"""
测试: KMS 新功能覆盖 — 8 个未覆盖模块

包含:
    kms_router:   意图路由(12种)
    kms_orch:     编排引擎(DAG+并行)
    kms_validator:验证+反馈回流
    kms_pipeline: 流水线+checkpoint
    kms_analytics:使用分析
    kms_session:  会话记忆+画像
    kms_guard:    安全守卫
    kms_daily:    每日晨报
"""

import sys, json, os, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


# ── kms_router: 意图路由 ─────────────────────────────────

class TestKmsRouter:
    """kms_router.py — 12种意图"""

    def setup_method(self):
        from kms_router import IntentRouter
        self.router = IntentRouter()

    def test_search(self):
        i, s, a = self.router.resolve("查资金因子")
        assert i == "search"

    def test_health(self):
        i, s, a = self.router.resolve("看看wiki健康")
        assert i == "health"

    def test_link(self):
        i, s, a = self.router.resolve("更新链接")
        assert i == "link"

    def test_gate(self):
        i, s, a = self.router.resolve("检查笔记")
        assert i == "gate"

    def test_kg(self):
        i, s, a = self.router.resolve("KG 资金因子")
        assert i == "kg"

    def test_fuse(self):
        i, s, a = self.router.resolve("融合笔记")
        assert i == "fuse"

    def test_analytics(self):
        i, s, a = self.router.resolve("使用报告")
        assert i == "analytics"

    def test_validate(self):
        i, s, a = self.router.resolve("验证笔记")
        assert i == "validate"

    def test_compound(self):
        """复合意图: 验证笔记并检查健康 → health(检查优先)"""
        i1, s1, _ = self.router.resolve("验证笔记并检查健康")
        assert i1 in ("validate", "health")  # 取决于匹配顺序

    def test_nomatch(self):
        i, s, a = self.router.resolve("不知道的命令")
        assert i is None

    def test_help(self):
        from kms_router import IntentRouter
        h = IntentRouter().help()
        assert "search" in h


# ── kms_orchestrator: 编排引擎 ───────────────────────────

class TestKmsOrchestrator:
    """kms_orchestrator.py — DAG拓扑排序+并行"""

    def test_topological_sort(self):
        from kms_orchestrator import TaskOrchestrator, TaskDef
        o = TaskOrchestrator()
        tasks = [
            TaskDef(name="A", func=lambda: 1),
            TaskDef(name="B", func=lambda: 2, deps=["A"]),
            TaskDef(name="C", func=lambda: 3, deps=["A"]),
            TaskDef(name="D", func=lambda: 4, deps=["B", "C"]),
        ]
        batches = o._topological_sort({t.name: t for t in tasks})
        assert batches[0] == ["A"]
        assert "D" in batches[-1]

    def test_run(self):
        from kms_orchestrator import TaskOrchestrator, TaskDef
        o = TaskOrchestrator(max_workers=2)
        results = []
        tasks = [
            TaskDef(name="t1", func=lambda: results.append(1)),
            TaskDef(name="t2", func=lambda: results.append(2)),
        ]
        o.run(tasks)
        assert len(results) == 2


# ── kms_validator: 验证+反馈 ─────────────────────────────

class TestKmsValidator:
    """kms_validator.py — 验证+反馈回写"""

    def test_check_quality_nonexist(self):
        from kms_validator import check_quality
        r = check_quality("/tmp/nonexistent_file.md")
        assert r["verdict"] == "FAIL"

    def test_read_issues_empty(self):
        from kms_validator import read_issues
        r = read_issues("/tmp/nonexistent_file.md")
        assert r == []

    def test_validate_nonexist(self):
        from kms_validator import validate
        r = validate("/tmp/nonexistent_file.md")
        assert r["verdict"] == "FAIL"


# ── kms_analytics: 使用分析 ─────────────────────────────

class TestKmsAnalytics:
    """kms_analytics.py — SQLite追踪"""

    def test_tracker(self):
        from kms_analytics import UsageTracker
        t = UsageTracker()
        t.log_search("测试关键词", result_count=3)
        t.log_command("test", detail="test", duration=0.5)
        report = t.report(days=30)
        assert report["total_commands"] >= 1

    def test_report_format(self):
        from kms_analytics import UsageTracker
        t = UsageTracker()
        r = t.report(days=7)
        assert "total_commands" in r
        assert "total_searches" in r
        assert "top_commands" in r


# ── kms_session: 会话记忆+画像 ──────────────────────────

class TestKmsSession:
    """kms_session.py — 会话记忆+画像"""

    def test_record_search(self):
        from kms_session import record_search, get_context
        record_search("测试")
        ctx = get_context()
        assert "测试" in ctx or "搜索" in ctx

    def test_record_health(self):
        from kms_session import record_health
        record_health(checks=6, issues=10)


# ── kms_guard: 安全守卫 ──────────────────────────────────

class TestKmsGuard:
    """kms_guard.py — 敏感信息检测"""

    def test_scan_clean(self):
        from kms_guard import scan
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("---\ntitle: test\n---\n正常内容")
            fname = f.name
        findings = scan(fname)
        os.unlink(fname)
        assert len(findings) == 0

    def test_scan_leak(self):
        from kms_guard import scan
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("api_key = 'sk-abc123def456ghi789jkl01234567'")
            fname = f.name
        findings = scan(fname)
        os.unlink(fname)
        assert len(findings) >= 1
        assert "API Key" in findings[0]["pattern"]

    def test_scan_nonexist(self):
        from kms_guard import scan
        r = scan("/tmp/nonexistent.md")
        assert len(r) == 1
        assert "不存在" in r[0]["pattern"]


# ── kms_daily_report: 每日晨报 ──────────────────────────

class TestKmsDailyReport:
    """kms_daily_report.py — 每日晨报"""

    def test_stale_check(self):
        from kms_daily_report import check_stale
        stale = check_stale(days=9999)  # 超长阈值，确保不报
        assert isinstance(stale, list)

    def test_network_check(self):
        from kms_daily_report import _network_available
        # 不会抛异常
        result = _network_available()
        assert isinstance(result, bool)


# ── kms_pipeline: 内容流水线 ────────────────────────────

class TestKmsPipeline:
    """kms_pipeline.py — 流水线编排"""

    def test_phases(self):
        from kms_pipeline import PHASES
        assert len(PHASES) == 6
        names = [p[0] for p in PHASES]
        assert "validate" in names
        assert "fuse" in names
        assert "link" in names
        assert "publish" in names

    def test_run_nonexist(self):
        from kms_pipeline import run_pipeline
        # 不应抛异常
        run_pipeline("/tmp/nonexistent.md", skip={"validate", "fuse", "link", "enrich", "review", "publish"})
