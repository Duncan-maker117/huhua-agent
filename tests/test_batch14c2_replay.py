"""Frozen real-round shapes with local extractor, writer and HTTP client doubles."""
from copy import deepcopy
from importlib import import_module
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]
from app.agents.fact_extractor import apply_fact_patch, extract_facts_patch  # noqa: E402
from app.agents.resume_writer import run_resume_writer  # noqa: E402
from app.agents.resume_graph import _writer_reply  # noqa: E402
from app.services.candidate_material import split_mixed_material  # noqa: E402
from app.agents.tailor_pipeline import constraints_for_turn  # noqa: E402
from app.services.experience_subjects import explicit_subject_spans  # noqa: E402
from app.services.fact_corrections import apply_literal_corrections, correction_pairs  # noqa: E402
from app.services.resume_versions import text_hash  # noqa: E402
from test_campus_and_naming import ExtractorStub, semantic_stub  # noqa: E402
from test_persona_regressions import fixture_patch  # noqa: E402
from test_resume_writer import FakeModel, fact  # noqa: E402

AIPM = import_module('evaluation.persona-ux.aipm')
SNAPSHOT = json.loads((ROOT / 'tests/fixtures/batch14c2-replay.json').read_text())


class ReplayWriter:
    def __init__(self, labeled=False, reject_one=False):
        self.labeled, self.reject_one = labeled, reject_one
        self.inputs = []

    def with_structured_output(self, schema):
        async def invoke(messages):
            payload = json.loads(messages[-1].content)
            if schema.__name__ == 'RepairOutput':
                return {'bullets': []}
            if schema.__name__ != 'WriterDraft':
                raise AssertionError(schema.__name__)
            self.inputs.append(payload)
            items = []
            for section in ('work_experience', 'projects'):
                for item in payload['evidence'].get(section, []):
                    if section == 'work_experience':
                        rows = [
                            ('在 4 人团队中使用 Spring Boot 和 MySQL，负责订单查询接口与参数校验。', ['团队', '订单查询', 'Spring Boot']),
                            ('在导师指导下为订单列表添加 Redis 缓存；测试环境为慢查询加联合索引，平均耗时由约 420ms 降至约 170ms，没做线上压测。', ['导师', '测试环境', '420', '线上压测']),
                            ('编写 12 条接口测试用例，与前端同学联调。' + ('主导全系统架构。' if self.reject_one else ''), ['12', '联调']),
                        ]
                    else:
                        rows = [('3 人课程小组负责商品发布和搜索接口，使用 Spring Boot、MySQL；登录模块由另一位同学编写。', ['3 人', '商品发布', '登录']),
                                ('部署在实验室服务器，只给班里演示。', ['实验室'])]
                    bullets = []
                    headers = [f['id'] for f in item['facts'] if f.get('field')]
                    for text, needles in rows:
                        refs = [f['id'] for f in item['facts'] if any(n in f['text'] for n in needles)]
                        bullets.append({'text': ('设计：' if self.labeled else '') + text,
                                        'fact_ids': list(dict.fromkeys(refs + headers))})
                    # Date-only rows and project title objects exercise the 14c boundaries.
                    bullets.append({'text': '2025.07—2025.09', 'fact_ids': headers})
                    items.append({'item_id': item['item_id'], 'section': section, 'bullets': bullets,
                                  'title': {'positioning': '接口开发实践', 'fact_ids': headers}})
            return {'items': items}
        return SimpleNamespace(ainvoke=invoke)


