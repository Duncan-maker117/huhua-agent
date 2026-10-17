"""c3 failures: frozen inputs/state, adverse model doubles, no real providers."""
import asyncio
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
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from app.agents import resume_graph as graph  # noqa: E402
from app.agents.resume_writer import run_resume_writer  # noqa: E402
from app.agents.triage_chain import TriageAction, TriageDecision  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.services.fact_corrections import apply_literal_corrections, correction_pairs  # noqa: E402
from app.services.intake import intake_update, intake_guidance, deepen_context  # noqa: E402
from app.services.profile_bridge import sanitize_fact_history  # noqa: E402
from app.services.resume_limits import preserve_item_limits  # noqa: E402
from app.services.resume_versions import text_hash  # noqa: E402
from app.services.resume_workspace import build_workspace  # noqa: E402
from app.services.role_profile import infer_role_family  # noqa: E402
from app.services.writing_style import format_rows  # noqa: E402
from test_batch14c3_real import RealModel, extract_real_stub, REAL  # noqa: E402
from test_batch14b_intake import PAGES  # noqa: E402
from test_campus_and_naming import semantic_stub  # noqa: E402
from test_resume_writer import fact  # noqa: E402
from test_writer_contract import SOURCE, PLAN  # noqa: E402
from test_persona_regressions import PersonaModel  # noqa: E402

FIXTURE = json.loads((ROOT / 'tests/fixtures/batch14c4-replay.json').read_text())
AIPM = import_module('evaluation.persona-ux.aipm')
CHECKS = import_module('evaluation.persona-ux.checks')


def record(action, text, data, reply):
    return {'action': action, 'input': text, 'resume_data': deepcopy(data), 'reply': reply,
            'status': 'ok', 'sse_done': True}


def save_evidence(name, value):
    directory = Path('/private/tmp/huhua-b14c4')
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(value, ensure_ascii=False, indent=2))


def tech_state():
    """Reconstruct only evidenced fields; raw extractor output was not logged."""
    snapshot = deepcopy(FIXTURE['tech_before_correction'])
    collected = {}
    for section in ('work_experience', 'projects'):
        collected[section] = []
        for item in snapshot['resume_data'].get(section, []):
            rows = []
            for entry in snapshot['resume_meta']['fact_coverage']['facts']:
                if entry['item_id'] != item['item_id']:
                    continue
                text = entry['text']
                f = fact(entry['fact_id'], text, kind='result_metric' if '420' in text else 'action')
                # Same original metric sentence as the supplied first input;
                # the fact.text is the shorter quantified extraction.
                if '420' in text:
                    f['source_quote'] = '在测试环境对一个慢查询加了联合索引，平均耗时由约 420ms 降到约 170ms，没做线上压测'
                rows.append(f)
            collected[section].append({**{k: v for k, v in item.items() if k not in {'bullets', 'polished_bullets', 'description'}}, 'facts': rows})
    return {**snapshot, 'collected_info': collected, 'stage': 'EVALUATING', 'intake_stage': 'ready',
            'messages': [HumanMessage(content=FIXTURE['tech_inputs'][2])]}


