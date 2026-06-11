"""
checkpoint_utils.py — 通用流水线 Checkpoint 工具

用途: 为 Hermes workflow (ARCH→REVIEW→ENGINE) 和 KMS 流水线
      (视频管线、研究报告生成) 提供文件级中断恢复能力。

设计原则:
- 幂等: 重复调用 step_done 不会产生副作用
- 无状态: 所有状态存文件, 不依赖内存
- 轻量: 无外部依赖, 仅用 json + pathlib
- 并发安全: fcntl.flock 文件锁 + 原子写入 (防崩溃截断)

API:
    start(name, total_steps, steps_plan, metadata)
    step_done(name, step_id, output)
    get_state(name) -> dict | None
    resume_from(name) -> int
    clear(name)
    list_all() -> list[dict]
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

# ── 文件锁 (POSIX) ──────────────────────────────────────
try:
    import fcntl
    _HAS_FLOCK = True
except ImportError:
    _HAS_FLOCK = False  # Windows, 回退到无锁模式


# ── 路径配置 ──────────────────────────────────────────────
# 尝试从 _path_setup 导入, 否则用相对兜底
try:
    from _path_setup import CHECKPOINT_DIR
except ImportError:
    CHECKPOINT_DIR = Path(__file__).resolve().parent.parent / "config" / "cache" / "checkpoints"
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)


def _file_path(name: str) -> Path:
    """获取 checkpoint 文件路径。"""
    if not name or not name.strip():
        raise ValueError("checkpoint name 不能为空")
    safe_name = name.replace("/", "_").replace("\\", "_")
    return CHECKPOINT_DIR / f"{safe_name}.checkpoint.json"


def _read_file(fp: Path) -> dict:
    """不加锁的文件读取 (锁由调用方 context 管理)。"""
    with open(fp, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_file(fp: Path, state: dict) -> None:
    """不加锁的原子写入 (锁由调用方 context 管理)。"""
    tmp = fp.parent / f"{fp.name}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, fp)


def _lock_path(fp: Path) -> Path:
    """获取与 checkpoint 配套的 lock 文件路径。"""
    return fp.parent / f"{fp.name}.lock"


def _acquire_lock(fp: Path, shared: bool = False) -> int:
    """获取文件锁, 返回 fd (调用方必须确保 close)。
    
    使用独立的 .lock 文件, 避免 open(tmp) truncate 与 flock 的竞态。
    """
    lock_fp = _lock_path(fp)
    fd = os.open(str(lock_fp), os.O_CREAT | os.O_RDWR)
    lock_flag = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    fcntl.flock(fd, lock_flag)
    return fd


def _release_lock(fd: int) -> None:
    """释放文件锁。"""
    if _HAS_FLOCK:
        fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def _read_atomic(fp: Path) -> dict:
    """原子读取: 加共享锁后读取完整 JSON。"""
    lock_fd = _acquire_lock(fp, shared=True)
    try:
        return _read_file(fp)
    finally:
        _release_lock(lock_fd)


def _write_atomic(fp: Path, state: dict) -> None:
    """原子写入: 加排他锁后写 tmp → os.replace。

    tmp 和目标文件在同一目录, 不会触发 EXDEV。
    仅供外部只读/只写场景使用 — 读-改-写用 _exclusive_transaction()。
    """
    lock_fd = _acquire_lock(fp, shared=False)
    try:
        _write_file(fp, state)
    finally:
        _release_lock(lock_fd)


def _exclusive_transaction(fp: Path, modifier):
    """读-改-写事务: 全程在排他锁下进行。

    Args:
        fp: checkpoint 文件路径
        modifier: callable(state) -> state, 在锁内执行

    Returns:
        修改后的 state
    """
    lock_fd = _acquire_lock(fp, shared=False)
    try:
        state = _read_file(fp)
        modifier(state)
        _write_file(fp, state)
        return state
    finally:
        _release_lock(lock_fd)


# ═══════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════

def start(name: str, total_steps: int,
          steps_plan: Optional[list[dict]] = None,
          metadata: Optional[dict] = None) -> dict:
    """创建或重置 checkpoint。

    幂等: 已存在的 checkpoint 不会覆盖, 返回已存在的内容。
    如需重置, 先调 clear()。

    Args:
        name: 流水线唯一标识 (同时也是 checkpoint_key)
        total_steps: 步骤总数
        steps_plan: 步骤计划列表, 每项至少含 {"id": str, "name": str}
        metadata: 附加元数据 (如 goal 等)

    Returns:
        创建的 state dict
    """
    fp = _file_path(name)
    if fp.exists():
        return _read_atomic(fp)

    state = {
        "checkpoint_key": name,
        "pipeline": name,
        "created_at": _now(),
        "updated_at": _now(),
        "total_steps": total_steps,
        "completed_steps": [],
        "steps_plan": steps_plan or [],
        "status": "in_progress",
        "metadata": metadata or {},
    }
    fp.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(fp, state)
    return state


def step_done(name: str, step_id: str,
              output: Optional[dict] = None) -> dict:
    """标记一个步骤为已完成。

    幂等: 重复标记同一 step_id 不会产生副作用。
    并发安全: 读-改-写全程在排他锁下进行。
    """
    fp = _file_path(name)
    if not fp.exists():
        raise FileNotFoundError(
            f"Checkpoint '{name}' 不存在, 请先调 start()")

    def _modifier(state):
        if step_id not in state["completed_steps"]:
            state["completed_steps"].append(step_id)
            if output:
                state.setdefault("step_outputs", {})[step_id] = output
            state["updated_at"] = _now()

    return _exclusive_transaction(fp, _modifier)


def get_state(name: str) -> Optional[dict]:
    """读取 checkpoint 状态。

    Returns:
        dict 如果存在, None 如果不存在 (用于区别"从头开始"和"有进度")
    """
    fp = _file_path(name)
    if not fp.exists():
        return None
    return _read_atomic(fp)


def resume_from(name: str) -> int:
    """返回应续跑的步骤索引。

    判断逻辑:
        1. checkpoint 不存在 → 返回 0 (从头开始)
        2. 有 steps_plan → 返回第一个未完成的步骤索引
        3. 全部完成 → 返回 total_steps (等同于结束)
        4. 没有 steps_plan 但有 completed_steps → 返回 len(completed_steps)

    Returns:
        int: 步骤索引 (0-based), 从该索引开始执行
    """
    state = get_state(name)
    if state is None:
        return 0

    steps_plan = state.get("steps_plan", [])
    completed = set(state.get("completed_steps", []))

    if not steps_plan:
        return len(completed)

    for i, step in enumerate(steps_plan):
        if not isinstance(step, dict):
            return i
        if step.get("id", "") not in completed:
            return i
    return len(steps_plan)


def clear(name: str) -> None:
    """删除 checkpoint 文件 (含 tmp 残留)。"""
    fp = _file_path(name)
    if fp.exists():
        fp.unlink()
    # 清理可能残留的 tmp 和 lock 文件
    for suffix in [".tmp", ".lock"]:
        extra = fp.parent / f"{fp.name}{suffix}"
        if extra.exists():
            extra.unlink()


def list_all() -> list[dict]:
    """列出所有活跃 checkpoint。"""
    results = []
    for fp in sorted(CHECKPOINT_DIR.glob("*.checkpoint.json")):
        try:
            results.append(_read_atomic(fp))
        except (json.JSONDecodeError, OSError):
            # 损坏的文件不报错, 跳过
            continue
    return results


def mark_complete(name: str) -> dict:
    """将流水线标记为已完成。自动补全所有未标记步骤。"""
    fp = _file_path(name)
    if not fp.exists():
        raise FileNotFoundError(
            f"Checkpoint '{name}' 不存在, 请先调 start()")

    def _modifier(state):
        state["status"] = "completed"
        state["updated_at"] = _now()
        all_ids = {s["id"] for s in state.get("steps_plan", []) if isinstance(s, dict)}
        for sid in all_ids:
            if sid not in state["completed_steps"]:
                state["completed_steps"].append(sid)

    return _exclusive_transaction(fp, _modifier)


# ═══════════════════════════════════════════════════════════
# 内部工具
# ═══════════════════════════════════════════════════════════

def _now() -> str:
    """返回 ISO 格式时间戳。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


# ═══════════════════════════════════════════════════════════
# CLI 入口 (调试用)
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python checkpoint_utils.py <command> [args...]")
        print("命令: list, show <name>, clear <name>")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "list":
        for cp in list_all():
            print(f"  {cp['checkpoint_key']}: {cp['status']} "
                  f"({len(cp['completed_steps'])}/{cp['total_steps']})")
    elif cmd == "show" and len(sys.argv) > 2:
        state = get_state(sys.argv[2])
        if state:
            print(json.dumps(state, ensure_ascii=False, indent=2))
        else:
            print(f"Checkpoint '{sys.argv[2]}' 不存在")
    elif cmd == "clear" and len(sys.argv) > 2:
        clear(sys.argv[2])
        print(f"已清除 checkpoint '{sys.argv[2]}'")
    else:
        print(f"未知命令: {cmd}")
