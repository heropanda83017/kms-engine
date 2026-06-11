"""
集成测试: checkpoint_utils.py

覆盖 (14 个测试):
    基础流程:    create_and_read, step_done, resume 系列(3), clear, list_all, idempotent
    新增:        mark_complete, mark_complete异常路径, step_done异常路径,
                output写入验证, metadata验证, 空name验证, clear幂等
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import checkpoint_utils as cp


class TestCheckpointUtils:
    """集成测试: checkpoint_utils 全 API。"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig_dir = cp.CHECKPOINT_DIR
        cp.CHECKPOINT_DIR = Path(self.tmpdir)

    def teardown_method(self):
        cp.CHECKPOINT_DIR = self.orig_dir

    # ── 基础流程 ─────────────────────────────────────

    def test_create_and_read(self):
        state = cp.start("test-pipeline", total_steps=3, steps_plan=[
            {"id": "step1", "name": "第一步"},
            {"id": "step2", "name": "第二步"},
            {"id": "step3", "name": "第三步"},
        ])
        assert state["checkpoint_key"] == "test-pipeline"
        assert state["total_steps"] == 3
        assert state["completed_steps"] == []
        assert state["status"] == "in_progress"

        state2 = cp.get_state("test-pipeline")
        assert state2 is not None
        assert state2["checkpoint_key"] == "test-pipeline"
        assert len(state2["steps_plan"]) == 3

    def test_step_done(self):
        cp.start("test-pipeline", total_steps=3, steps_plan=[
            {"id": "step1", "name": "第一步"},
            {"id": "step2", "name": "第二步"},
            {"id": "step3", "name": "第三步"},
        ])
        cp.step_done("test-pipeline", "step1", {"result": "ok"})
        state = cp.get_state("test-pipeline")
        assert "step1" in state["completed_steps"]
        assert state["step_outputs"]["step1"]["result"] == "ok"

    def test_resume_from_middle(self):
        cp.start("test-pipeline", total_steps=4, steps_plan=[
            {"id": "fetch", "name": "获取数据"},
            {"id": "calc", "name": "计算因子"},
            {"id": "analyze", "name": "分析结果"},
            {"id": "report", "name": "生成报告"},
        ])
        cp.step_done("test-pipeline", "fetch")
        cp.step_done("test-pipeline", "calc")
        idx = cp.resume_from("test-pipeline")
        assert idx == 2

    def test_resume_from_start(self):
        idx = cp.resume_from("nonexistent")
        assert idx == 0

    def test_resume_from_complete(self):
        cp.start("test-pipeline", total_steps=2, steps_plan=[
            {"id": "step1", "name": "第一步"},
            {"id": "step2", "name": "第二步"},
        ])
        cp.step_done("test-pipeline", "step1")
        cp.step_done("test-pipeline", "step2")
        cp.mark_complete("test-pipeline")
        idx = cp.resume_from("test-pipeline")
        assert idx == 2

    def test_clear(self):
        cp.start("test-pipeline", total_steps=1)
        assert cp.get_state("test-pipeline") is not None
        cp.clear("test-pipeline")
        assert cp.get_state("test-pipeline") is None

    def test_list_all(self):
        cp.start("pipe-a", total_steps=1)
        cp.start("pipe-b", total_steps=2)
        all_cp = cp.list_all()
        keys = [c["checkpoint_key"] for c in all_cp]
        assert "pipe-a" in keys
        assert "pipe-b" in keys
        assert len(all_cp) == 2

    def test_idempotent(self):
        cp.start("test-pipeline", total_steps=3)
        for _ in range(3):
            cp.step_done("test-pipeline", "step1")
        state = cp.get_state("test-pipeline")
        assert len(state["completed_steps"]) == 1

    # ── mark_complete 路径 ────────────────────────────

    def test_mark_complete(self):
        """mark_complete 正常路径: 状态变更 + 自动补全。"""
        cp.start("test-pipeline", total_steps=3, steps_plan=[
            {"id": "step1", "name": "第一步"},
            {"id": "step2", "name": "第二步"},
            {"id": "step3", "name": "第三步"},
        ])
        # 只标记 step1
        cp.step_done("test-pipeline", "step1")
        cp.mark_complete("test-pipeline")
        state = cp.get_state("test-pipeline")
        assert state["status"] == "completed"
        # step2, step3 应被自动补全
        assert len(state["completed_steps"]) == 3

    def test_mark_complete_no_checkpoint(self):
        """mark_complete 在不存在 checkpoint 时应抛异常。"""
        try:
            cp.mark_complete("nonexistent")
            assert False, "应抛出 FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_step_done_no_checkpoint(self):
        """step_done 在不存在 checkpoint 时应抛异常。"""
        try:
            cp.step_done("nonexistent", "step1")
            assert False, "应抛出 FileNotFoundError"
        except FileNotFoundError:
            pass

    # ── 参数验证 ─────────────────────────────────────

    def test_metadata(self):
        """start 的 metadata 应正确写入。"""
        cp.start("test-pipeline", total_steps=2, metadata={
            "goal": "test",
            "workflow_id": "wf-001",
        })
        state = cp.get_state("test-pipeline")
        assert state["metadata"]["goal"] == "test"
        assert state["metadata"]["workflow_id"] == "wf-001"

    def test_empty_name(self):
        """空 name 应抛 ValueError。"""
        try:
            cp.start("", total_steps=1)
            assert False, "应抛出 ValueError"
        except ValueError:
            pass
        try:
            cp.start("   ", total_steps=1)
            assert False, "应抛出 ValueError"
        except ValueError:
            pass

    def test_clear_idempotent(self):
        """重复 clear 不抛异常。"""
        cp.start("test-pipeline", total_steps=1)
        cp.clear("test-pipeline")
        cp.clear("test-pipeline")  # 再次 clear

    # ── 边界条件 ─────────────────────────────────────

    def test_resume_from_no_steps_plan(self):
        """没有 steps_plan 的 resume 按 completed 数量推进。"""
        cp.start("test-pipeline", total_steps=3)
        idx = cp.resume_from("test-pipeline")
        assert idx == 0  # 没有 completed
        cp.step_done("test-pipeline", "step_a")
        idx = cp.resume_from("test-pipeline")
        assert idx == 1

    def test_start_idempotent(self):
        """已存在的 checkpoint 不覆盖。"""
        cp.start("test-pipeline", total_steps=3, metadata={"k": "old"})
        cp.start("test-pipeline", total_steps=999, metadata={"k": "new"})
        state = cp.get_state("test-pipeline")
        assert state["total_steps"] == 3  # 不被覆盖
        assert state["metadata"]["k"] == "old"

    # ── 并发安全 ─────────────────────────────────────

    def test_concurrent_flock(self):
        """多线程并发 step_done (同进程, flock验证写入安全)。"""
        import threading

        cp.start("concurrent", total_steps=20, steps_plan=[
            {"id": f"s{i}", "name": f"Step{i}"} for i in range(20)
        ])

        def worker(wid):
            cp.step_done("concurrent", f"s{wid}")

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        state = cp.get_state("concurrent")
        assert len(state["completed_steps"]) == 20, \
            f"并发后应有 20 个 completed, 实际 {len(state['completed_steps'])}"
        cp.clear("concurrent")
