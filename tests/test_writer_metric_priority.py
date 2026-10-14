"""量化成果事实在 lead/keep 条目里优先保留；全部使用虚构数据与本地替身模型。"""

import asyncio
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from app.agents.resume_writer import run_resume_writer  # noqa: E402
from test_resume_writer import FakeModel, ROLE, draft, fact, item, plan  # noqa: E402

METRIC = "开源项目获得 128 个虚构星标"
PROMO = "在虚构社区发帖推广该项目"


def source(kind="result_metric"):
    return {
        "projects": [{"item_id": "p1", "name": "虚构开源工具", "facts": [
            fact("a1", "实现命令行解析模块"),
            fact("a2", "编写自动化测试覆盖主要流程和边界情况"),
            fact("a3", "设计插件加载机制"),
            fact("m1", METRIC, kind=kind),
            fact("a4", PROMO),
        ]}],
        "work_experience": [], "skills": [],
    }


def plan_for(treatment):
    return plan({"p1": treatment})


def bullets_of(result):
    return result["resume_data"]["projects"][0]["polished_bullets"]


def run(model, treatment="keep", **kwargs):
    return asyncio.run(run_resume_writer(source(**kwargs), ROLE, model))


def first_pass(treatment, rows):
    return ("OnePassOutput", {"match_plan": {**plan_for(treatment), "experience_plan": [
        {"item_id": "p1", "treatment": treatment, "target_bullets": 3}]},
        "writer": draft([item("p1", "projects", rows)])})


class MetricPriorityTest(unittest.TestCase):
    def test_model_repair_with_checklist_cites_metric(self):
        model = FakeModel([
            first_pass("keep", [("实现命令行解析模块", ["a1"]), ("编写自动化测试覆盖主要流程", ["a2"])]),
            ("WriterDraft", draft([item("p1", "projects", [
                ("实现命令行解析模块", ["a1"]), (METRIC, ["m1"])])])),
        ])
        result = run(model)
        self.assertEqual(bullets_of(result), ["实现命令行解析模块", METRIC])
        self.assertEqual([name for name, _ in model.calls], ["OnePassOutput", "WriterDraft", "RepairOutput"])
        self.assertIn("m1", model.calls[1][1][-1].content)  # 修复调用带缺失清单

    def test_still_missing_after_repair_prioritizes_numbers_at_capacity(self):
        model = FakeModel([
            first_pass("keep", [("实现命令行解析模块", ["a1"]), ("编写自动化测试覆盖主要流程和边界情况", ["a2"])]),
            ("WriterDraft", draft([item("p1", "projects", [
                ("实现命令行解析模块", ["a1"]), ("编写自动化测试覆盖主要流程和边界情况", ["a2"])])])),
        ])
        result = run(model)
        bullets = bullets_of(result)
        self.assertEqual(len(bullets), 2)  # keep 上限 2
        self.assertIn(METRIC, ' '.join(bullets))
        self.assertIn("编写自动化测试覆盖主要流程和边界情况", bullets)  # 更长（信息量更大）的保留
        self.assertNotIn("实现命令行解析模块", bullets)
        meta = result["resume_meta"]["bullets"]["p1"]
        self.assertEqual(meta[-1]['fact_ids'], ['m1'])

    def test_appends_when_under_limit_and_repair_call_fails(self):
        model = FakeModel([
            first_pass("lead", [("实现命令行解析模块", ["a1"]), ("设计插件加载机制", ["a3"])]),
            ("WriterDraft", RuntimeError("upstream down")),
        ])
        result = run(model)
        self.assertEqual(bullets_of(result), ["实现命令行解析模块", "设计插件加载机制", METRIC])
        self.assertTrue(result["resume_meta"]["bullets"]["p1"][-1]["text_hash"])

    def test_already_cited_metric_only_needs_source_echo_polish(self):
        model = FakeModel([first_pass("keep", [(METRIC, ["m1"]), ("实现命令行解析模块", ["a1"])])])
        result = run(model)
        self.assertEqual(bullets_of(result), [METRIC, "实现命令行解析模块"])
        self.assertEqual(len(model.calls), 2)

    def test_brief_item_is_not_forced(self):
        model = FakeModel([first_pass("brief", [("实现命令行解析模块", ["a1"])])])
        result = run(model)
        self.assertNotIn(METRIC, bullets_of(result))
        self.assertEqual(len(model.calls), 2)

    def test_number_in_non_metric_kind_is_still_prioritized(self):
        model = FakeModel([first_pass("keep", [("实现命令行解析模块", ["a1"])])])
        result = run(model, kind="result_qualitative")
        self.assertIn(METRIC, bullets_of(result))
        self.assertIn('WriterDraft', [name for name, _ in model.calls])


if __name__ == "__main__":
    unittest.main()
