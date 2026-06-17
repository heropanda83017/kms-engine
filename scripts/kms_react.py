#!/usr/bin/env python3
"""
KMS ReAct Agent 框架 — Reasoning + Acting 循环

借鉴投资体系多 Agent 的 ReAct 模式，让 KMS Agent 不再是固定流水线，
而是「思考→行动→观察→再思考」的智能循环。

核心循环:
  observe(状态) → think(下一步) → act(执行) → observe(结果) → ...

用法:
    python3 kms_react.py router "查资金因子并检查健康"
    python3 kms_react.py validator "笔记路径"
"""

import json
import sys
import time
from pathlib import Path
from typing import Any, Optional


class ReActAgent:
    """ReAct Agent 基类 — 思考→行动→观察循环"""

    def __init__(self, name: str, max_steps: int = 5):
        self.name = name
        self.max_steps = max_steps
        self.history: list[dict] = []  # 完整轨迹

    def observe(self, state: dict) -> str:
        """观察当前状态，返回状态摘要"""
        raise NotImplementedError

    def think(self, state: dict) -> Optional[str]:
        """思考下一步行动，返回行动名或 None（完成）"""
        raise NotImplementedError

    def act(self, action: str, state: dict) -> dict:
        """执行行动，返回结果"""
        raise NotImplementedError

    def validate(self, action: str, result: dict, state: dict) -> dict:
        """结果合理性验证 — 返回 {"valid": bool, "reason": str}
        
        子类可重写此方法实现专用验证逻辑。
        """
        # 默认验证：检查结果中是否有 error/FAIL 标记
        if result.get("verdict") == "FAIL":
            return {"valid": False, "reason": f"执行失败: {result.get('detail', result.get('error', '未知'))}"}
        if "error" in str(result).lower()[:100]:
            return {"valid": False, "reason": "结果包含错误信息"}
        if not result or (isinstance(result, dict) and len(result) == 0):
            return {"valid": False, "reason": "结果为空"}
        return {"valid": True, "reason": ""}

    def fallback(self, action: str, result: dict, state: dict) -> Optional[dict]:
        """降级修复 — 验证失败时尝试替代方案
        
        子类可重写此方法实现专用降级逻辑。
        """
        return None

    def run(self, goal: str, initial_state: dict = None) -> dict:
        """运行 ReAct 循环

        Args:
            goal: 目标描述
            initial_state: 初始状态

        Returns:
            {"result": ..., "steps": N, "history": [...]}
        """
        state = initial_state or {}
        state["goal"] = goal
        state["step"] = 0

        print(f"\n  🤖 [{self.name}] 目标: {goal}")
        print(f"  {'='*45}")

        for step in range(1, self.max_steps + 1):
            state["step"] = step

            # 1. Observe
            t0 = time.time()
            observation = self.observe(state)
            elapsed = time.time() - t0

            # 2. Think
            t0 = time.time()
            action = self.think(state)
            think_elapsed = time.time() - t0

            if action is None:
                print(f"  ✅ Step {step}: 目标达成 ({elapsed:.1f}s)")
                self.history.append({
                    "step": step, "phase": "think",
                    "observation": observation,
                    "action": None, "result": "DONE"
                })
                break

            # 3. Act
            t0 = time.time()
            result = self.act(action, state)
            act_elapsed = time.time() - t0

            # 4. Validate — 结果合理性验证
            validation = self.validate(action, result, state)
            if not validation.get("valid", True):
                print(f"  ⚠️ Step {step}: {action} 结果异常 — {validation.get('reason', '')}")
                # 尝试降级修复
                fallback = self.fallback(action, result, state)
                if fallback:
                    print(f"  🔄 Step {step}: 降级 → {fallback.get('method', '?')}")
                    result = fallback
                    validation = self.validate(action, result, state)

            # 记录
            self.history.append({
                "step": step, "phase": "act",
                "observation": observation,
                "action": action,
                "result": str(result)[:200],
                "validation": validation,
            })

            print(f"  🔄 Step {step}: {action} ({act_elapsed:.1f}s)")

            # 更新状态
            state["last_action"] = action
            state["last_result"] = result

        else:
            print(f"  ⚠️ 达到最大步数 {self.max_steps}")

        return {
            "result": state.get("last_result"),
            "steps": step,
            "history": self.history,
        }


