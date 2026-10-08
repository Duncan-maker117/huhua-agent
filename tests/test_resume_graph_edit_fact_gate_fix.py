"""Pure editing commands cannot become new candidate-source fact patches."""

import importlib.util
from pathlib import Path
import sys
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path.cwd() / "backend"))
SPEC = importlib.util.spec_from_file_location("resume_graph_edit_fact_gate_fix", ROOT / "backend/app/agents/resume_graph.py")
assert SPEC and SPEC.loader
graph = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(graph)


class ExistingDraftFactGateTest(TestCase):
    def test_editorial_first_person_or_quoted_claim_is_not_a_new_statement(self):
        for command in ('帮我修改项目描述', '把“我负责整理反馈”这句写短',
                        '突出我整理反馈的部分，保留已有事实。'):
            self.assertFalse(graph._generation_contains_facts(command, editing_existing=True), command)
        self.assertTrue(graph._generation_contains_facts(
            '我还组织了访谈，把它加进项目。', editing_existing=True))
    def test_quoted_existing_action_is_an_edit_not_a_new_fact(self):
        command = "请把项目中‘整理反馈’这句写得更精炼，保留已有事实。"
        self.assertTrue(graph._generation_contains_facts(command))
        self.assertFalse(graph._generation_contains_facts(command, editing_existing=True))

    def test_explicit_new_candidate_fact_still_enters_extractor(self):
        self.assertTrue(graph._generation_contains_facts("我组织了十场访谈，形成结论。", editing_existing=True))
        self.assertTrue(graph._generation_contains_facts("补充项目经历：做了用户访谈。", editing_existing=True))
        self.assertTrue(graph._generation_contains_facts("请补充我整理过访谈笔记。", editing_existing=True))
        self.assertTrue(graph._generation_contains_facts("请先补充整理访谈笔记，再导出。", editing_existing=True))

    def test_document_operation_with_supplement_word_is_not_fact(self):
        self.assertFalse(graph._generation_contains_facts(
            "请补充这段项目的简历表述，合并两条重复 bullet。", editing_existing=True))
