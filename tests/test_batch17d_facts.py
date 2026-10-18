"""Offline upload regression; model patches are synthetic, not captured responses."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.agents import fact_extractor, orchestrator_tools as tools, resume_graph as graph  # noqa: E402
from app.agents.triage_chain import TriageAction, TriageDecision  # noqa: E402
from app.services.candidate_language import experience_constraint, literal_item_name, safe_item_name  # noqa: E402
from app.services.candidate_material import parse_existing_resume  # noqa: E402
from app.services.experience_subjects import subject_span  # noqa: E402
from app.services.resume_facts import active_facts_for_writer  # noqa: E402


UPLOAD = (ROOT / 'tests/fixtures/batch17d_upload.txt').read_text().strip()
PROJECT = '预约系统课程测试'
ROLE = '小组测试成员'
DUTIES = ['按老师给的需求', '用 Python 编写16条测试用例', '在本地环境执行', '记录5个问题并提交问题清单']
LIMITS = ['同学负责系统开发', '我没有上线部署', '没有做生产压测', '不是项目负责人']


def fact(text, kind='action', **values):
    return {'kind': kind, 'text': text, 'source_quote': text, **values}


def model_patch(*, split=False, sparse=False):
    rows = [{'section': 'projects', 'name': PROJECT,
             'facts': [fact(DUTIES[1])]}]
    if not sparse:
        details = [fact(ROLE, 'role', field='role'), *[fact(text) for text in DUTIES if text != DUTIES[1]],
                   *[fact(text, 'status_limit') for text in LIMITS]]
        if split:
            rows.append({'section': 'projects', 'name': '不是', 'facts': details})
        else:
            rows[0]['facts'].extend(details)
    return {'items': rows}


class Extractor:
    def __init__(self, response):
        self.response, self.requests = response, []

    async def ainvoke(self, messages):
        self.requests.append(deepcopy(messages))
        return AIMessage(content=json.dumps(self.response, ensure_ascii=False))


class Batch17dFactsTests(unittest.IsolatedAsyncioTestCase):
    def assert_project(self, collected):
        self.assertEqual(len(collected['projects']), 1, [row['name'] for row in collected['projects']])
        item = collected['projects'][0]
        self.assertEqual(item['name'], PROJECT)
        self.assertEqual((item['start_date'], item['end_date']), ('2026.03', '2026.05'))
        facts = [f for f in item['facts'] if f['status'] == 'active']
        self.assertEqual([f['text'] for f in facts if f.get('field') == 'role'], [ROLE])
        text = '\n'.join(f['text'] for f in facts)
        for quote in DUTIES + LIMITS:
            self.assertIn(quote.removeprefix('我'), text)
            self.assertTrue(any(quote in f['source_quote'] for f in facts), quote)
        for quote in LIMITS:
            self.assertTrue(any(quote in f['source_quote'] and f['kind'] == 'status_limit'
                                and not f.get('field') for f in facts), quote)
        writer = active_facts_for_writer(collected)['projects']
        self.assertEqual(len(writer), 1)
        self.assertEqual({f['id'] for f in writer[0]['facts']}, {f['id'] for f in facts})

    def assert_private(self, requests):
        self.assertTrue(requests)
        for messages in requests:
            content = '\n'.join(m.content for m in messages)
            self.assertNotIn('13900002018', content)
            self.assertNotIn('upload.person@example.invalid', content)
            for message in messages:
                if message.type == 'system':
                    self.assertNotIn(PROJECT, message.content)
                    self.assertNotIn('叶清', message.content)

    async def test_extractor_preserves_single_project_with_correct_split_and_sparse_patches(self):
        self.assertIsNone(parse_existing_resume(UPLOAD))  # Exercise extraction, not the import parser.
        for response in (model_patch(), model_patch(split=True), model_patch(sparse=True), {}):
            with self.subTest(response=response):
                model = Extractor(response)
                result = await fact_extractor.extract_facts_patch(UPLOAD, {}, model, turn_id='upload')
                self.assert_project(fact_extractor.apply_fact_patch({}, result))
                self.assertEqual(result['uncovered'], [])
                self.assert_private(model.requests)

    async def test_collecting_and_record_facts_preserve_the_same_project_and_limits(self):
        for route in ('collecting', 'record_facts'):
            with self.subTest(route=route):
                model = Extractor(model_patch(split=True))
                state = {**graph._init_state(), 'stage': 'COLLECTING',
                         'candidate_history_reconciled': True,
                         'messages': [HumanMessage(content=UPLOAD, id='upload')]}
                saved = AsyncMock()
                token = graph._intake_saver.set(saved)
                try:
                    if route == 'collecting':
                        decision = TriageDecision(action=TriageAction.ASK_EXPERIENCE, reason='offline')
                        with patch.object(graph, 'run_triage', AsyncMock(return_value=decision)), \
                             patch.object(graph, '_make_non_streaming_llm', return_value=model), \
                             patch.object(graph, 'enrich_direction', AsyncMock(return_value={})), \
                             patch.object(graph, '_collection_reply', AsyncMock(return_value=AIMessage(content='已记录。'))):
                            update = await graph.collecting_node(state, model)
                    else:
                        outcome = await tools.record_facts(state, {'source_id': 'current'}, tools.ToolContext(llm=model))
                        self.assertEqual(outcome.result['status'], 'ok')
                        self.assertNotIn('13900002018', json.dumps(outcome.result))
                        self.assertNotIn('upload.person@example.invalid', json.dumps(outcome.result))
                        update = outcome.update
                finally:
                    graph._intake_saver.reset(token)
                self.assert_project(update['collected_info'])
                self.assert_project(saved.await_args.args[0]['collected_info'])
                self.assert_private(model.requests)

    def test_scope_and_negative_phrases_are_never_literal_experience_names(self):
        self.assertEqual(literal_item_name('同学负责系统开发\n不是项目负责人', 'projects'), '')
        for name in ('不是', '不是项目负责人', '并非负责人', '非负责人', '没有上线部署', '未上线',
                     '尚未部署', '同学负责系统开发', '开发由队友负责', '范围：未参与部署'):
            with self.subTest(name=name):
                self.assertFalse(safe_item_name(name))
                self.assertEqual(literal_item_name(f'项目名称：{name}', 'projects'), '')
        for name in ('未来预约系统', '无人机航线工具', '未央校园助手', '非遗资料库'):
            self.assertTrue(safe_item_name(name), name)

    def test_intake_constraint_does_not_absorb_candidate_work_near_a_teammate(self):
        for text in ('同学负责开发', '数据接口由队友负责', '未参加部署', '没有做生产压测'):
            self.assertTrue(experience_constraint(text), text)
        for text in ('按同学负责的接口编写7条测试', '我检查同学负责的页面',
                     '同学负责开发而我执行测试', '没有参与部署但编写了测试用例'):
            self.assertFalse(experience_constraint(text), text)

    def test_labelled_details_stop_at_next_subject_or_unlabelled_prose(self):
        text = ('项目：表单核对工具。\n角色：测试成员。\n具体工作：编写7条用例。\n范围：没有上线。\n'
                '项目：报表校验工具。\n角色：开发成员。\n具体工作：校验3类报表。\n'
                '技能：Python 基础。\n范围：未参加比赛。\n我还有一段实习。\n角色：运营成员。')
        for quote, name in (('编写7条用例', '表单核对工具'), ('没有上线', '表单核对工具'),
                            ('校验3类报表', '报表校验工具')):
            self.assertEqual(subject_span(quote, text)['name'], name)
        for quote in ('Python 基础', '未参加比赛', '运营成员'):
            self.assertIsNone(subject_span(quote, text))

    async def test_two_labelled_projects_keep_duties_and_limits_separate(self):
        text = ('项目：表单核对工具。\n角色：测试成员。\n具体工作：编写7条用例。\n范围：同学负责开发，未上线。\n'
                '项目：报表校验工具。\n角色：开发成员。\n具体工作：校验3类报表。\n范围：并非负责人。')
        result = await fact_extractor.extract_facts_patch(text, {}, Extractor({}))
        rows = fact_extractor.apply_fact_patch({}, result)['projects']
        self.assertEqual(len(rows), 2)
        by_name = {row['name']: row for row in rows}
        first, second = by_name['表单核对工具'], by_name['报表校验工具']
        self.assertEqual([f['text'] for f in first['facts'] if f.get('field') == 'role'], ['测试成员'])
        self.assertEqual([f['text'] for f in second['facts'] if f.get('field') == 'role'], ['开发成员'])
        self.assertIn('7条用例', str(first['facts']))
        self.assertNotIn('3类报表', str(first))
        self.assertIn('3类报表', str(second['facts']))
        self.assertNotIn('未上线', str(second))


if __name__ == '__main__':
    unittest.main()