class Batch14c4DirectionTests(unittest.TestCase):
    def test_colloquial_ai_roles_are_deterministic_and_use_ai_pm(self):
        for text in (FIXTURE['aipm_real_inputs'][1], '做AI产品', 'AI 产品经理',
                     '想投 aI  产品 相关工作', '想做ai产品', 'AI\t产品'):
            with self.subTest(text=text):
                self.assertTrue(graph._looks_like_role_direction(text))
                self.assertEqual(graph._direction_profile_update({}, text)['jd_info']['role_profile']['role_family'], 'ai_pm')
        self.assertTrue(graph._looks_like_role_direction('想投产品'))
        self.assertEqual(infer_role_family('想投产品'), 'pm')
        self.assertEqual(graph._direction_profile_update({}, '想投产品')['jd_info']['role_profile']['role_family'], 'ai_pm')
        for text in ('我做过一个AI产品项目', FIXTURE['aipm_real_inputs'][2], '这家公司的AI产品怎么样？'):
            self.assertFalse(graph._looks_like_role_direction(text), text)

    def test_unknown_target_does_not_block_experience_card_or_deepening(self):
        state = {'intake_stage': 'target', 'intake_progress': {'basics': 'skipped'},
                 'collected_info': {'projects': [{'item_id': 'p', 'name': '项目（待补名称）',
                     'facts': [fact('work', '开发简历工具')]}]}}
        self.assertEqual(intake_update(state)['intake_stage'], 'experiences')
        card = intake_guidance(state)
        self.assertEqual(card['items'][0]['name'], '')
        self.assertEqual(card['items'][0]['summary'], '开发简历工具')
        self.assertIn('顺带问一次', deepen_context(state)['instruction'])
        state['messages'] = [AIMessage(content='你想投什么岗位方向？')]
        self.assertIn('不再追问', deepen_context(state)['instruction'])
        state['intake_progress']['experiences'] = 'submitted'
        self.assertEqual(intake_update(state)['intake_stage'], 'deepen')

    def test_no_card_answers_follow_body_question_with_separate_banks(self):
        for module, bank in ((AIPM, AIPM.VALUES), (REAL, REAL.VALUES)):
            for prompt, dimension in [('用了什么技术栈？', 'tech_stack'), ('有多少人在用？', 'adoption'),
                                      ('关键产品决策是什么？', 'decision'), ('你最喜欢什么颜色？', 'unknown')]:
                value = bank.get(dimension)
                expected = '；'.join(value) if isinstance(value, list) else value or '不知道'
                self.assertEqual(AIPM.free_text_answer('已记下。\n\n' + prompt, bank), expected)
                if module is REAL:
                    self.assertEqual(REAL.submission({}, prompt), ('free_answer', expected, {}))
        self.assertEqual(AIPM.free_text_answer('> 例如你用了什么技术？\n已保存。', AIPM.VALUES), '不知道')

    def test_real_runner_sends_free_answer_instead_of_continue(self):
        sent = []
        class Client:
            def turn(self, action, text, **payload):
                sent.append((action, text, payload))
                return {'status': 'ok', 'workspace': {}, 'reply': '有多少人在用？'}
        turns = REAL.replay(Client())
        for _ in range(5):
            next(turns)
        self.assertEqual(sent[4], ('free_answer', '10 人', {}))
        turns.close()

    def test_free_answers_are_audited_and_unknown_dimension_stays_closed(self):
        turns = [{'workspace': {}, 'reply': '有多少人在用？'},
                 {'workspace': {}, 'input': '10 人', 'reply': '用了什么技术栈？'},
                 {'workspace': {}, 'input': '不知道', 'reply': '用了什么技术栈？'}]
        adoption, repeated = REAL._answer_audit(turns)
        self.assertTrue(adoption)
        self.assertEqual(repeated, ['tech_stack'])
        turns = [{'workspace': {}, 'reply': '关键产品决策是什么？'},
                 {'workspace': {}, 'input': AIPM.VALUES['decision']}]
        self.assertEqual(AIPM.submitted_values(turns), [AIPM.VALUES['decision']])