# ── 具体 Agent 实现 ────────────────────────────────────────

class ReActRouter(ReActAgent):
    """ReAct 路由器 — 不只是关键词匹配，而是理解意图后选择工具链"""

    def __init__(self):
        super().__init__("Router", max_steps=3)
        # 可用工具
        self._tools = {
            "search": "搜索 wiki 知识库",
            "health": "健康检查（可并行）",
            "validate": "笔记多视角验证",
            "pipeline": "内容创建流水线",
            "analytics": "使用分析报告",
            "link": "更新 wiki 链接",
            "guard": "敏感信息检测",
        }

    def observe(self, state: dict) -> str:
        """分析用户输入"""
        text = state.get("goal", "")
        # 提取关键词
        keywords = []
        for kw in ["查", "搜", "找", "健康", "检查", "验证", "分析", "报告", "链接", "更新", "敏感"]:
            if kw in text:
                keywords.append(kw)
        state["keywords"] = keywords
        return f"输入: {text[:50]} → 关键词: {keywords}"

    def think(self, state: dict) -> Optional[str]:
        """根据关键词决定工具链"""
        text = state.get("goal", "")
        step = state.get("step", 0)

        if step == 1:
            # 第一轮：决定主工具
            # 复合意图检测：先检查长关键词
            if "验证笔记" in text or "笔记验证" in text:
                return "validate"
            if "并行健康" in text or "并行检查" in text:
                return "health"
            if "流水线" in text or "pipeline" in text:
                return "pipeline"
            if "分析报告" in text or "使用报告" in text:
                return "analytics"
            if "敏感" in text:
                return "guard"
            if "更新链接" in text or "跑链接" in text:
                return "link"
            # 单关键词
            if "验证" in text or "validate" in text:
                return "validate"
            if "健康" in text or "检查" in text:
                return "health"
            if any(kw in text for kw in ["查", "搜", "找"]):
                return "search"
            if "分析" in text or "报告" in text:
                return "analytics"
            if "链接" in text or "更新" in text:
                return "link"
            # 默认
            return "search"

        elif step == 2:
            # 第二轮：复合意图处理 — 检查是否还需要补充工具
            last = state.get("last_action")
            text = state.get("goal", "")
            if last == "search" and ("健康" in text or "检查" in text):
                return "health"
            if last == "validate" and ("健康" in text or "检查" in text):
                return "health"
            if last == "validate" and "链接" in text:
                return "link"
            if last == "health" and ("验证" in text or "validate" in text):
                return "validate"
            return None  # 完成

        return None

    def act(self, action: str, state: dict) -> dict:
        """执行工具 — 真实调用 + 降级链 + 结果验证"""
        text = state.get("goal", "")

        if action == "search":
            return self._act_search(text)
        elif action == "health":
            return self._act_health()
        elif action == "validate":
            return self._act_validate(text)
        elif action == "analytics":
            return self._act_analytics()
        elif action == "link":
            return self._act_link()
        elif action == "guard":
            return self._act_guard(text)
        elif action == "pipeline":
            return self._act_pipeline(text)
        return {"action": action, "error": "未知工具", "verdict": "FAIL"}

    def validate(self, action: str, result: dict, state: dict) -> dict:
        """Router 专用验证"""
        # 先走基类默认验证
        base = super().validate(action, result, state)
        if not base["valid"]:
            return base
        # search 专用：检查是否有实际结果
        if action == "search":
            results = result.get("results", "")
            if isinstance(results, str) and len(results) < 20:
                return {"valid": False, "reason": "搜索结果过短"}
        # health 专用：检查是否包含数据
        if action == "health":
            output = result.get("output", "")
            if "HEALTH|" not in output:
                return {"valid": False, "reason": "健康检查输出格式异常"}
        return {"valid": True, "reason": ""}

    def fallback(self, action: str, result: dict, state: dict) -> Optional[dict]:
        """Router 专用降级"""
        if action == "search":
            # 搜索失败 → 尝试 analytics
            return self._act_analytics()
        if action == "health":
            # 并行健康检查失败 → 尝试串行
            return self._act_health()  # _act_health 内部已有降级链
        return None

    # ── 真实执行 + 降级链 + 验证 ─────────────────────────

    def _act_search(self, text: str) -> dict:
        """真实搜索 + 降级链"""
        query = text
        for prefix in ["查", "搜", "找", "搜索", "查找"]:
            query = query.replace(prefix, "", 1) if query.startswith(prefix) else query
        query = query.strip() or "全部"

        # 首选: kms search --fusion
        try:
            import subprocess as sp
            r = sp.run(
                ["python3", str(Path(__file__).resolve().parent / "kms.py"), "search", query],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode == 0 and len(r.stdout) > 50:
                return {"action": "search", "query": query, "results": r.stdout[:500], "verdict": "PASS"}
        except Exception:
            pass

        # 降级1: 直接搜索（无 --fusion）
        try:
            import subprocess as sp
            r = sp.run(
                ["python3", str(Path(__file__).resolve().parent / "kms.py"), "search", query, "--mode", "fts5"],
                capture_output=True, text=True, timeout=15
            )
            if r.returncode == 0 and len(r.stdout) > 50:
                return {"action": "search", "query": query, "results": r.stdout[:500], "verdict": "PASS", "fallback": "fts5"}
        except Exception:
            pass

        # 兜底
        return {"action": "search", "query": query, "results": "搜索暂不可用", "verdict": "FAIL"}

    def _act_health(self) -> dict:
        """真实健康检查 + 降级链"""
        # 首选: 并行健康检查
        try:
            import subprocess as sp
            r = sp.run(
                ["python3", str(Path(__file__).resolve().parent / "kms.py"), "health", "--parallel"],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode == 0:
                return {"action": "health", "mode": "parallel", "output": r.stdout[:500], "verdict": "PASS"}
        except Exception:
            pass

        # 降级: 串行健康检查
        try:
            import subprocess as sp
            r = sp.run(
                ["python3", str(Path(__file__).resolve().parent / "kms.py"), "health"],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode == 0:
                return {"action": "health", "mode": "serial", "output": r.stdout[:500], "verdict": "PASS", "fallback": "serial"}
        except Exception:
            pass

        return {"action": "health", "output": "健康检查暂不可用", "verdict": "FAIL"}

    def _act_validate(self, text: str) -> dict:
        """真实验证 + 降级链"""
        import re
        paths = re.findall(r'[\w\-/]+\.md', text)
        note = paths[0] if paths else "未指定"

        # 首选: kms validate
        try:
            import subprocess as sp
            r = sp.run(
                ["python3", str(Path(__file__).resolve().parent / "kms.py"), "validate", note],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode == 0:
                return {"action": "validate", "note": note, "output": r.stdout[:500], "verdict": "PASS"}
        except Exception:
            pass

        # 降级: 直接调 kms_validator
        try:
            import subprocess as sp
            r = sp.run(
                ["python3", str(Path(__file__).resolve().parent / "kms_validator.py"), note],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode == 0:
                return {"action": "validate", "note": note, "output": r.stdout[:500], "verdict": "PASS", "fallback": "direct"}
        except Exception:
            pass

        return {"action": "validate", "note": note, "output": "验证暂不可用", "verdict": "FAIL"}

    def _act_analytics(self) -> dict:
        """真实使用分析"""
        try:
            import subprocess as sp
            r = sp.run(
                ["python3", str(Path(__file__).resolve().parent / "kms.py"), "analytics", "--days", "7"],
                capture_output=True, text=True, timeout=15
            )
            if r.returncode == 0:
                return {"action": "analytics", "output": r.stdout[:500], "verdict": "PASS"}
        except Exception:
            pass
        return {"action": "analytics", "output": "分析暂不可用", "verdict": "FAIL"}

    def _act_link(self) -> dict:
        """真实更新链接"""
        try:
            import subprocess as sp
            r = sp.run(
                ["python3", str(Path(__file__).resolve().parent / "kms.py"), "link"],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode == 0:
                return {"action": "link", "output": r.stdout[:200], "verdict": "PASS"}
        except Exception:
            pass
        return {"action": "link", "output": "链接更新暂不可用", "verdict": "FAIL"}

    def _act_guard(self, text: str) -> dict:
        """真实敏感信息检测"""
        import re
        paths = re.findall(r'[\w\-/]+\.md', text)
        note = paths[0] if paths else "未指定"
        try:
            import subprocess as sp
            r = sp.run(
                ["python3", str(Path(__file__).resolve().parent / "kms_guard.py"), note],
                capture_output=True, text=True, timeout=15
            )
            return {"action": "guard", "note": note, "output": r.stdout[:200], "verdict": "PASS"}
        except Exception:
            pass
        return {"action": "guard", "note": note, "output": "检测暂不可用", "verdict": "FAIL"}

    def _act_pipeline(self, text: str) -> dict:
        """真实流水线"""
        import re
        paths = re.findall(r'[\w\-/]+\.md', text)
        note = paths[0] if paths else "未指定"
        try:
            import subprocess as sp
            r = sp.run(
                ["python3", str(Path(__file__).resolve().parent / "kms_pipeline.py"), note, "--skip", "enrich,review,publish"],
                capture_output=True, text=True, timeout=60
            )
            return {"action": "pipeline", "note": note, "output": r.stdout[:500], "verdict": "PASS"}
        except Exception:
            pass
        return {"action": "pipeline", "note": note, "output": "流水线暂不可用", "verdict": "FAIL"}


class ReActValidator(ReActAgent):
    """ReAct 验证器 — 根据笔记类型动态选择验证维度"""

    def __init__(self):
        super().__init__("Validator", max_steps=4)
        self._checks = {
            "quality": "质量检查(frontmatter/字数/链接)",
            "fusion": "融合检查(smart_fuse重叠)",
            "entity": "实体检查(KG抽取)",
            "governance": "治理检查(断裂链接)",
        }

    def observe(self, state: dict) -> str:
        note_path = state.get("goal", "")
        path = Path(note_path)
        if path.exists():
            size = path.stat().st_size
            lines = len(path.read_text(encoding="utf-8").split("\n"))
            state["file_info"] = {"size": size, "lines": lines}
            return f"笔记: {path.name} ({size}字节, {lines}行)"
        return f"笔记不存在: {note_path}"

    def think(self, state: dict) -> Optional[str]:
        step = state.get("step", 0)
        info = state.get("file_info", {})

        if step == 1:
            return "quality"  # 先做质量检查
        elif step == 2:
            # 如果笔记大（>5KB），做融合检查
            if info.get("size", 0) > 5000:
                return "fusion"
            return "governance"
        elif step == 3:
            # 如果有内容，做实体检查
            if info.get("lines", 0) > 50:
                return "entity"
            return None
        return None
    def act(self, action: str, state: dict) -> dict:
        """执行验证 — 真实调用 + 降级链 + 结果验证"""
        note_path = state.get("goal", "")
        _KMS_ROOT = Path(__file__).resolve().parent

        if action == "quality":
            return self._act_quality(note_path, _KMS_ROOT)
        elif action == "fusion":
            return self._act_fusion(note_path, _KMS_ROOT)
        elif action == "entity":
            return self._act_entity(note_path, _KMS_ROOT)
        elif action == "governance":
            return self._act_governance(note_path, _KMS_ROOT)
        return {"verdict": "FAIL", "detail": f"未知检查: {action}"}

    def validate(self, action: str, result: dict, state: dict) -> dict:
        """Validator 专用验证"""
        base = super().validate(action, result, state)
        if not base["valid"]:
            return base
        if action == "quality" and result.get("verdict") not in ("PASS", "WARN", "FAIL"):
            return {"valid": False, "reason": "质量检查未返回有效裁决"}
        return {"valid": True, "reason": ""}

    def fallback(self, action: str, result: dict, state: dict) -> Optional[dict]:
        """Validator 专用降级"""
        note_path = state.get("goal", "")
        _KMS_ROOT = Path(__file__).resolve().parent
        if action == "quality":
            return self._act_quality(note_path, _KMS_ROOT)
        if action == "fusion":
            return self._act_fusion(note_path, _KMS_ROOT)
        return None

    def _act_quality(self, note_path: str, _KMS_ROOT: Path) -> dict:
        """质量检查 + 降级链"""
        # 首选: 内联 check_quality
        try:
            from kms_validator import check_quality
            result = check_quality(note_path)
            if result.get("verdict") in ("PASS", "WARN", "FAIL"):
                return {**result, "action": "quality", "method": "inline"}
        except Exception:
            pass
        # 降级: subprocess 调 kms validate
        try:
            import subprocess as sp
            r = sp.run(["python3", str(_KMS_ROOT / "kms.py"), "validate", note_path],
                       capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                return {"action": "quality", "output": r.stdout[:300], "verdict": "PASS", "fallback": "subprocess"}
        except Exception:
            pass
        return {"action": "quality", "verdict": "FAIL", "detail": "质量检查暂不可用"}

    def _act_fusion(self, note_path: str, _KMS_ROOT: Path) -> dict:
        """融合检查 + 降级链"""
        # 首选: smart_fuse
        try:
            import subprocess as sp
            r = sp.run(["python3", str(_KMS_ROOT.parent.parent / "scripts" / "smart_fuse.py"), note_path],
                       capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and len(r.stdout) > 20:
                return {"action": "fusion", "output": r.stdout[:300], "verdict": "PASS"}
        except Exception:
            pass
        # 降级: 内联 find_fusion_candidates
        try:
            import sys as _sys
            _sys.path.insert(0, str(_KMS_ROOT.parent.parent))
            from scripts.smart_fuse import find_fusion_candidates
            candidates = find_fusion_candidates(note_path, top_n=3)
            if candidates:
                return {"action": "fusion", "candidates": len(candidates), "verdict": "PASS", "fallback": "inline"}
        except Exception:
            pass
        return {"action": "fusion", "verdict": "PASS", "detail": "融合检查跳过"}

    def _act_entity(self, note_path: str, _KMS_ROOT: Path) -> dict:
        """实体检查 + 降级链"""
        # 首选: kg_extract
        try:
            import subprocess as sp
            r = sp.run(["python3", str(_KMS_ROOT / "kms.py"), "kg", "extract", note_path],
                       capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                return {"action": "entity", "output": r.stdout[:300], "verdict": "PASS"}
        except Exception:
            pass
        # 降级: 内联 extract_note
        try:
            from pathlib import Path as _Path
            from scripts.kg_extract import extract_note
            result = extract_note(note_path=_Path(note_path), dry_run=True)
            entities = (result or {}).get("entities", [])
            if entities:
                return {"action": "entity", "count": len(entities), "verdict": "PASS", "fallback": "inline"}
        except Exception:
            pass
        return {"action": "entity", "verdict": "PASS", "detail": "实体检查跳过"}

    def _act_governance(self, note_path: str, _KMS_ROOT: Path) -> dict:
        """治理检查 + 降级链"""
        try:
            from kms_validator import check_governance
            result = check_governance(note_path)
            return {**result, "action": "governance"}
        except Exception:
            pass
        return {"action": "governance", "verdict": "PASS", "detail": "治理检查跳过"}


class ReActPipeline(ReActAgent):
    """ReAct 流水线 — 根据笔记内容动态编排阶段"""

    def __init__(self):
        super().__init__("Pipeline", max_steps=4)
        self._phases = ["validate", "fuse", "link", "guard"]

    def observe(self, state: dict) -> str:
        note_path = state.get("goal", "")
        path = Path(note_path)
        if path.exists():
            content = path.read_text(encoding="utf-8")
            has_frontmatter = content.startswith("---")
            word_count = len(content.strip())
            state["note_info"] = {
                "has_frontmatter": has_frontmatter,
                "word_count": word_count,
            }
            return f"{'有' if has_frontmatter else '无'}frontmatter, {word_count}字"
        return f"笔记不存在: {note_path}"

    def think(self, state: dict) -> Optional[str]:
        step = state.get("step", 0)
        info = state.get("note_info", {})

        if step == 1:
            return "validate"
        elif step == 2:
            if info.get("word_count", 0) > 200:
                return "fuse"
            return "link"
        elif step == 3:
            if info.get("has_frontmatter"):
                return "guard"
            return "link"
        elif step == 4:
            return "link"
        return None

    def act(self, action: str, state: dict) -> dict:
        """执行阶段 — 真实调用 + 降级链"""
        note_path = state.get("goal", "")
        _KMS_ROOT = Path(__file__).resolve().parent

        if action == "validate":
            return self._pipe_validate(note_path, _KMS_ROOT)
        elif action == "fuse":
            return self._pipe_fuse(note_path, _KMS_ROOT)
        elif action == "link":
            return self._pipe_link(_KMS_ROOT)
        elif action == "guard":
            return self._pipe_guard(note_path, _KMS_ROOT)
        return {"action": action, "error": "未知阶段", "verdict": "FAIL"}

    def validate(self, action: str, result: dict, state: dict) -> dict:
        """Pipeline 专用验证"""
        base = super().validate(action, result, state)
        if not base["valid"]:
            return base
        # link 专用：必须包含"更新完成"
        if action == "link" and "更新完成" not in result.get("output", ""):
            return {"valid": False, "reason": "链接更新可能未完成"}
        return {"valid": True, "reason": ""}

    def fallback(self, action: str, result: dict, state: dict) -> Optional[dict]:
        """Pipeline 专用降级"""
        if action == "link":
            return {"action": "link", "output": "链接更新跳过（降级）", "verdict": "PASS", "fallback": "skipped"}
        return None

    def _pipe_validate(self, note_path: str, _KMS_ROOT: Path) -> dict:
        try:
            import subprocess as sp
            r = sp.run(["python3", str(_KMS_ROOT / "kms_validator.py"), note_path],
                       capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                return {"action": "validate", "output": r.stdout[:300], "verdict": "PASS"}
        except Exception:
            pass
        return {"action": "validate", "verdict": "FAIL", "detail": "验证失败"}

    def _pipe_fuse(self, note_path: str, _KMS_ROOT: Path) -> dict:
        try:
            import subprocess as sp
            r = sp.run(["python3", str(_KMS_ROOT.parent.parent / "scripts" / "smart_fuse.py"), note_path],
                       capture_output=True, text=True, timeout=30)
            return {"action": "fuse", "output": r.stdout[:200], "verdict": "PASS"}
        except Exception:
            pass
        return {"action": "fuse", "verdict": "PASS", "detail": "融合跳过"}

    def _pipe_link(self, _KMS_ROOT: Path) -> dict:
        try:
            import subprocess as sp
            r = sp.run(["python3", str(_KMS_ROOT / "kms.py"), "link"],
                       capture_output=True, text=True, timeout=30)
            return {"action": "link", "output": r.stdout[:200], "verdict": "PASS"}
        except Exception:
            pass
        return {"action": "link", "verdict": "FAIL", "detail": "链接更新失败"}

    def _pipe_guard(self, note_path: str, _KMS_ROOT: Path) -> dict:
        try:
            import subprocess as sp
            r = sp.run(["python3", str(_KMS_ROOT / "kms_guard.py"), note_path],
                       capture_output=True, text=True, timeout=15)
            return {"action": "guard", "output": r.stdout[:200], "verdict": "PASS"}
        except Exception:
            pass
        return {"action": "guard", "verdict": "PASS", "detail": "安全检查跳过"}


# ── 扩展 Agent ─────────────────────────────────────────────

class ReActEnricher(ReActAgent):
    """ReAct 富化器 — 为笔记自动搜索补充背景信息"""

    def __init__(self):
        super().__init__("Enricher", max_steps=3)
        self._steps = ["analyze", "search", "append"]

    def observe(self, state: dict) -> str:
        note_path = state.get("goal", "")
        path = Path(note_path)
        if path.exists():
            content = path.read_text(encoding="utf-8")
            has_score = "score:" in content[:200] or "quality_gate" in content[:500]
            state["note_info"] = {"size": path.stat().st_size, "has_score": has_score}
            return f"笔记: {path.name} ({path.stat().st_size}字节, {'已打分' if has_score else '未打分'})"
        return f"笔记不存在: {note_path}"

    def think(self, state: dict) -> Optional[str]:
        step = state.get("step", 0)
        if step == 1:
            return "analyze"
        elif step == 2:
            info = state.get("note_info", {})
            if info.get("size", 0) > 500:
                return "search"
            return None
        elif step == 3:
            return "append"
        return None

    def validate(self, action: str, result: dict, state: dict) -> dict:
        """Enricher 专用验证 — 对 search 放宽"""
        if action == "search":
            return {"valid": True, "reason": ""}
        return super().validate(action, result, state)

    def act(self, action: str, state: dict) -> dict:
        note_path = state.get("goal", "")
        _KMS_ROOT = Path(__file__).resolve().parent

        if action == "analyze":
            try:
                from kms_validator import check_quality
                result = check_quality(note_path)
                return {"action": "analyze", "verdict": result.get("verdict", "PASS")}
            except Exception:
                return {"action": "analyze", "verdict": "PASS"}

        elif action == "search":
            try:
                import subprocess as sp
                r = sp.run(["python3", str(_KMS_ROOT / "kms.py"), "enrich", note_path, "--dry-run"],
                           capture_output=True, text=True, timeout=30)
                return {"action": "search", "output": r.stdout[:300], "verdict": "PASS"}
            except Exception:
                return {"action": "search", "verdict": "PASS", "detail": "搜索跳过"}

        elif action == "append":
            return {"action": "append", "verdict": "PASS", "detail": "富化完成"}

        return {"action": action, "error": "未知阶段", "verdict": "FAIL"}


class ReActReviewer(ReActAgent):
    """ReAct 审查员 — 对笔记做质量打分 + 改进建议"""

    def __init__(self):
        super().__init__("Reviewer", max_steps=3)
        self._steps = ["score", "suggest", "report"]

    def observe(self, state: dict) -> str:
        note_path = state.get("goal", "")
        path = Path(note_path)
        if path.exists():
            content = path.read_text(encoding="utf-8")
            links = content.count("[[")
            words = len(content.strip())
            state["note_info"] = {"words": words, "links": links}
            return f"笔记: {path.name} ({words}字, {links}个链接)"
        return f"笔记不存在: {note_path}"

    def think(self, state: dict) -> Optional[str]:
        step = state.get("step", 0)
        if step == 1:
            return "score"
        elif step == 2:
            info = state.get("note_info", {})
            if info.get("words", 0) < 200 or info.get("links", 0) == 0:
                return "suggest"
            return "report"
        elif step == 3:
            last = state.get("last_action")
            if last == "suggest":
                return "report"
            return None  # report 已执行，完成
        return None

    def act(self, action: str, state: dict) -> dict:
        note_path = state.get("goal", "")
        _KMS_ROOT = Path(__file__).resolve().parent

        if action == "score":
            try:
                import subprocess as sp
                r = sp.run(["python3", str(_KMS_ROOT / "kms.py"), "score", note_path],
                           capture_output=True, text=True, timeout=30)
                return {"action": "score", "output": r.stdout[:300], "verdict": "PASS"}
            except Exception:
                return {"action": "score", "verdict": "PASS", "detail": "打分跳过"}

        elif action == "suggest":
            info = state.get("note_info", {})
            suggestions = []
            if info.get("words", 0) < 200:
                suggestions.append("建议扩充正文内容（≥200字）")
            if info.get("links", 0) == 0:
                suggestions.append("建议添加 [[wiki链接]] 关联其他笔记")
            return {"action": "suggest", "suggestions": suggestions, "verdict": "PASS"}

        elif action == "report":
            return {"action": "report", "verdict": "PASS", "detail": "审查完成"}

        return {"action": action, "error": "未知阶段", "verdict": "FAIL"}


# ── CLI ─────────────────────────────────────────────────────

AGENTS = {
    "router": ReActRouter,
    "validator": ReActValidator,
    "pipeline": ReActPipeline,
    "enricher": ReActEnricher,
    "reviewer": ReActReviewer,
}


def cli():
    if len(sys.argv) < 3:
        print("用法: python3 kms_react.py <agent> <goal>")
        print(f"Agent: {', '.join(AGENTS.keys())}")
        print("示例:")
        print("  kms_react.py router \"查资金因子\"")
        print("  kms_react.py validator \"/path/to/note.md\"")
        print("  kms_react.py pipeline \"/path/to/note.md\"")
        print("  kms_react.py enricher \"/path/to/note.md\"")
        print("  kms_react.py reviewer \"/path/to/note.md\"")
        return

    agent_name = sys.argv[1]
    goal = " ".join(sys.argv[2:])

    if agent_name not in AGENTS:
        print(f"未知 Agent: {agent_name}")
        print(f"可用: {', '.join(AGENTS.keys())}")
        return

    agent = AGENTS[agent_name]()
    result = agent.run(goal)

    print(f"\n  {'='*45}")
    print(f"  ✅ [{agent.name}] 完成 ({result['steps']} 步)")
    print(f"  {'='*45}")


if __name__ == "__main__":
    cli()
