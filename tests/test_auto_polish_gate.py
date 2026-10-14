"""Fictional two-turn replay; extraction, writing and semantics are all stubs."""
import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from test_campus_and_naming import ExtractorStub, raw, semantic_stub
from app.agents import resume_graph as graph
from app.agents.fact_extractor import apply_fact_patch, extract_facts_patch
from app.agents.resume_writer import run_resume_writer
from app.services.auto_polish_gate import needs_polish
from app.services.candidate_language import constraint_only, resume_bullet
from app.services.fact_coverage import cite_entailed_facts, coverage_notice, ensure_fact_coverage, text_covered
from app.services.fact_guard import guard_bullets
from app.services.resume_facts import new_fact
from app.services.resume_versions import text_hash


FIRST = '我想投新媒体运营……我叫陈夏，江城学院新闻学本科，2022 年 9 月入学，2026 年 6 月毕业。大三在校园读书协会帮忙做过公众号排版，也写过推文，但没有认真统计数据。还在一家咖啡店做过两个月兼职，拍过店里的短视频，也帮店长做海报，我不是账号负责人。会用剪映、Canva、Excel，会一点 PS。'
SECOND = '读书协会是 2024 年 9 月到 2025 年 6 月。我排版过 8 篇公众号文章，其中 3 篇的初稿是我写的，选题由部长定；没有阅读量数据。咖啡店叫小巷咖啡，2025 年 7 月到 8 月，我用手机拍过 6 条短视频素材，其中 2 条被店长发布，我没有后台权限，不知道播放量。我还做过 4 张促销海报，店长给文案，我用 Canva 排版。请直接生成……不要再追问'
GOOD = '协助协会公众号内容，完成8篇文章排版，其中3篇初稿由本人撰写。'
VIDEO = '使用手机拍摄6条短视频素材，其中2条被店长发布。'


async def replay():
    # Deliberately wrong model ownership and a second, unnamed campus item.
    first = {'basic_info': {'objective': '新媒体运营', 'name': '陈夏'}, 'items': [
        {'section': 'campus', 'name': '校园读书协会', 'facts': [raw(value) for value in (
            '大三在校园读书协会帮忙做过公众号排版', '也写过推文', '但没有认真统计数据',
            '还在一家咖啡店做过两个月兼职', '拍过店里的短视频', '也帮店长做海报', '我不是账号负责人')]}]}
    collected = apply_fact_patch({}, await extract_facts_patch(FIRST, {}, ExtractorStub(first)))
    second = {'items': [
        {'section': 'campus', 'name': '读书协会', 'facts': [raw(value) for value in (
            '我排版过 8 篇公众号文章', '其中 3 篇的初稿是我写的', '选题由部长定', '没有阅读量数据',
            '咖啡店叫小巷咖啡', '我用手机拍过 6 条短视频素材', '其中 2 条被店长发布',
            '我没有后台权限', '不知道播放量')]},
        {'section': 'campus', 'name': '', 'facts': [raw(value) for value in (
            '我还做过 4 张促销海报', '店长给文案', '我用 Canva 排版')]}]}
    collected = apply_fact_patch(collected, await extract_facts_patch(SECOND, collected, ExtractorStub(second)))
    return collected


class PartialWriter:
    def __init__(self, *, hallucinate=False, fail_polish=False):
        self.schema = None
        self.polished = []
        self.hallucinate = hallucinate
        self.fail_polish = fail_polish

    def with_structured_output(self, schema):
        self.schema = schema.__name__
        return self

    async def ainvoke(self, messages):
        payload = json.loads(messages[-1].content)
        if self.schema == 'RepairOutput':
            if self.fail_polish:
                raise RuntimeError('synthetic outage')
            rows = payload.get('bullets', [])
            self.polished.extend(deepcopy(rows))
            return {'bullets': [{
                'id': row['id'], 'fact_ids': row['fact_ids'],
                'text': ('负责运营账号，粉丝增长1000人。' if self.hallucinate else
                         VIDEO if '短视频' in row['text'] else resume_bullet(row['text']))} for row in rows]}
        rows = []
        for section in ('campus', 'work_experience'):
            for item in payload['evidence'].get(section, []):
                facts = item['facts']
                markers = ('8 篇', '3 篇') if section == 'campus' else ('6 条', '2 条')
                refs = [fact['id'] for fact in facts if any(marker in fact['text'] for marker in markers)]
                if refs:
                    rows.append({'section': section, 'item_id': item['item_id'], 'bullets': [{
                        'text': GOOD if section == 'campus' else '我用手机拍过6条短视频素材，其中2条被店长发布了。',
                        'fact_ids': refs}]})
        return {'match_plan': {}, 'writer': {'items': rows}}


class AutoPolishGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_turn_replay_preserves_good_prose_and_ownership(self):
        source = await replay()
        self.assertEqual(len(source['campus']), 1)
        self.assertEqual(len(source['work_experience']), 1)
        self.assertEqual(source['work_experience'][0]['company'], '小巷咖啡')
        self.assertTrue(any('4 张' in f['text'] for f in source['work_experience'][0]['facts']))
        self.assertFalse(any('海报' in f['text'] for f in source['campus'][0]['facts']))
        model = PartialWriter()
        with patch('app.services.fact_guard.verify_semantics', semantic_stub):
            result = await run_resume_writer(source, {}, model)
        data, meta = result['resume_data'], result['resume_meta']
        campus = data['campus'][0]
        coffee = data['work_experience'][0]
        bullets = campus['bullets'] + coffee['bullets']
        self.assertIn(GOOD, campus['bullets'])
        self.assertEqual(campus['bullets'], [GOOD])
        good_meta = meta['bullets'][campus['item_id']][campus['bullets'].index(GOOD)]
        self.assertEqual(good_meta['polish'], {'rewritten': False, 'reasons': [], 'method': 'unchanged'})
        self.assertNotIn(GOOD, [row['text'] for row in model.polished])
        self.assertIn(VIDEO, coffee['bullets'])
        self.assertTrue(any('4' in text and '促销海报' in text for text in coffee['bullets']))
        self.assertEqual(sum('短视频' in text for text in coffee['bullets']), 1)
        self.assertEqual(sum('海报' in text for text in coffee['bullets']), 1)
        for forbidden in ('写过推文', '拍过店里的短视频', '帮店长做海报', '后台权限', '负责人', '没有阅读量', '不知道播放量', '选题由', '店长给文案', '负责', '运营账号', '策划'):
            self.assertNotIn(forbidden, '\n'.join(bullets))
        for group in (campus['bullets'], coffee['bullets']):
            self.assertFalse(any(text_covered(a, [b]) for i, a in enumerate(group) for j, b in enumerate(group) if i != j), group)
        self.assertEqual(set(data['skills']), {'Canva', 'Photoshop（基础）', 'Excel', '剪映'})
        self.assertFalse(any(constraint_only(f['text']) for f in meta['fact_coverage']['facts']))
        reply = graph._writer_reply({**result, 'changed': True})
        self.assertNotIn('备用、不展示', reply)
        self.assertNotIn('这句没有记下来：我想投新媒体运营', reply)
        state = {'messages': [HumanMessage(content=FIRST), HumanMessage(content=SECOND)], 'collected_info': source}
        self.assertEqual(graph._interview_suffix(state, result)[0], '')
        finished = graph._finish_followup_turn(state, {**result, 'stage': 'EVALUATING', 'messages': [AIMessage(content=reply)]})
        self.assertNotIn('需要你补充', ''.join(m.content for m in finished['messages']))
        self.assertNotIn('？', ''.join(m.content for m in finished['messages']))

    async def test_independent_missing_fact_is_polished_and_invention_rejected(self):
        for fail, hallucinate in ((False, False), (True, False), (False, True)):
            source = await replay()
            fact = new_fact('我还整理过30份订单记录了', kind='action')
            source['work_experience'][0]['facts'].append(fact)
            with patch('app.services.fact_guard.verify_semantics', semantic_stub):
                result = await run_resume_writer(source, {}, PartialWriter(fail_polish=fail, hallucinate=hallucinate))
            bullets = result['resume_data']['work_experience'][0]['bullets']
            self.assertTrue(any('30份订单记录' in text for text in bullets), bullets)
            self.assertNotIn('我还整理过30份订单记录了', bullets)
            self.assertNotIn('1000', '\n'.join(bullets))
            self.assertFalse(any('负责' in text for text in bullets))

    async def test_explicit_return_to_association_wins_over_recency(self):
        current = await replay()
        quote = '在协会也做过海报'
        result = apply_fact_patch(current, await extract_facts_patch('咖啡店的工作结束后，在协会也做过海报。', current,
            ExtractorStub({'items': [{'section': 'work_experience', 'item_id': current['work_experience'][0]['item_id'],
                                     'facts': [raw(quote)]}]})))
        self.assertTrue(any(f['source_quote'] == quote for f in result['campus'][0]['facts']))
        self.assertFalse(any(f['source_quote'] == quote for f in result['work_experience'][0]['facts']))

    async def test_nearest_named_owner_with_two_work_experiences(self):
        source = {'work_experience': [
            {'item_id': 'a', 'company': '青松公司', 'facts': [new_fact('整理资料')]},
            {'item_id': 'b', 'company': '白鹿公司', 'facts': [new_fact('拍摄视频')]}]}
        quote = '也帮店长做海报'
        message = '在青松公司整理资料，后来在白鹿公司拍摄视频，也帮店长做海报。'
        result = apply_fact_patch(source, await extract_facts_patch(message, source, ExtractorStub({
            'items': [{'section': 'work_experience', 'item_id': 'a', 'facts': [raw(quote)]}]})))
        self.assertEqual(len(result['work_experience']), 2)
        self.assertTrue(any(f['source_quote'] == quote for f in result['work_experience'][1]['facts']))
        self.assertFalse(any(f['source_quote'] == quote for f in result['work_experience'][0]['facts']))

    async def test_uncited_constraints_still_reject_responsibility_upgrade(self):
        facts = [dict(new_fact('拍摄6条短视频素材', kind='action'), item_id='coffee'),
                 dict(new_fact('我没有后台权限', kind='status_limit'), item_id='coffee')]
        result = await guard_bullets([{'id': 'b', 'item_id': 'coffee', 'text': '负责运营账号并拍摄6条短视频素材',
                                      'fact_ids': [facts[0]['id']]}], facts, lexical_only=True)
        self.assertEqual(result[0]['verdict'], 'fail')
        self.assertIn('contradicted_item_limit', result[0]['lexical_errors'])

    async def test_objective_receipt_and_stop_request_survive_collection(self):
        collected = await graph._extract_info_from_message(FIRST, {}, ExtractorStub({
            'basic_info': {'objective': '新媒体运营'}}))
        self.assertEqual(collected['basic_info']['objective'], '新媒体运营')
        self.assertFalse(any('我想投新媒体运营' in note for note in collected.get('verification_notes', [])))
        stopped = await graph._extract_info_from_message('不用问了', collected, ExtractorStub({}))
        self.assertTrue(stopped['no_more_questions'])
        self.assertTrue(graph._no_more_questions({'collected_info': stopped, 'messages': [HumanMessage(content='再润色一下')]}))

    async def test_semantic_failure_and_wrong_citations_cannot_prove_coverage(self):
        fact = new_fact('归类用户意见', kind='action')
        source = {'projects': [{'item_id': 'p', 'facts': [fact]}]}
        data = {'projects': [{'item_id': 'p', 'polished_bullets': ['整理客户反馈']}]}
        meta = {'bullets': {'p': [{'fact_ids': [fact['id']], 'text_hash': text_hash('整理客户反馈')}]}}
        with patch('app.services.fact_guard.verify_semantics', return_value={}):
            await cite_entailed_facts(data, meta, source, object(), item_ids=['p'])
        self.assertEqual(ensure_fact_coverage(data, meta, source)['covered'], 0)
        data['projects'][0]['polished_bullets'] = [fact['text']]
        meta['bullets']['p'] = [{'fact_ids': ['another-item'], 'text_hash': text_hash(fact['text'])}]
        self.assertEqual(ensure_fact_coverage(data, meta, source)['covered'], 0)

    def test_cropped_constraints_do_not_become_personal_actions(self):
        from app.agents.fact_extractor import _quote_has_unquoted_limit
        self.assertTrue(_quote_has_unquoted_limit('选题由部长定', '选题'))
        self.assertTrue(_quote_has_unquoted_limit('店长给文案', '文案'))

    async def test_semantic_entailment_is_directional_and_hash_bound(self):
        fact = new_fact('分类整理用户反馈', kind='action')
        data = {'projects': [{'item_id': 'p', 'polished_bullets': ['归类整理用户反馈']} ]}
        meta = {'bullets': {'p': [{'fact_ids': [fact['id']], 'text_hash': text_hash('归类整理用户反馈')}]}}
        source = {'projects': [{'item_id': 'p', 'facts': [fact]}]}
        async def semantic(pairs, *args, **kwargs):
            self.assertEqual(pairs[0]['text'], '分类整理用户反馈')
            self.assertEqual(pairs[0]['source_quotes'], ['归类整理用户反馈'])
            return {p['id']: {'verdict': 'pass'} for p in pairs}
        with patch('app.services.fact_guard.verify_semantics', semantic):
            await cite_entailed_facts(data, meta, source, object(), item_ids=['p'])
        self.assertIn(fact['id'], meta['bullets']['p'][0]['coverage_fact_ids'])
        data['projects'][0]['polished_bullets'] = ['整理材料']
        self.assertEqual(ensure_fact_coverage(data, meta, source)['covered'], 0)

    def test_gate_rules_notice_and_previous_no_question_request(self):
        self.assertIn('first_person', needs_polish('我拍摄视频素材'))
        self.assertIn('colloquial', needs_polish('帮店长做海报'))
        self.assertIn('short_fragment', needs_polish('做过'))
        self.assertIn('narrative_opening', needs_polish('兼职期间我拍摄视频素材'))
        self.assertIn('verbatim_source', needs_polish('整理订单记录', source_quotes=['整理订单记录']))
        self.assertIn('semantic_duplicate', needs_polish('拍过店里的短视频', siblings=[VIDEO]))
        self.assertEqual(needs_polish(GOOD), [])
        self.assertFalse(text_covered('拍摄6条短视频素材', ['拍摄2条短视频素材']))
        self.assertFalse(text_covered('撰写推文并回复用户评论', [GOOD]))
        self.assertEqual(coverage_notice({'facts': [{'status': 'omitted', 'text': '原文不要展开', 'reason': '篇幅'}]}),
                         '另有 1 条信息作为备用未放进这一版（可在右侧『核对』查看）。')
        state = {'messages': [HumanMessage(content='不用问了'), AIMessage(content='已收到'), HumanMessage(content='再润色一下')],
                 'collected_info': {'campus': [{'item_id': 'x', 'name': '校园经历（待补组织名）'}]}}
        result = graph._finish_followup_turn(state, {'stage': 'EVALUATING', 'messages': [AIMessage(content='已生成。\n需要你补充：组织名称是什么？')]})
        self.assertEqual(result['messages'][0].content, '已生成。')