class Batch14c4RealGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_four_real_inputs_without_helpful_direction_triage(self):
        self.assertEqual(FIXTURE['aipm_real_inputs'], REAL.FIRST_TURNS)
        model = RealModel()
        compiled = graph.build_graph(model)
        async def triage(user_message, **kwargs):
            # Deliberately no SKIP_JD_OK / jd_keywords assistance for turn 2.
            return TriageDecision(action=TriageAction.ASK_EXPERIENCE, reason='正文收集')
        for context in (
            patch.object(graph, 'get_graph', return_value=compiled),
            patch.object(graph, '_make_non_streaming_llm', side_effect=lambda model, **kwargs: model),
            patch.object(graph, '_extract_info_from_message', side_effect=extract_real_stub),
            patch.object(graph, 'run_triage', side_effect=triage),
            patch('app.services.session_store.save_candidate_intake'), patch('app.services.session_store.save_resume_session'),
            patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value=PAGES),
            patch.object(get_settings(), 'LLM_PLAN_CONFIRM', True),
        ):
            self.enterContext(context)
        states = []
        async def turn(action, text, **payload):
            events = [e async for e in graph.stream_agent([{'role': 'user', 'content': text}], 'real-c4', model,
                **{k: v for k, v in payload.items() if k in {'intake', 'answers'}})]
            self.assertNotIn('"error"', str(events))
            state = (await compiled.aget_state({'configurable': {'thread_id': 'real-c4'}})).values
            states.append(state)
            return {'action': action, 'input': text, **payload, 'status': 'ok', 'sse_done': True,
                    'revision': text_hash(json.dumps(state.get('resume_data') or {}, ensure_ascii=False)),
                    'resume_data': deepcopy(state.get('resume_data') or {}),
                    'workspace': build_workspace(state, state.get('resume_data') or {}), 'stage': state.get('stage')}
        loop = asyncio.get_running_loop()
        class Client:
            def turn(self, *args, **kwargs):
                return asyncio.run_coroutine_threadsafe(turn(*args, **kwargs), loop).result(timeout=30)
        turns = await asyncio.to_thread(lambda: list(REAL.replay(Client())))
        self.assertEqual(states[1]['jd_info']['role_profile']['role_family'], 'ai_pm')
        fourth = turns[3]['workspace']
        self.assertEqual(fourth['intake_stage'], 'experiences')
        self.assertEqual(fourth['guidance']['items'][0]['name'], '')
        self.assertTrue(fourth['guidance']['items'][0]['summary'])
        self.assertEqual(turns[4]['workspace']['intake_stage'], 'deepen')
        self.assertEqual(turns[4]['workspace']['guidance']['kind'], 'ask_user')
        results = REAL.evaluate_persona('aipm_real', turns)
        self.assertTrue(all(r['status'] == 'pass' for r in results), results)
        save_evidence('aipm-real-stub.json',
                      {'evidence': 'real inputs with adverse triage and scripted models', 'turns': turns, 'checks': results})