class Batch14c2TechTests(unittest.IsolatedAsyncioTestCase):
    async def source(self, missing_work=True):
        candidate = fixture_patch('tech')
        if missing_work:
            candidate['items'] = [i for i in candidate['items'] if i['section'] != 'internship']
        text, _ = split_mixed_material(SNAPSHOT['tech']['input'])
        result = await extract_facts_patch(text, {}, ExtractorStub(candidate))
        return apply_fact_patch({}, result)

    async def test_real_input_missing_extractor_item_reaches_writer_and_correction(self):
        self.enterContext(patch('app.services.fact_guard.verify_semantics', semantic_stub))
        source = await self.source()
        works = source.get('internship', []) + source.get('work_experience', [])
        self.assertEqual(len(works), 1)
        work = works[0]
        self.assertEqual(work['company'], '云舟科技')
        facts = ' '.join(f['text'] for f in work['facts'])
        for required in ('导师', '测试环境', '420', '170', '12', '4 人', '线上压测', '联调'):
            self.assertIn(required, facts)
        self.assertNotIn('商品发布', facts)
        # The captured plan already lost the work ID. Restore the explicitly
        # requested lead/keep intent, binding it to this extraction's real IDs.
        plan = deepcopy(SNAPSHOT['tech']['plan'])
        plan.update(requirements=[], questions=[], experience_plan=[
            {'item_id': work['item_id'], 'treatment': 'lead', 'target_bullets': 3},
            *[{'item_id': p['item_id'], 'treatment': 'keep', 'target_bullets': 2} for p in source['projects']]])
        for labeled, reject_one in ((False, False), (True, False), (True, True)):
            with self.subTest(labeled=labeled, reject_one=reject_one):
                model = ReplayWriter(labeled, reject_one)
                result = await run_resume_writer(source, {'role_family': 'engineering'}, model,
                    phase='write', previous_plan=plan, instruction=SNAPSHOT['tech']['input'],
                    constraints=constraints_for_turn({}, SNAPSHOT['tech']['input']))
                self.assertTrue(model.inputs)
                data = result['resume_data']
                actual = data['work_experience'][0]
                self.assertFalse(actual.get('hidden'))
                self.assertEqual((actual['start_date'], actual['end_date']), ('2025.07', '2025.09'))
                body = '\n'.join(actual['bullets'])
                for word in ('导师', '测试环境', '线上压测', '420', '170', '12', '4'):
                    self.assertIn(word, body)
                self.assertNotIn('主导全系统', body)
                self.assertNotIn('2025', body)
                if reject_one:
                    self.assertTrue(result['guard_fallbacks'])
                instruction = '优化后约 190ms，不是 170ms。其他数字保持不变。'
                corrected = apply_literal_corrections(source, data, result['resume_meta'], correction_pairs(instruction))
                self.assertNotIn('error', corrected)
                changed = str(corrected['resume_data']['work_experience'])
                self.assertIn('190', changed)
                self.assertNotIn('170ms', changed)
                for value in ('420', '12', '4'):
                    self.assertIn(value, changed)

    def test_literal_identity_does_not_accept_plans_third_party_or_cross_sentence(self):
        for text in ('希望在云舟科技做后端开发实习生，负责订单查询。',
                     '朋友在云舟科技做后端开发实习生，负责订单查询。',
                     '我没在云舟科技做后端开发实习生。'):
            self.assertEqual(explicit_subject_spans(text), [])
        text = '在云舟科技做后端开发实习生，负责订单查询。课程项目叫交易系统，我负责商品接口。'
        self.assertEqual(len(explicit_subject_spans(text)), 1)
        self.assertNotIn('课程项目', text[:explicit_subject_spans(text)[0]['end']])
        text = '在云舟科技做后端开发实习生，负责订单；在星海科技做开发实习生，负责商品；课程项目叫交易系统。'
        spans = explicit_subject_spans(text)
        self.assertEqual([span['name'] for span in spans], ['云舟科技', '星海科技'])
        self.assertNotIn('星海', text[spans[0]['start']:spans[0]['end']])
        self.assertNotIn('课程项目', text[spans[1]['start']:spans[1]['end']])

    async def test_selected_item_without_supported_body_is_explicit_delivery_failure(self):
        source = {'work_experience': [{'item_id': 'work', 'company': '云舟科技',
                  'facts': [{**fact('date', '2025.07'), 'field': 'start_date'}]}]}
        plan = {'experience_plan': [{'item_id': 'work', 'treatment': 'lead', 'target_bullets': 3}]}
        model = FakeModel([('WriterDraft', {'items': [{'item_id': 'work', 'section': 'work_experience',
                              'bullets': [{'text': '2025.07', 'fact_ids': ['date']}]}]})])
        result = await run_resume_writer(source, {}, model, phase='write', previous_plan=plan)
        self.assertEqual(result['writer_diagnostic']['undelivered_items'], ['work'])
        self.assertIn('云舟科技', str(result['resume_data']['verification_notes']))
        self.assertIn('未能形成通过事实校验的正文', _writer_reply({**result, 'changed': True}))


