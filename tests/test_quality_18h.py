"""Duplicate confirmation, mixed JD messages and hollow lead-ins. Fictional data only."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'tests')]
from langchain_core.messages import AIMessage, HumanMessage
from app.agents import orchestrator as loop, orchestrator_tools as tools
from app.agents.resume_graph import _serialize_to_resume_data
from app.config import Settings
from app.services.candidate_language import non_fact, without_empty_lead_in
from app.services.resume_facts import normalize_fact_store
from app.services.resume_preflight import (
    DUPLICATE_NO, DUPLICATE_YES, check_resume, clean_prose, preflight_resume, suspected_duplicates)
from app.services.resume_versions import valid_bullet_metadata
from test_orchestrator import Model, call
from test_quality_18g import MESSAGE, fixture

PAIR = ('trip-original', 'trip-relationship')


def base_state(text='简历好像有内容重复了'):
    store = normalize_fact_store(fixture())
    data, meta, _ = preflight_resume(_serialize_to_resume_data({'collected_info': store, 'messages': []}), {}, store)
    return dict(collected_info=store, resume_data=data, resume_meta=meta, resume_versions=[],
                messages=[HumanMessage(content=text, id='turn-1')])


def item_ids(data):
    return [row['item_id'] for row in data['projects']]


def bullets(row):
    return [*(row.get('polished_bullets') or []), *(row.get('description') or '').splitlines()]


class LoopCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch('app.config.get_settings', return_value=Settings(_env_file=None, AGENT_MODE='loop')))
        self.enterContext(patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={'pages': 1}))
        self.enterContext(patch('app.services.resume_capacity.measure_rendered_pages', return_value={'pages': 1}))

    async def ask(self, text='简历好像有内容重复了'):
        state = base_state(text)
        result = await tools.edit_resume(state, {'instruction': '合并重复的内容'}, tools.ToolContext(turn_id='card-1'))
        return state, result

    def answered(self, state, result, value):
        card = result.update['messages'][0].additional_kwargs['ask_user']
        question = card['questions'][0]
        answer = HumanMessage(content=value, id='turn-2', additional_kwargs={
            'answers': {'turn_id': card['turn_id'], 'items': [{'id': question['id'], 'value': [value]}]}})
        return {**state, 'messages': [*state['messages'], *result.update['messages'], answer]}


class VagueComplaintTests(LoopCase):
    async def test_complaint_with_only_a_suspected_pair_asks_and_removes_nothing(self):
        state, result = await self.ask()
        self.assertEqual(result.result['status'], 'needs_confirmation')
        self.assertEqual(result.result['candidates'], [{'section': 'projects', 'names': ['mtagent', '同路 mtagent']}])
        self.assertFalse(result.result['changed'])
        self.assertEqual(set(result.update), {'messages'})
        self.assertTrue(result.stop)
        card = result.update['messages'][0].additional_kwargs['ask_user']
        self.assertEqual([(q['prompt'], q['options']) for q in card['questions']], [
            ('「mtagent」和「同路 mtagent」是同一个项目吗？', ['是，合并成一条', '不是，分开保留'])])
        self.assertEqual(result.events[-1]['guidance'], card)
        self.assertEqual(item_ids(state['resume_data']), ['trip-original', 'trip-relationship', 'resume-unnamed'])

    async def test_other_vague_wordings_never_merge_look_alikes(self):
        for text in ('内容重复了', '有重复，帮我去重', '简历有重复内容，整理一下'):
            with self.subTest(text=text):
                _, result = await self.ask(text)
                self.assertEqual(result.result['status'], 'needs_confirmation')
                self.assertNotIn('resume_data', result.update)

    async def test_named_pair_merges_directly_without_a_card(self):
        state = base_state('mtagent 和同路 mtagent 是同一个项目，合并')
        result = await tools.edit_resume(state, {'instruction': state['messages'][0].content}, tools.ToolContext())
        self.assertEqual(item_ids(result.update['resume_data']), ['trip-original', 'resume-unnamed'])
        self.assertNotIn('messages', result.update)
        self.assertNotEqual(result.result['status'], 'needs_confirmation')

    async def test_proven_duplicates_still_merge_on_a_vague_complaint_while_look_alikes_are_asked(self):
        state = base_state()
        extra = {'item_id': 'trip-copy', 'name': 'mtagent', 'role': '项目发起人', 'start_date': '2025.09',
                 'polished_bullets': ['补充路线回退']}
        state['resume_data']['projects'].append(extra)
        state['collected_info']['projects'].append({**deepcopy(state['collected_info']['projects'][0]),
                                                    'item_id': 'trip-copy', 'facts': []})
        result = await tools.edit_resume(state, {'instruction': '合并重复内容'}, tools.ToolContext(turn_id='card-1'))
        merged = result.update['resume_data']['projects']
        self.assertNotIn('trip-copy', item_ids(result.update['resume_data']))
        self.assertIn('补充路线回退', str([bullets(row) for row in merged]))
        self.assertIn('trip-relationship', item_ids(result.update['resume_data']))
        self.assertEqual(result.result['needs_confirmation'], [{'section': 'projects', 'names': ['mtagent', '同路 mtagent']}])
        self.assertTrue(result.result['card_shown'])

    async def test_merge_that_did_not_happen_never_deletes_an_entry(self):
        from app.services import edit_plan
        real = edit_plan.execute_edit_plan

        def lossy(*args, **kwargs):
            executed = real(*args, **kwargs)
            executed['data']['projects'] = executed['data']['projects'][:1]
            return executed
        state = base_state()
        with patch('app.services.edit_plan.execute_edit_plan', side_effect=lossy):
            result = await tools.edit_resume(state, {'instruction': '合并重复内容'}, tools.ToolContext(turn_id='card-1'))
        self.assertEqual(result.result['status'], 'insufficient')
        self.assertEqual(result.update, {})


class AnswerTests(LoopCase):
    async def run_answer(self, state):
        model = Model([{'content': '好的。'}])
        return await loop.run_orchestrator(state, model, registry=tools.TOOLS)

    async def test_yes_merges_and_every_fact_of_the_merged_entry_survives(self):
        state, result = await self.ask()
        before = {row['item_id']: row for row in state['resume_data']['projects']}
        outcome = await self.run_answer(self.answered(state, result, DUPLICATE_YES))
        projects = {row['item_id']: row for row in outcome['resume_data']['projects']}
        self.assertEqual(list(projects), ['trip-original', 'resume-unnamed'])
        kept = str(bullets(projects['trip-original']))
        for line in [*bullets(before['trip-original']), *bullets(before['trip-relationship'])]:
            if line:
                self.assertIn(line, kept)
        self.assertEqual(outcome['resume_meta']['merged_items']['trip-original'], list(PAIR))
        self.assertIn('已把「mtagent」和「同路 mtagent」合并成一条', outcome['messages'][-1].content)
        self.assertNotIn('duplicate_experience', {row['category'] for row in outcome['resume_meta']['precheck']['issues']})
        self.assertEqual(outcome.get('collected_info', state['collected_info']), state['collected_info'])
        self.assertTrue(outcome['version_id'])

    async def test_no_keeps_both_and_the_pair_is_never_reported_again(self):
        state, result = await self.ask()
        self.assertTrue(any(row['category'] == 'duplicate_experience'
                            for row in check_resume(state['resume_data'], state['collected_info'])['issues']))
        outcome = await self.run_answer(self.answered(state, result, DUPLICATE_NO))
        self.assertEqual(item_ids(outcome.get('resume_data', state['resume_data'])), item_ids(state['resume_data']))
        self.assertEqual(outcome['collected_info']['distinct_experiences'], [list(PAIR)])
        self.assertIn('分开保留', outcome['messages'][-1].content)
        after = {**state, **outcome}
        self.assertFalse(any(row['category'] == 'duplicate_experience' for row in check_resume(
            after['resume_data'], after['collected_info'], meta=after['resume_meta'])['issues']))
        self.assertFalse(suspected_duplicates(after['resume_data'], after['collected_info'], after['resume_meta']))
        # The same complaint now has nothing left to ask or merge.
        again = await tools.edit_resume({**after, 'messages': [HumanMessage(content='内容重复了', id='turn-3')]},
                                        {'instruction': '去重'}, tools.ToolContext(turn_id='card-2'))
        self.assertNotEqual(again.result['status'], 'needs_confirmation')
        self.assertEqual(item_ids(again.update.get('resume_data', after['resume_data'])), item_ids(state['resume_data']))
        # Even a complaint that names the shared core cannot override the answer.
        named = await tools.edit_resume({**after, 'messages': [HumanMessage(content='mtagent 有重复，去重', id='turn-4')]},
                                        {'instruction': '去重'}, tools.ToolContext(turn_id='card-3'))
        self.assertEqual(item_ids(named.update.get('resume_data', after['resume_data'])), item_ids(state['resume_data']))

    async def test_skipped_answer_changes_nothing(self):
        state, result = await self.ask()
        answered = self.answered(state, result, '不知道')
        outcome = await self.run_answer(answered)
        self.assertEqual(item_ids(outcome.get('resume_data', state['resume_data'])), item_ids(state['resume_data']))
        self.assertNotIn('distinct_experiences', outcome.get('collected_info', {}))


class SystemCardTests(LoopCase):
    INVENTED = {'subject': '内容重复确认', 'questions': [{
        'id': 'confirm_mtagent_dup', 'prompt': 'mtagent 与同路 mtagent 是同一段经历吗？', 'kind': 'single',
        'options': ['是同一个项目，合并成一段', '是两个不同项目，保持独立']}]}

    def cards(self, messages):
        return [m.additional_kwargs['ask_user'] for m in messages
                if isinstance(m, AIMessage) and m.additional_kwargs.get('ask_user')]

    async def test_check_resume_attaches_the_system_card_on_a_complaint(self):
        state = base_state('简历好像有内容重复了铁铁')
        result = await tools.check_resume(state, {}, tools.ToolContext(turn_id='card-1'))
        self.assertTrue(result.result['confirmation_attached'])
        self.assertTrue(any(row['category'] == 'duplicate_experience' for row in result.result['issues']))
        self.assertEqual(self.cards(result.update['messages'])[0]['questions'][0]['id'][:4], 'dup-')
        # Not a complaint: a plain read, no card and the unchanged contract.
        plain = await tools.check_resume(base_state('帮我看看排版'), {}, tools.ToolContext())
        self.assertEqual((set(plain.result), plain.update), ({'status', 'issues', 'counts'}, {}))

    async def test_model_made_duplicate_card_is_replaced_by_the_system_card(self):
        for script in ([call('check_resume'), call('ask_user', card=self.INVENTED)],
                       [call('ask_user', card=self.INVENTED)]):
            with self.subTest(first=script[0]['calls'][0]['name']):
                state = base_state('简历好像有内容重复了铁铁')
                outcome = await loop.run_orchestrator(state, Model([*script, {'content': '请先确认一下。'}]),
                                                      registry=tools.TOOLS)
                shown = self.cards(outcome['messages'])
                self.assertEqual({q['id'][:4] for card in shown for q in card['questions']}, {'dup-'})
                final = outcome['messages'][-1].additional_kwargs['ask_user']
                self.assertEqual(final['questions'][0]['prompt'], '「mtagent」和「同路 mtagent」是同一个项目吗？')
                # Answering “不是” is acted on by code.
                answer = HumanMessage(content=DUPLICATE_NO, id='turn-2', additional_kwargs={'answers': {
                    'turn_id': final['turn_id'], 'items': [{'id': final['questions'][0]['id'], 'value': [DUPLICATE_NO]}]}})
                later = {**state, **{k: v for k, v in outcome.items() if k != 'messages'},
                         'messages': [*state['messages'], *outcome['messages'], answer]}
                done = await loop.run_orchestrator(later, Model([{'content': '好的。'}]), registry=tools.TOOLS)
                self.assertEqual(done['collected_info']['distinct_experiences'], [list(PAIR)])

    async def test_edit_after_an_attached_card_does_not_ask_twice(self):
        state = base_state('简历好像有内容重复了铁铁')
        ctx = tools.ToolContext(turn_id='card-1')
        await tools.check_resume(state, {}, ctx)
        edit = await tools.edit_resume(state, {'instruction': '去重'}, ctx)
        self.assertEqual(edit.result['status'], 'needs_confirmation')
        self.assertTrue(edit.result['card_shown'])
        self.assertNotIn('messages', edit.update)


class MergeConflictTests(unittest.TestCase):
    def rows(self):
        return {'projects': [
            {'item_id': 'a', 'name': 'mtagent', 'role': '项目发起人', 'polished_bullets': ['设计多 Agent 架构']},
            {'item_id': 'b', 'name': '同路 mtagent', 'role': '个人项目', 'polished_bullets': ['设计四种关系画像']}]}

    def test_conflicts_of_an_undone_or_rewritten_merge_do_not_linger(self):
        stale = {'merged_items': {'a': ['a', 'b']}, 'merge_conflicts': {'a': {'role': ['项目发起人', '个人项目']}}}
        data = self.rows()
        self.assertFalse(any(row['category'] == 'role_conflict' for row in check_resume(data, meta=stale)['issues']))
        pruned = valid_bullet_metadata(data, stale)
        self.assertEqual((pruned['merged_items'], pruned['merge_conflicts']), ({}, {}))
        _, meta, _ = preflight_resume(data, stale)
        self.assertEqual((meta['merged_items'], meta['merge_conflicts']), ({}, {}))

    def test_conflicts_of_a_real_merge_are_kept_and_reported(self):
        data = self.rows()
        merged, meta, report = preflight_resume(data, {}, {}, confirmed_pairs=[('a', 'b')])
        self.assertEqual(len(merged['projects']), 1)
        self.assertEqual(meta['merged_items'], {'a': ['a', 'b']})
        self.assertEqual(meta['merge_conflicts']['a']['role'], ['项目发起人', '个人项目'])
        self.assertTrue(any(row['category'] == 'role_conflict' for row in check_resume(merged, meta=meta)['issues']))
        self.assertEqual(valid_bullet_metadata(merged, meta)['merge_conflicts'], meta['merge_conflicts'])


class MixedJdTests(unittest.IsolatedAsyncioTestCase):
    TEXT = ('岗位职责：负责 AI 应用后端开发，参与多 Agent 流程设计与上线。任职要求：熟悉 Python 与 FastAPI，了解大模型应用开发。\n\n'
            '另外我做过一个旅行规划项目，向 demo-org/demo-repo 提交了 PR https://github.com/demo-org/demo-repo/pull/6 '
            '和 https://github.com/demo-org/demo-repo/pull/8，均已合入上游。')

    async def test_jd_body_is_decoded_and_candidate_urls_are_ignored(self):
        self.assertEqual(tools._source_parts(self.TEXT)[1], '')
        state = {'messages': [HumanMessage(content=self.TEXT, id='mixed')]}
        decoded = {'jd_info': {'job_title': 'AI 应用工程师', 'required_skills': ['Python']}}
        with patch('app.agents.decoder_chain.run_decoder_chain', new=AsyncMock(return_value=decoded)) as decoder, \
                patch('app.services.job_intel.read_job_url', new=AsyncMock()) as reader:
            result = await tools.read_jd(state, {'source_id': 'current'}, tools.ToolContext(llm=object()))
        self.assertEqual(result.result['status'], 'ok')
        self.assertEqual(result.update['jd_info']['job_title'], 'AI 应用工程师')
        self.assertEqual(decoder.call_args.args[0], self.TEXT)
        reader.assert_not_awaited()


    REAL = (
        '岗位：AI 应用工程师（2027 校招，深圳）\n'
        '职责：负责 AI Agent 及场景化 AI 应用的设计、开发、调试与上线；收集并分析 Bad Case，优化 Prompt 工程；对接业务需求设计技术方案。\n'
        '要求：熟悉 Python；了解大模型、Prompt、Agent 等概念；有 AI 相关项目经历优先。\n\n'
        '针对这份岗位给我做一份简历。我叫测试同学，电话 13800000000，邮箱 test@example.com，个人主页 example.cn，'
        'GitHub github.com/testuser，个人主页 https://example.cn/，GitHub https://github.com/TESTUSER。\n'
        '教育：某某大学 计算机科学与技术 本科 2023.09—预计2027年6月。\n'
        '项目1：mtagent，多 Agent 协作的旅行行程规划应用，我是项目发起人，向 demo-org/demo-repo 提交了 PR '
        'https://github.com/demo-org/demo-repo/pull/6 和 https://github.com/demo-org/demo-repo/pull/8，均已合入上游。')

    async def test_unprefixed_jd_paragraph_with_three_distinct_urls_is_decoded(self):
        candidate, jd = tools._source_parts(self.REAL)
        self.assertTrue(jd.startswith('岗位：AI 应用工程师') and jd.endswith('有 AI 相关项目经历优先。'))
        self.assertIn('我叫测试同学', candidate)
        self.assertNotIn('岗位：', candidate)
        state = {'messages': [HumanMessage(content=self.REAL, id='real')]}
        decoded = {'jd_info': {'job_title': 'AI 应用工程师', 'required_skills': ['Python']}}
        with patch('app.agents.decoder_chain.run_decoder_chain', new=AsyncMock(return_value=decoded)) as decoder, \
                patch('app.services.job_intel.read_job_url', new=AsyncMock()) as reader:
            result = await tools.read_jd(state, {'source_id': 'current'}, tools.ToolContext(llm=object()))
        self.assertEqual(result.result['status'], 'ok', result.result)
        self.assertEqual(decoder.call_args.args[0], jd)
        reader.assert_not_awaited()
        # The candidate paragraph stays usable as personal material.
        self.assertNotIn('real', result.update.get('non_candidate_message_ids', []))

    async def test_a_message_that_is_only_links_still_reads_the_link_or_refuses_several(self):
        state = {'messages': [HumanMessage(content='看看这两个岗位 https://jobs.example.invalid/1 https://jobs.example.invalid/2', id='links')]}
        with patch('app.services.job_intel.read_job_url', new=AsyncMock()) as reader:
            result = await tools.read_jd(state, {'source_id': 'current'}, tools.ToolContext(llm=object()))
        self.assertEqual(result.result['code'], 'multiple_urls')
        reader.assert_not_awaited()


class HollowLeadInTests(unittest.IsolatedAsyncioTestCase):
    def test_announcement_without_content_is_not_a_fact(self):
        for text in ('本人做了几个关键决定', '本人做了几个关键决定：', '做了以下决策：', '完成出几个关键设计决定'):
            self.assertTrue(non_fact(text), text)
            self.assertEqual(without_empty_lead_in(text), '')
        self.assertEqual(without_empty_lead_in('本人做了几个关键决定：设计四种关系画像，加入必去点和返程时间约束'),
                         '设计四种关系画像，加入必去点和返程时间约束')
        for text in ('设计四种关系画像', '完成了4个设计', '做了两个关键决定：先体验后登录'):
            self.assertFalse(non_fact(text), text)
            self.assertEqual(without_empty_lead_in(text), text)

    def test_delivered_prose_keeps_only_the_specifics(self):
        text = '完成出几个关键设计决定，向 demo-org/demo-repo 提交 PR #6、#8 并已合入上游'
        self.assertEqual(clean_prose(text), '向 demo-org/demo-repo 提交 PR #6、#8 并已合入上游')
        data = {'projects': [{'item_id': 'p', 'name': '同路 mtagent', 'polished_bullets': [
            text, '决策：本人做了几个关键决定：设计四种关系画像；加入必去点和返程时间约束']}]}
        output, _, _ = preflight_resume(data)
        self.assertNotIn('几个关键', str(output))
        self.assertIn('决策：设计四种关系画像；加入必去点和返程时间约束', output['projects'][0]['polished_bullets'])

    async def test_extraction_drops_the_announcement_and_keeps_the_decisions(self):
        from app.agents.fact_extractor import apply_fact_patch, extract_facts_patch
        from test_fact_extractor import FakeLLM
        quote = '本人做了几个关键决定：设计四种关系画像'
        candidate = {'items': [{'section': 'projects', 'name': '同路 mtagent', 'facts': [
            {'text': '本人做了几个关键决定', 'source_quote': '本人做了几个关键决定', 'kind': 'action'},
            {'text': quote, 'source_quote': quote, 'kind': 'action'},
            {'text': '加入必去点和返程时间约束', 'source_quote': '加入必去点和返程时间约束', 'kind': 'action'}]}]}
        patch_ = await extract_facts_patch(MESSAGE, {}, FakeLLM(candidate), turn_id='fictional-message')
        facts = [fact['text'] for item in apply_fact_patch({}, patch_)['projects'] for fact in item['facts']]
        self.assertIn('设计四种关系画像', facts)
        self.assertIn('加入必去点和返程时间约束', facts)
        self.assertFalse([text for text in facts if '几个关键决定' in text], facts)



class CodeLinkLabelTests(unittest.TestCase):
    def test_existing_pr_label_is_not_doubled(self):
        from app.services.resume_preflight import compact_code_links
        text = 'PR https://github.com/demo-org/demo-repo/pull/6 和 https://github.com/demo-org/demo-repo/pull/8 已合入上游'
        self.assertEqual(compact_code_links(text), 'PR #6、#8 已合入上游')

if __name__ == '__main__':
    unittest.main()
