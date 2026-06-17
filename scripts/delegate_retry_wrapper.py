#!/usr/bin/env python3
"""delegate_retry_wrapper.py — delegate_task 重试包装器 + Reflexion 自我反思

借鉴小红书文章「Hermes子agent委派兜底机制 — 17%→100%」
用 tenacity 库实现软/硬失败分类 + 指数退避 + jitter + 重试历史注入。
借鉴 Reflexion (Shinn et al., NeurIPS 2023) 实现 agent 自我反思。

用法:
  from delegate_retry_wrapper import delegate_with_retry
  result = delegate_with_retry(task={"goal": "..."}, context="...")
"""

import os, sys, uuid, hashlib, json, logging, uuid as _uuid
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta

# tenacity — 指数退避重试
try:
    from tenacity import retry, stop_after_attempt, wait_exponential, \
        retry_if_exception, before_sleep_log
    HAS_TENACITY = True
except ImportError:
    HAS_TENACITY = False

# ── 反思配置 ──────────────────────────────────────────
CONFIG_DIR = Path.home() / ".hermes" / "profiles" / "ai-investor" / "config"
REFLECTIONS_FILE = CONFIG_DIR / "agent_reflections.json"

REFLECTION_CONFIG = {
    "model": "deepseek/deepseek-v4-flash",
    "max_tokens": 500,
    "max_reflections": 3,
    "stale_days": 30,
    "stale_apply_threshold": 5,
}


# ── 失败类型分类 ──────────────────────────────────────

SOFT_FAILURES = (
    TimeoutError,
    ConnectionError,
    ConnectionResetError,
    ConnectionAbortedError,
    OSError,
    BrokenPipeError,
)

HARD_FAILURES = (
    ValueError,
    KeyError,
    TypeError,
    ImportError,
    ModuleNotFoundError,
    FileNotFoundError,
    PermissionError,
)


def is_soft_failure(exception: BaseException) -> bool:
    """判断是否为软失败（可重试）"""
    if isinstance(exception, SOFT_FAILURES):
        return True
    if isinstance(exception, HARD_FAILURES):
        return False
    # 字符串关键词匹配
    msg = str(exception).lower()
    soft_keywords = ["timeout", "connection", "network", "empty response",
                     "temporary", "rate limit", "too many requests"]
    hard_keywords = ["not found", "invalid", "not supported", "permission",
                     "not installed", "not configured", "missing"]
    for kw in soft_keywords:
        if kw in msg:
            return True
    for kw in hard_keywords:
        if kw in msg:
            return False
    return True


# ── subagent_id 跨重试保持 ────────────────────────────

_subagent_sessions: dict = {}
_session_template_names: dict = {}  # task_hash -> template_name


def _task_hash(task) -> str:
    raw = str(task)
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def get_or_create_session(task) -> str:
    h = _task_hash(task)
    if h not in _subagent_sessions:
        _subagent_sessions[h] = str(uuid.uuid4())
    return _subagent_sessions[h]


# ── 重试历史注入 ──────────────────────────────────────

_retry_context: str = ""


def inject_retry_history(retry_state):
    global _retry_context
    attempt = retry_state.attempt_number
    last_exception = retry_state.outcome.exception()
    last_exc_str = f"{type(last_exception).__name__}: {last_exception}" if last_exception else "未知"
    _retry_context = (
        f"[重试历史] 这是第 {attempt} 次尝试。"
        f"上一次失败原因: {last_exc_str}。"
        f"请特别注意避免同样的问题。"
    )


def build_context(original_context: str = "") -> str:
    global _retry_context
    if _retry_context:
        result = f"{original_context}\n\n{_retry_context}" if original_context else _retry_context
        _retry_context = ""
        return result
    return original_context


# ── Reflexion 自我反思 ────────────────────────────────