def good_final():
    turn = deepcopy(SNAPSHOT['aipm'][-1])
    p = turn['resume_data']['projects'][0]
    p['polished_bullets'] = ['问题：通过对话帮助学生梳理经历并撰写简历。',
        '决策：比较提示词与方案；以 71 条断言检查成稿，回放五个虚拟求职者对话。',
        '迭代：更换模型或调参；通过链接可在公网访问。']
    turn['workspace']['guidance'] = {}
    turn['workspace']['tailor']['resume_meta']['bullets'][p['item_id']] = [
        {'fact_ids': ['synthetic-fact'], 'text_hash': text_hash(b)} for b in p['polished_bullets']]
    return turn


class Batch14c2AipmTests(unittest.TestCase):
    def test_real_preview_prefix_fails_all_body_checks_even_with_stage_and_revision(self):
        turns = deepcopy(SNAPSHOT['aipm'][:4])
        for stage in ('BUILDING', 'EVALUATING'):
            turns[-1]['stage'] = stage
            checks = {c['id']: c for c in AIPM.evaluate_persona('aipm', turns)}
            for key in ('common.rounds_complete', 'heading', 'labels', 'answers_used', 'rewritten', 'no_invented_metrics'):
                self.assertEqual(checks['aipm.' + key]['status'], 'fail')

    def test_complete_real_artifact_did_write_but_still_fails_quality(self):
        self.assertTrue(AIPM.delivered(SNAPSHOT['aipm'][-1]))
        checks = {c['id']: c for c in AIPM.evaluate_persona('aipm', SNAPSHOT['aipm'])}
        self.assertEqual(checks['aipm.common.rounds_complete']['status'], 'pass')
        self.assertEqual(checks['aipm.labels']['status'], 'fail')  # 迭代：评测： nested label

    def test_stale_writer_metadata_or_plan_alone_cannot_certify_preview(self):
        turn = good_final()
        turn['resume_data']['projects'][0]['polished_bullets'][0] = '收集期用户原话'
        self.assertFalse(AIPM.delivered(turn))
        turn = good_final()
        turn['workspace']['tailor']['resume_meta'].pop('bullets')
        self.assertFalse(AIPM.delivered(turn))
        turn = good_final()
        turn['stage'] = 'BUILDING'
        self.assertFalse(AIPM.delivered(turn))

    def test_question_numbers_and_unknown_answers_do_not_license_metrics(self):
        previous = deepcopy(SNAPSHOT['aipm'][1])
        guidance = previous['workspace']['guidance']
        guidance['questions'] = [{'id':'eval', 'prompt':'有1000个样例吗？', 'kind':'text'}]
        turn = good_final()
        turn.update(input='有1000个样例吗：不知道', answers={'turn_id':guidance['turn_id'],
            'items':[{'id':'eval', 'value':'1000个样例', 'unknown':True}]})
        project = turn['resume_data']['projects'][0]
        project['polished_bullets'][0] = '问题：用1000个样例检查事实。'
        turn['workspace']['tailor']['resume_meta']['bullets'][project['item_id']][0]['text_hash'] = text_hash(project['polished_bullets'][0])
        checks = {c['id']:c['status'] for c in AIPM.evaluate_persona('aipm', [previous, turn])}
        self.assertEqual(checks['aipm.common.rounds_complete'], 'pass')
        self.assertEqual(checks['aipm.no_invented_metrics'], 'fail')

    def test_real_rounds_stub_follows_links_and_plan_until_writer(self):
        requests = []
        responses = deepcopy(SNAPSHOT['aipm'])
        responses[-1] = good_final()
        class Client:
            def turn(self, action, text, **payload):
                result = responses[len(requests)]
                requests.append(payload)
                return {**result, 'action': action, 'input': text, **payload}
        turns = list(AIPM.replay(Client()))
        self.assertEqual(len(turns), 5)
        link = requests[2]['answers']['items'][-1]
        self.assertEqual(link['value'], '公网可访问的链接')
        self.assertFalse(link['unknown'])
        self.assertEqual(turns[-1]['input'], '按推荐写')
        self.assertTrue(all(c['status'] == 'pass' for c in AIPM.evaluate_persona('aipm', turns)))

    def test_keeps_answering_after_confirmation_if_writer_not_yet_delivered(self):
        responses = deepcopy(SNAPSHOT['aipm'])
        responses[-1]['workspace']['tailor']['resume_meta'] = {}
        responses.extend([deepcopy(SNAPSHOT['aipm'][3]), good_final()])
        requests = []
        class Client:
            def turn(self, action, text, **payload):
                result = responses[len(requests)]
                requests.append(payload)
                return {**result, 'action':action, 'input':text, **payload}
        turns = list(AIPM.replay(Client()))
        self.assertEqual(len(turns), 7)
        self.assertIn('answers', requests[5])
        self.assertTrue(AIPM.delivered(turns[-1]))
        self.assertFalse(any(t.get('depth_limit_exceeded') for t in turns))

    def test_depth_limit_is_separate_failure_even_if_direct_write_delivers(self):
        requests = []
        class Client:
            def turn(self, action, text, **payload):
                requests.append(text)
                if text == '直接写':
                    return {**good_final(), 'input':text, 'action':action}
                turn = deepcopy(SNAPSHOT['aipm'][1])
                turn.update(input=text, action=action, **payload)
                return turn
        turns = list(AIPM.replay(Client()))
        self.assertEqual(len(turns), AIPM.MAX_ROUNDS + 2)
        self.assertEqual(requests[-1], '直接写')
        checks = {c['id']: c['status'] for c in AIPM.evaluate_persona('aipm', turns)}
        self.assertEqual(checks['aipm.common.rounds_complete'], 'pass')
        self.assertEqual(checks['aipm.depth_within_limit'], 'fail')

    def test_answers_use_actual_non_unknown_submissions_and_need_all_when_under_three(self):
        previous = deepcopy(SNAPSHOT['aipm'][1])
        guidance = previous['workspace']['guidance']
        turn = good_final()
        turn['answers'] = {'turn_id':guidance['turn_id'], 'items':[
            {'id':'badcase', 'value':'换模型或调参数'}, {'id':'links', 'value':'公网可访问的链接'},
            {'id':'eval', 'value':'这个不会算进去', 'unknown':True}]}
        self.assertEqual(len(AIPM.submitted_values([previous, turn])), 2)
        self.assertEqual(next(c for c in AIPM.evaluate_persona('aipm', [previous, turn]) if c['id'].endswith('answers_used'))['status'], 'pass')
        turn['answers']['items'][1]['value'] = '从未提供过的事实'
        self.assertEqual(next(c for c in AIPM.evaluate_persona('aipm', [previous, turn]) if c['id'].endswith('answers_used'))['status'], 'fail')

    def test_answer_bank_dimensions_options_other_and_unknown(self):
        prompts = {'tech_stack':'技术栈是什么？', 'decision':'关键决策是什么？', 'badcase':'效果不好怎么改？',
                   'eval':'如何评估？', 'status':'现状？', 'links':'现在能访问吗？有链接或仓库吗？',
                   'problem':'解决谁的什么问题？', 'my_work':'你负责什么？', 'revenue':'付费收入多少？'}
        for identifier, prompt in prompts.items():
            q = {'id':identifier, 'prompt':prompt, 'kind':'text'}
            answer = AIPM._answer(q)
            self.assertEqual(answer['unknown'], identifier == 'revenue', identifier)
        q = {'id':'iteration', 'prompt':'怎么改？', 'kind':'single',
             'options':['没有改过', '更换模型或调整参数'], 'allow_other':True}
        self.assertEqual(AIPM._answer(q)['value'], q['options'][1])
        q['options'] = ['没有改过', '只改界面']
        self.assertEqual(AIPM._answer(q)['value'], '换模型或调参数')


if __name__ == '__main__':
    unittest.main()
