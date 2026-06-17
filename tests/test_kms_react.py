"""
测试: kms_react.py — ReAct Agent 框架

覆盖 (12 个测试):
    ReActAgent 基类:    observe_think_act_cycle, validate_default, validate_fail
    ReActRouter:        intent_search, intent_health, intent_compound, validate_search, fallback_search
    ReActValidator:     intent_quality, validate_quality, dynamic_dimension
    ReActPipeline:      dynamic_phases, validate_link
"""

import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from kms_react import ReActAgent, ReActRouter, ReActValidator, ReActPipeline


# ── ReActAgent 基类测试 ──────────────────────────────────

class TestReActAgent:
    """ReActAgent 基类"""

    def test_observe_think_act_cycle(self):
        """基类必须要求子类实现 observe/think/act"""
        agent = ReActAgent("Test", max_steps=3)
        try:
            agent.observe({})
            assert False, "应抛出 NotImplementedError"
        except NotImplementedError:
            pass

    def test_validate_default(self):
        """默认 validate: 正常结果返回 valid=True"""
        agent = ReActAgent("Test")
        result = validate = agent.validate("test", {"verdict": "PASS", "data": "ok"}, {})
        assert validate["valid"] is True

    def test_validate_fail(self):
        """默认 validate: FAIL verdict 返回 valid=False"""
        agent = ReActAgent("Test")
        validate = agent.validate("test", {"verdict": "FAIL", "detail": "错误"}, {})
        assert validate["valid"] is False
        assert "执行失败" in validate["reason"]

    def test_fallback_default(self):
        """默认 fallback 返回 None"""
        agent = ReActAgent("Test")
        assert agent.fallback("test", {}, {}) is None


# ── ReActRouter 测试 ─────────────────────────────────────

class TestReActRouter:
    """ReActRouter"""

    def setup_method(self):
        self.router = ReActRouter()

    def test_intent_search(self):
        """Router think: 查资金因子 → search"""
        action = self.router.think({"goal": "查资金因子", "step": 1})
        assert action == "search"

    def test_intent_health(self):
        """Router think: 并行健康检查 → health"""
        action = self.router.think({"goal": "并行健康检查", "step": 1})
        assert action == "health"

    def test_intent_compound(self):
        """Router think: 验证笔记并检查健康 → validate(step1) → health(step2)"""
        action1 = self.router.think({"goal": "验证笔记并检查健康", "step": 1})
        assert action1 == "validate"
        action2 = self.router.think({"goal": "验证笔记并检查健康", "step": 2, "last_action": "validate"})
        assert action2 == "health"

    def test_validate_search(self):
        """Router validate: 搜索返回短结果 → invalid"""
        result = {"action": "search", "results": "短"}
        v = self.router.validate("search", result, {})
        assert v["valid"] is False
        assert "过短" in v["reason"]

    def test_validate_search_ok(self):
        """Router validate: 搜索返回正常结果 → valid"""
        result = {"action": "search", "results": "找到 10 处匹配: 资金因子相关内容..."}
        v = self.router.validate("search", result, {})
        assert v["valid"] is True

    def test_fallback_search(self):
        """Router fallback: 搜索失败 → analytics"""
        fb = self.router.fallback("search", {"verdict": "FAIL"}, {})
        assert fb is not None
        assert fb.get("action") == "analytics"


# ── ReActValidator 测试 ──────────────────────────────────

class TestReActValidator:
    """ReActValidator"""

    def setup_method(self):
        self.validator = ReActValidator()

    def test_intent_quality(self):
        """Validator think: step1 → quality"""
        action = self.validator.think({"step": 1})
        assert action == "quality"

    def test_validate_quality(self):
        """Validator validate: quality 无 verdict → invalid"""
        result = {"action": "quality", "data": "some"}
        v = self.validator.validate("quality", result, {})
        assert v["valid"] is False

    def test_validate_quality_ok(self):
        """Validator validate: quality 有 PASS verdict → valid"""
        result = {"action": "quality", "verdict": "PASS"}
        v = self.validator.validate("quality", result, {})
        assert v["valid"] is True

    def test_dynamic_dimension(self):
        """Validator think: 大笔记(>5KB) → fusion, 小笔记 → governance"""
        big = self.validator.think({"step": 2, "file_info": {"size": 10000}})
        assert big == "fusion"
        small = self.validator.think({"step": 2, "file_info": {"size": 1000}})
        assert small == "governance"


# ── ReActPipeline 测试 ───────────────────────────────────

class TestReActPipeline:
    """ReActPipeline"""

    def setup_method(self):
        self.pipeline = ReActPipeline()

    def test_dynamic_phases(self):
        """Pipeline think: 有 frontmatter → guard, 无 → link"""
        has_fm = self.pipeline.think({"step": 3, "note_info": {"has_frontmatter": True}})
        assert has_fm == "guard"
        no_fm = self.pipeline.think({"step": 3, "note_info": {"has_frontmatter": False}})
        assert no_fm == "link"

    def test_validate_link(self):
        """Pipeline validate: link 无更新完成 → invalid"""
        result = {"action": "link", "output": "部分完成"}
        v = self.pipeline.validate("link", result, {})
        assert v["valid"] is False

    def test_validate_link_ok(self):
        """Pipeline validate: link 有更新完成 → valid"""
        result = {"action": "link", "output": "更新完成: 0 个页面"}
        v = self.pipeline.validate("link", result, {})
        assert v["valid"] is True