def _load_reflections() -> dict:
    """加载所有反思经验"""
    if not REFLECTIONS_FILE.exists():
        return {}
    try:
        return json.loads(REFLECTIONS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_reflections(reflections: dict):
    """原子写入反思经验"""
    REFLECTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REFLECTIONS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(reflections, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(REFLECTIONS_FILE)


def inject_reflections(template_name: str, context: str) -> str:
    """执行前注入历史反思经验"""
    if not template_name:
        return context
    reflections = _load_reflections()
    items = reflections.get(template_name, [])
    if not items:
        return context

    # 取最近 N 条有效经验
    valid = [r for r in items if not _is_stale(r)]
    recent = valid[-REFLECTION_CONFIG["max_reflections"]:]

    if not recent:
        return context

    exp_lines = ["\n\n## 历史经验参考\n"]
    for r in recent:
        exp_lines.append(f"- 曾失败原因: {r.get('root_cause', '未知')}")
        exp_lines.append(f"  改进方案: {r.get('improvement', '无')}")
        if r.get("needs_tools"):
            exp_lines.append(f"  建议工具: {', '.join(r['needs_tools'])}")
        # 更新 apply_count
        r["apply_count"] = r.get("apply_count", 0) + 1
        r["last_used"] = datetime.now().isoformat()

    _save_reflections(reflections)
    return context + "\n".join(exp_lines)


def reflect(template_name: str, goal: str, error: str) -> Optional[dict]:
    """agent 执行失败后自我反思（调用 LLM）"""
    if not error:
        return None

    try:
        from litellm import completion

        prompt = f"""你刚刚执行任务失败了。

模板: {template_name}
目标: {goal}
失败原因: {error}

请反思：
1. 失败的根本原因是什么？
2. 下次如何避免？
3. 需要补充什么工具或信息？

请只返回 JSON，不要包含任何其他文字：
{{"root_cause": "根本原因（一句话）", "improvement": "改进方案（一句话）", "needs_tools": ["工具1", "工具2"]}}"""

        resp = completion(
            model=REFLECTION_CONFIG["model"],
            messages=[
                {"role": "system", "content": "你是一个 agent 反思助手。请分析失败原因并输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            api_key=os.environ.get("DEEPSEEK_PRO_API_KEY", ""),
            api_base="https://api.deepseek.com",
            temperature=0.3,
            max_tokens=REFLECTION_CONFIG["max_tokens"],
        )
        raw = resp.choices[0].message.content.strip()

        import re
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            return None

        data = json.loads(json_match.group())
        reflection = {
            "id": str(_uuid.uuid4())[:8],
            "root_cause": data.get("root_cause", "未知"),
            "improvement": data.get("improvement", ""),
            "needs_tools": data.get("needs_tools", []),
            "created_at": datetime.now().isoformat(),
            "last_used": datetime.now().isoformat(),
            "success_count": 0,
            "apply_count": 0,
        }

        # 存储
        reflections = _load_reflections()
        if template_name not in reflections:
            reflections[template_name] = []
        reflections[template_name].append(reflection)
        _save_reflections(reflections)

        return reflection

    except Exception as e:
        logging.warning(f"反思失败: {e}")
        return None


def on_success(template_name: str, reflection_id: str = None):
    """执行成功后更新反思经验的 success_count"""
    if not template_name or not reflection_id:
        return
    reflections = _load_reflections()
    items = reflections.get(template_name, [])
    for r in items:
        if r.get("id") == reflection_id:
            r["success_count"] = r.get("success_count", 0) + 1
            r["last_used"] = datetime.now().isoformat()
            break
    _save_reflections(reflections)


def _is_stale(r: dict) -> bool:
    """经验是否过期"""
    try:
        created = datetime.fromisoformat(r.get("created_at", ""))
        age = datetime.now() - created
        if age > timedelta(days=REFLECTION_CONFIG["stale_days"]):
            return True
        if r.get("success_count", 0) == 0 and r.get("apply_count", 0) > REFLECTION_CONFIG["stale_apply_threshold"]:
            return True
    except Exception:
        pass
    return False


def cleanup_reflections():
    """清理过期经验"""
    reflections = _load_reflections()
    changed = False
    for template_name in list(reflections.keys()):
        items = reflections[template_name]
        active = [r for r in items if not _is_stale(r)]
        if len(active) != len(items):
            if active:
                reflections[template_name] = active
            else:
                del reflections[template_name]
            changed = True
    if changed:
        _save_reflections(reflections)


# ── 重试配置 ──────────────────────────────────────────

RETRY_CONFIG = {
    "max_attempts": int(os.environ.get("RETRY_MAX_ATTEMPTS", "3")),
    "min_wait": int(os.environ.get("RETRY_MIN_WAIT", "2")),
    "max_wait": int(os.environ.get("RETRY_MAX_WAIT", "30")),
    "multiplier": int(os.environ.get("RETRY_MULTIPLIER", "2")),
}


# ── 主入口 ─────────────────────────────────────────────

def delegate_with_retry(task, context="", toolsets=None):
    """包装 delegate_task，带重试 + 反思"""
    if not HAS_TENACITY:
        return _do_delegate(task, context, toolsets)

    session_id = get_or_create_session(task)
    template_name = task.get("template_name", "")

    # 注入历史反思经验
    context = inject_reflections(template_name, context)

    # 构建最终 context
    final_context = build_context(context)

    try:
        result = _delegate_with_retry_inner(task, final_context, toolsets, session_id)
        # 成功：更新反思经验
        if template_name:
            on_success(template_name, task.get("_reflection_id"))
        return result
    except Exception as e:
        # 失败：触发反思
        reflect(template_name, task.get("goal", ""), str(e))
        raise


@retry(
    stop=stop_after_attempt(RETRY_CONFIG["max_attempts"]),
    wait=wait_exponential(
        multiplier=RETRY_CONFIG["multiplier"],
        min=RETRY_CONFIG["min_wait"],
        max=RETRY_CONFIG["max_wait"],
    ),
    retry=retry_if_exception(is_soft_failure),
    before_sleep=inject_retry_history,
    reraise=True,
)
def _delegate_with_retry_inner(task, context, toolsets, session_id):
    final_context = build_context(context)
    return _do_delegate(task, final_context, toolsets, session_id)


def _do_delegate(task, context, toolsets, session_id=None):
    raise NotImplementedError(
        "delegate_with_retry 需要在 Hermes Agent 环境中使用。\n"
        "请通过 execute_code 或 terminal 调用:\n"
        "  from hermes_tools import delegate_task\n"
        "  result = delegate_task(goal=task['goal'], context=context, toolsets=toolsets)"
    )


# ── 测试/调试 ─────────────────────────────────────────

def _test():
    """测试反思 + 重试逻辑"""
    import time

    # 测试 1: 反思存储
    print("=== 测试 1: 反思存储 ===")
    reflection = reflect("macro", "测试任务", "TimeoutError: API 超时")
    if reflection:
        print(f"  ✅ 反思已存储: {reflection['root_cause']}")
    else:
        print(f"  ⚠️ 反思未执行（LLM 不可用）")

    # 测试 2: 经验注入
    print("\n=== 测试 2: 经验注入 ===")
    ctx = inject_reflections("macro", "原始上下文")
    if "历史经验" in ctx:
        print(f"  ✅ 经验已注入 (context 长度: {len(ctx)})")
    else:
        print(f"  ⚠️ 无经验注入")

    # 测试 3: 过期清理
    print("\n=== 测试 3: 过期清理 ===")
    cleanup_reflections()
    reflections = _load_reflections()
    total = sum(len(v) for v in reflections.values())
    print(f"  ✅ 清理后剩余 {total} 条经验")

    # 测试 4: 软/硬失败分类
    print("\n=== 测试 4: 失败分类 ===")
    assert is_soft_failure(TimeoutError("test")) == True
    assert is_soft_failure(ValueError("test")) == False
    print("  ✅ 软/硬失败分类正确")

    print(f"\n{'='*40}")
    print("🎉 测试完成")
    print(f"{'='*40}")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
    elif "--cleanup" in sys.argv:
        cleanup_reflections()
        print("✅ 过期经验已清理")
    else:
        print(__doc__)