class Batch14c4WriterTests(unittest.IsolatedAsyncioTestCase):
    async def test_misplaced_item_retries_before_lenient_schema_can_drop_it(self):
        self.enterContext(patch.object(get_settings(), 'LLM_WRITER_IGNORE_EXTRA_BULLET_FIELDS', True))
        self.enterContext(patch('app.services.fact_guard.verify_semantics', semantic_stub))
        calls = []
        class Model:
            def with_structured_output(self, schema):
                async def invoke(messages):
                    calls.append(messages)
                    if len(calls) == 1:
                        return schema.model_validate({'item_id': 'synthetic-paper', 'section': 'projects', 'title': {}, 'bullets': []})
                    return {'items': [{'item_id': 'synthetic-paper', 'section': 'projects', 'bullets': [
                        {'text': SOURCE['projects'][0]['facts'][0]['text'], 'fact_ids': [SOURCE['projects'][0]['facts'][0]['id']]}]}]}
                return SimpleNamespace(ainvoke=invoke)
        result = await run_resume_writer(SOURCE, {}, Model(), phase='write', previous_plan=PLAN)
        self.assertEqual(result['writer_diagnostic']['schema_retry_count'], 1)
        self.assertEqual(result['writer_diagnostic']['status'], 'model_completed')
        self.assertIn('schema_structure', calls[1][-1].content)
        self.assertTrue(result['resume_data']['projects'][0]['polished_bullets'])

    async def test_bad_root_twice_aborts_and_preserves_input(self):
        from app.services.error_codes import ChatTurnError
        self.enterContext(patch.object(get_settings(), 'LLM_WRITER_IGNORE_EXTRA_BULLET_FIELDS', True))
        class Model:
            def with_structured_output(self, schema):
                async def invoke(messages):
                    return {'item_id': 'synthetic-paper', 'section': 'projects', 'title': {}, 'bullets': []}
                return SimpleNamespace(ainvoke=invoke)
        current = {'projects': [{'item_id': 'synthetic-paper', 'name': '已有稿', 'polished_bullets': ['已核对的正文']}]}
        before = deepcopy(current)
        with self.assertRaises(ChatTurnError):
            await run_resume_writer(SOURCE, {}, Model(), current_data=current, phase='write', previous_plan=PLAN)
        self.assertEqual(current, before)

    async def test_ops_real_inputs_preview_excludes_constraints_and_writer_keeps_counts(self):
        model = PersonaModel('ops')
        source = await graph._extract_info_from_message(FIXTURE['ops_inputs'][0], {}, model)
        initial = graph._serialize_to_resume_data({'collected_info': source})
        source = await graph._extract_info_from_message(FIXTURE['ops_inputs'][1], source, model)
        before = deepcopy(source)
        preview = graph._serialize_to_resume_data({'collected_info': source})
        body = json.dumps(preview, ensure_ascii=False)
        self.assertNotIn('不是账号负责人', body)
        self.assertNotIn('没有后台权限', body)
        self.assertNotIn('选题由部长定', body)
        self.assertEqual(source, before)
        self.assertIn('负责人', json.dumps(source, ensure_ascii=False))
        self.enterContext(patch('app.services.fact_guard.verify_semantics', semantic_stub))
        result = await run_resume_writer(source, {'role_family': 'ops'}, model, current_data=preview)
        body = json.dumps(result['resume_data'], ensure_ascii=False)
        for number in ('6', '2', '4', '8', '3'):
            self.assertIn(number, body)
        self.assertNotIn('不是账号负责人', body)
        self.assertNotIn('选题由部长定', body)
        from app.agents.tailor_pipeline import run_tailor_pipeline
        self.enterContext(patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value=PAGES))
        polished = await run_tailor_pipeline({**result, 'stage': 'EVALUATING', 'collected_info': source},
            result['resume_data'], model, instruction=FIXTURE['ops_inputs'][2])
        turns = [record('initial', FIXTURE['ops_inputs'][0], initial, '已记录经历。'),
                 record('followup', FIXTURE['ops_inputs'][1], result['resume_data'], graph._writer_reply({**result, 'changed': True})),
                 record('polish', FIXTURE['ops_inputs'][2], polished['resume_data'], graph._writer_reply(polished))]
        checks = CHECKS.evaluate_persona('ops', turns)
        self.assertTrue(all(c['status'] == 'pass' for c in checks), [c for c in checks if c['status'] != 'pass'])
        save_evidence('ops-stub.json',
            {'evidence': 'real inputs through extraction/writer/local polish; reply and SSE envelopes are stubs',
             'turns': turns, 'checks': checks})

    async def test_empty_writer_never_preserves_collecting_preview_as_finished_prose(self):
        from app.agents.tailor_pipeline import run_tailor_pipeline
        model = PersonaModel('ops')
        source = await graph._extract_info_from_message(FIXTURE['ops_inputs'][0], {}, model)
        initial = graph._serialize_to_resume_data({'collected_info': source})
        source = await graph._extract_info_from_message(FIXTURE['ops_inputs'][1], source, model)
        base = graph._serialize_to_resume_data({'collected_info': source})
        plan = {'experience_plan': [{'item_id': p['item_id'], 'treatment': 'lead', 'target_bullets': 3}
                                    for s in ('work_experience', 'campus') for p in source.get(s, [])]}
        class Empty:
            def with_structured_output(self, schema):
                async def invoke(messages):
                    return {'items': []} if schema.__name__ == 'WriterDraft' else {'bullets': []}
                return SimpleNamespace(ainvoke=invoke)
        self.enterContext(patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value=PAGES))
        self.enterContext(patch('app.services.fact_guard.verify_semantics', semantic_stub))
        result = await run_tailor_pipeline({'stage': 'COLLECTING', 'resume_data': initial,
            'collected_info': source, 'confirmed_plan': plan}, base, Empty(), instruction=FIXTURE['ops_inputs'][1])
        self.assertEqual(result['writer_diagnostic']['status'], 'model_fallback')
        self.assertNotEqual(result['writer_diagnostic'].get('fallback_action'), 'preserved_existing_draft')
        body = '\n'.join(result['resume_data']['work_experience'][0]['bullets'])
        self.assertIn('6', body)
        self.assertIn('4', body)
        self.assertNotIn('不是账号负责人', body)
        self.assertNotEqual(body, '\n'.join(initial['work_experience'][0]['bullets']))

    def test_empty_label_is_removed_without_inventing_a_problem(self):
        text = '面向学生的 AI 简历助手，通过对话挖掘经历并据此撰写简历。'
        facts = {'f': fact('f', text, kind='context')}
        for prefix in ('：', ': ', '  ：', '问题：'):
            for style in ('plain', 'labeled'):
                row = format_rows([{'text': prefix + text, 'fact_ids': ['f']}], facts, style, role_family='ai_pm')[0]
                self.assertEqual(row['text'], text)
                self.assertEqual(row['fact_ids'], ['f'])
        pain = '学生难以梳理经历'
        row = format_rows([{'text': '：' + pain, 'fact_ids': ['f']}], {'f': fact('f', pain, kind='context')}, 'labeled')[0]
        self.assertEqual(row['text'], '问题：' + pain)

    def test_constraint_filter_preserves_action_and_untouched_punctuation(self):
        from app.services.candidate_language import without_wording_constraints
        self.assertEqual(without_wording_constraints('拍摄6条素材（不是账号负责人）。'), '拍摄6条素材。')
        for text in ('按店长给的文案制作4张海报。', '编写12条接口测试。', '测试环境耗时420ms降至190ms，没做线上压测。'):
            self.assertEqual(without_wording_constraints(text), text)


class Batch14c4CorrectionTests(unittest.IsolatedAsyncioTestCase):
    def test_exact_c3_polish_then_correction_survives_history_sanitizer(self):
        state = tech_state()
        corrected = apply_literal_corrections(state['collected_info'], state['resume_data'], state['resume_meta'],
                                               correction_pairs(FIXTURE['tech_inputs'][2], state['collected_info']))
        self.assertNotIn('error', corrected)
        cleaned = sanitize_fact_history({**corrected, 'resume_versions': [state]})
        work = cleaned['resume_data']['work_experience'][0]
        self.assertEqual(len(work['bullets']), 3)
        self.assertEqual(work['bullets'][1], state['resume_data']['work_experience'][0]['bullets'][1].replace('170', '190'))
        self.assertEqual(cleaned['resume_data']['projects'], state['resume_data']['projects'])
        self.assertNotIn('170', json.dumps(cleaned['resume_versions'][0]['resume_data'], ensure_ascii=False))
        for text, record in zip(work['bullets'], cleaned['resume_meta']['bullets'][work['item_id']]):
            self.assertEqual(record['text_hash'], text_hash(text))

    def test_swapped_citation_or_old_and_new_claim_still_removed(self):
        state = tech_state()
        corrected = apply_literal_corrections(state['collected_info'], state['resume_data'], state['resume_meta'],
                                               correction_pairs(FIXTURE['tech_inputs'][2], state['collected_info']))
        for suffix in ('；旧数据平均耗时由约 420ms 降到约 170ms', ''):
            candidate = deepcopy(corrected)
            work = candidate['resume_data']['work_experience'][0]
            text = work['bullets'][1] + suffix if suffix else work['bullets'][1].replace('190', '170')
            work['bullets'][1] = text
            candidate['resume_meta']['bullets'][work['item_id']][1]['text_hash'] = text_hash(text)
            self.assertEqual(len(sanitize_fact_history(candidate)['resume_data']['work_experience'][0]['bullets']), 2)

    def test_corrected_clause_keeps_unrelated_numbers_with_shared_digits(self):
        old = '平均耗时由约420ms降到约170ms'
        new = old.replace('170', '190')
        for count in (17, 1700):
            action = f'编写{count}条接口测试'
            body = f'在测试环境{new}，没做线上压测，并{action}'
            source = {'work_experience': [{'item_id': 'w', 'facts': [
                {**fact('old', old), 'source_quote': body.replace('190', '170'), 'status': 'superseded'},
                {**fact('new', new), 'replaces': 'old'}, fact('tests', action)]}]}
            data = {'work_experience': [{'item_id': 'w', 'bullets': [body]}]}
            meta = {'bullets': {'w': [{'fact_ids': ['new', 'tests'], 'text_hash': text_hash(body)}]}}
            cleaned = sanitize_fact_history({'collected_info': source, 'resume_data': data, 'resume_meta': meta})
            self.assertEqual(cleaned['resume_data'], data)
            self.assertEqual(cleaned['resume_meta'], meta)

    async def test_correction_graph_receipt_matches_saved_body(self):
        self.enterContext(patch('app.services.resume_capacity.measure_rendered_pages', return_value=PAGES))
        state = tech_state()
        result = await graph._evaluating_turn_node(state, None)
        cleaned = sanitize_fact_history(result)
        self.assertIn('已更新正文', result['messages'][0].content)
        body = '\n'.join(cleaned['resume_data']['work_experience'][0]['bullets'])
        for required in ('420', '190', '测试环境', '没做线上压测', '12', '4 人'):
            self.assertIn(required, body)
        self.assertNotIn('170', body)
        turns = [record('initial', FIXTURE['tech_inputs'][0], state['resume_data'], '已生成草稿。'),
                 record('polish', FIXTURE['tech_inputs'][1], state['resume_data'], '已润色。'),
                 record('correction', FIXTURE['tech_inputs'][2], cleaned['resume_data'], result['messages'][0].content)]
        checks = CHECKS.evaluate_persona('tech', turns)
        self.assertTrue(all(c['status'] == 'pass' for c in checks), [c for c in checks if c['status'] != 'pass'])
        save_evidence('tech-correction-stub.json',
            {'evidence': 'frozen pre-correction state through current correction node and persistence sanitizer; initial/polish are replayed state',
             'turns': turns, 'checks': checks})

    def test_demo_scope_adds_only_missing_boundary_and_is_idempotent(self):
        source = {'projects': [{'item_id': 'p', 'name': '校园二手交易系统', 'facts': [
            fact('deploy', '部署在实验室服务器，只给班里演示，没有真实用户', kind='status_limit')]}]}
        text = '负责商品发布与搜索接口，部署于实验室服务器并面向班级演示'
        data = {'projects': [{'item_id': 'p', 'name': '校园二手交易系统', 'polished_bullets': [text]}]}
        meta = {'bullets': {'p': [{'fact_ids': ['deploy'], 'text_hash': text_hash(text)}]}}
        result, metadata, _ = preserve_item_limits(data, meta, source, item_ids=['p'])
        body = result['projects'][0]['polished_bullets'][0]
        self.assertEqual(body.count('实验室服务器'), 1)
        self.assertIn('仅面向班级演示', body)
        self.assertEqual(body.count('演示'), 1)
        self.assertNotIn('没有真实用户', body)
        again, again_meta, _ = preserve_item_limits(result, metadata, source, item_ids=['p'])
        self.assertEqual(again, result)
        self.assertEqual(again_meta, metadata)
        self.assertEqual(metadata['bullets']['p'][0]['text_hash'], text_hash(body))


if __name__ == '__main__':
    unittest.main()
