"""Batch 11d: partial delivery filtering, first-draft boundaries and metric dedupe."""
# ruff: noqa: E402 -- application imports require the repository backend path.
import json
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import test_batch11_comparison_case as batch11
from test_batch11_comparison_case import graph, TechReplayWriter
from test_campus_and_naming import semantic_stub
from langchain_core.messages import AIMessage
from app.agents.resume_writer import run_resume_writer, _missing_metric_facts, _append_metric_bullets
from app.schemas.writer import WrittenItem, WrittenBullet
from app.services.resume_delivery import guard_delivery, presents_resume_body
from app.services.resume_facts import new_fact
from app.services.resume_versions import text_hash
from app.services.skill_groups import normalize_skill_groups

# Frozen model reply from after-batch10c/career/01-initial.reply.txt.
CAREER = """先说结论：你的行政经历里有 3 块能往 SaaS 客户成功上迁移，但都不是"客户成功"本身，只能按行政口径写。缺的那块（客户问题记录）正好是最接近 CS 的一环，我需要确认一个事实再定稿。

## 一、能迁移的（现有事实够写）

| 你做过的事 | 迁移到什么能力 |
| --- | --- |
| 每月约 30 份报销材料，核对发票与审批单 | 逐条核对、口径一致性、按流程交件——CS 日常对账单/工单信息的核对习惯 |
| 维护 120 人员工通讯录 | 结构化信息维护，多人数据的准确性责任 |
| 协助组织 6 场培训：报名表、场地、签到 | 活动/项目的多方协调与执行落地——CS 的客户培训、上线支持是同类型执行 |
| 接待访客，记录客户问题并转交业务同事 | 一线接待 + 问题记录 + 内部转交，这是最靠近客户成功的一条 |
| Excel / Word / PPT | 台账、清单、汇报材料的载体 |

## 二、还缺证据的（不要硬写）

- 客户问题的**记录载体和闭环**：现在是"记录后转交"，没有台账、没有跟进结果，写不出"跟踪至解决"。
- **产品侧**：没有 SaaS/软件产品使用经验，没有 CRM（你明确没用过），不写。
- **客户指标**：无续费、留存、满意度、健康度任何数据，也不写服务多少客户。
- **量级**：访客/客户问题的数量你没有，暂不写数字。

## 三、已有经历的改法（草稿，请你核对）

**启明商贸 | 全职行政助理 | 2024.07—2026.09**
- 每月整理约 30 份报销材料，逐份核对发票与审批单后提交
- 维护 120 人员工通讯录
- 协助组织 6 场内部培训：负责报名表制作、场地协调与现场签到
- 接待访客，将客户问题记录后转交业务同事

**南川大学 | 工商管理 本科 | 2020.09—2024.06**

技能：Excel、Word、PPT

改动说明：只做了压缩和动词明确化——"负责报名表制作、场地协调与现场签到"来自你原话，"协助组织"保留在句首不升级；审批权限那条按规则不进正文。

## 四、要你确认的一个问题

你接待访客时记录的客户问题——是随手转达，还是留下了可以回看的记录？

这条决定了第四条 bullet 是"记录后转交"，还是能写成"建立客户问题记录表，按类型整理后转交"。有记录表的话，我立刻改稿；没有，我就保持现在的写法，不给你编一个。"""
SAVED = {'work_experience': [{'company': '启明商贸', 'bullets': ['维护员工通讯录']}]}


class DeliveryTest(unittest.IsolatedAsyncioTestCase):
    def test_only_draft_block_is_removed(self):
        for data, saved, receipt in ((SAVED, True, '草稿已放到右侧「写简历」'),
                                     (SAVED, False, '本轮尚未保存更新版'), ({}, False, '本轮尚未生成并保存')):
            result = guard_delivery(CAREER, data, saved_this_turn=saved)
            self.assertEqual(result.split('## 三、')[0] if '## 三、' in result else result.split(receipt)[0],
                             CAREER.split('## 三、')[0])
            self.assertIn('## 一、能迁移的', result)
            self.assertIn('## 二、还缺证据的', result)
            self.assertIn('改动说明：只做了压缩', result)
            self.assertIn('## 四、要你确认的一个问题', result)
            self.assertNotIn('**启明商贸 |', result)
            self.assertNotIn('**南川大学 |', result)
            self.assertEqual(result.count(receipt), 1)

    def test_analysis_headings_and_lists_are_not_body(self):
        analysis = CAREER.split('## 三、')[0] + CAREER.split('## 四、')[1]
        for text in (analysis, '# 能迁移的\n- 信息核对\n- 协调与执行\n',
                     '## 工作经历\n缺少客户问题闭环。\n## 技能\n- 应补充产品使用证据。',
                     '\n'.join('- ' + '完成用户访谈与原型改版并核对结果' * 3 for _ in range(5))):
            self.assertFalse(presents_resume_body(text))
            self.assertEqual(guard_delivery(text, SAVED, saved_this_turn=True), text)

    def test_named_resume_with_spaced_sections_keeps_followup(self):
        text = '# 林知夏\n## 项目经历\n\n- 访谈18名同学\n\n## 技能\n\nSQL基础查询\n\n## 要确认的问题\n是否有访谈记录？'
        result = guard_delivery(text, SAVED, saved_this_turn=True)
        self.assertTrue(presents_resume_body(text))
        self.assertNotIn('18名', result)
        self.assertNotIn('SQL基础查询', result)
        self.assertIn('## 要确认的问题\n是否有访谈记录？', result)

    def test_late_plain_header_finishes_immutable_line_before_receipt(self):
        text = '启明商贸 | 行政助理 | 2024.07—2026.09\n- 维护120人通讯录\n'
        result = guard_delivery(text, SAVED, saved_this_turn=True, preserve_prefix=2)
        self.assertTrue(result.startswith(text.split('\n')[0] + '\n'))
        self.assertNotIn('120', result)
        self.assertIn('草稿已放到右侧', result)

    async def test_chunked_reply_and_history_equal_guarded_reply(self):
        expected = guard_delivery(CAREER, SAVED, saved_this_turn=True)
        for width in (1, 2, 7, 53, len(CAREER)):
            with self.subTest(width=width):
                values = {**graph._init_state(), 'resume_data': SAVED,
                          'messages': [AIMessage(id='reply', content=CAREER)]}
                async def events(*args, **kwargs):
                    for offset in range(0, len(CAREER), width):
                        yield 'custom', {'type': 'public_reply_delta', 'node': 'collecting',
                                         'reply_id': 'reply', 'content': CAREER[offset:offset + width]}
                    yield 'updates', {'collecting': {'messages': values['messages']}}
                fake = SimpleNamespace(astream=events,
                    aget_state=AsyncMock(return_value=SimpleNamespace(values=values)), aupdate_state=AsyncMock())
                with patch.object(graph, 'get_graph', return_value=fake), \
                        patch('app.services.session_store.save_resume_session', return_value={'resume_data': SAVED, 'resume_meta': {}}), \
                        patch('app.services.conversation_store.update_conversation_title'):
                    chunks = [s async for s in graph.stream_agent([{'content': '说明哪些能力能迁移、哪些证据还缺'}], '11d-career', object())]
                self.assertEqual(''.join(chunks), expected)
                repaired = [m.content for call in fake.aupdate_state.call_args_list for m in call.args[1].get('messages', [])]
                self.assertIn(expected, repaired)


class OmitBoundaryWriter(TechReplayWriter):
    async def invoke(self, schema, messages):
        result = await super().invoke(schema, messages)
        for item in result.get('items', []):
            if item['section'] == 'projects':
                item['bullets'] = item['bullets'][:1]
            else:
                evidence = json.loads(messages[-1].content)['evidence']['work_experience'][0]['facts']
                metric = next(f['id'] for f in evidence if '420' in f['text'])
                item['bullets'][1]['text'] += '，平均耗时由约 420ms 降至约 170ms'
                item['bullets'][1]['fact_ids'].append(metric)
        return result


class FirstDraftTest(unittest.IsolatedAsyncioTestCase):
    def test_mixed_role_retains_identity_and_moves_duties_to_body(self):
        from app.services.resume_limits import preserve_item_limits
        fact = {**new_fact('后端开发参与者，负责商品发布和搜索接口，登录模块由另一位同学编写', kind='role'), 'field': 'role'}
        source = {'projects': [{'item_id': 'p', 'name': '校园二手交易系统', 'facts': [fact]}]}
        initial = graph._serialize_to_resume_data({'collected_info': source})['projects'][0]
        self.assertEqual(initial['role'], '后端开发参与者')
        self.assertNotIn('后端开发参与者', initial['description'])
        for duty in ('负责商品发布和搜索接口', '登录模块由另一位同学编写'):
            self.assertIn(duty, initial['description'])
        data = {'projects': [{**initial, 'polished_bullets': ['使用 Spring Boot、MySQL']}]}
        result, meta, _ = preserve_item_limits(data, {}, source, item_ids=['p'])
        text = result['projects'][0]['polished_bullets'][0]
        self.assertNotIn('后端开发参与者', text)
        self.assertIn('负责商品发布和搜索接口', text)
        self.assertIn('登录模块由另一位同学编写', text)
        self.assertEqual(meta['bullets']['p'][0]['text_hash'], text_hash(text))

    def test_relocated_duties_and_boundary_survive_full_first_draft_budget(self):
        from app.services.resume_limits import preserve_item_limits
        facts = [{**new_fact('负责商品发布和搜索接口', kind='role'), 'field': 'role'},
                 {**new_fact('登录模块由另一位同学编写', kind='role'), 'field': 'role'}]
        source = {'projects': [{'item_id': 'p', 'name': '校园二手交易系统', 'facts': facts}]}
        data = {'projects': [{'item_id': 'p', 'name': '校园二手交易系统', 'role': facts[0]['text'],
                             'polished_bullets': ['使用 Spring Boot、MySQL']} ]}
        result, meta, _ = preserve_item_limits(data, {}, source, item_ids=['p'])
        project = result['projects'][0]
        self.assertEqual(project['role'], '')
        self.assertEqual(len(project['polished_bullets']), 1)
        for fact in facts:
            self.assertIn(fact['text'], project['polished_bullets'][0])
            self.assertIn(fact['id'], meta['bullets']['p'][0]['fact_ids'])
        again, _, _ = preserve_item_limits(result, meta, source, item_ids=['p'])
        self.assertEqual(again, result)

    def test_replayed_duplicate_metric_removal_retains_independent_facts(self):
        from app.agents.resume_writer import _without_near_duplicate_rows
        metric = new_fact('慢查询平均耗时由约 420ms 降到约 170ms', kind='result_metric')
        tests = new_fact('编写了12条接口测试用例')
        rows = [{'item_id': 'w', 'text': '在测试环境对慢查询加联合索引，平均耗时由约 420ms 降至约 170ms，没做线上压测',
                 'fact_ids': [metric['id']]},
                {'item_id': 'w', 'text': '慢查询平均耗时由约 420ms 降到约 170ms；编写了12条接口测试用例，在导师指导下给订单列表加了 Redis 缓存',
                 'fact_ids': [metric['id'], tests['id']]}]
        result = _without_near_duplicate_rows(rows, {f['id']: f for f in (metric, tests)})
        text = ' '.join(r['text'] for r in result)
        self.assertEqual(text.count('420'), 1, text)
        self.assertEqual(text.count('170'), 1, text)
        for value in ('12条接口测试用例', 'Redis', '导师指导下', '测试环境', '没做线上压测'):
            self.assertIn(value, text)
        self.assertNotIn(metric['id'], result[1]['fact_ids'])
        self.assertIn(tests['id'], result[1]['fact_ids'])
        self.assertEqual(_without_near_duplicate_rows(result, {f['id']: f for f in (metric, tests)}), result)

    async def test_missing_boundary_returns_in_first_draft_and_metric_once(self):
        source = await batch11.Batch11cTechTest.source(self)
        login = next(f for f in source['projects'][0]['facts'] if '登录模块' in f['text'])
        login.update(kind='role', field='role')
        original = deepcopy(source)
        current = graph._serialize_to_resume_data({'collected_info': source})
        self.assertRegex(current['projects'][0]['description'], '登录模块.*同学')
        plan = {'requirements': [], 'experience_plan': [
            {'item_id': item['item_id'], 'treatment': 'keep', 'target_bullets': 2 if sec == 'projects' else 3}
            for sec in ('work_experience', 'internship', 'projects') for item in source.get(sec, [])]}
        with patch('app.services.fact_guard.verify_semantics', side_effect=semantic_stub):
            result = await run_resume_writer(source, {}, OmitBoundaryWriter(), current_data=current,
                previous_plan=plan, phase='write', constraints={'preserve_explicit_limits': True}, instruction='直接成稿')
        project = result['resume_data']['projects'][0]
        self.assertNotRegex(project['role'], '登录|负责|同学')
        self.assertRegex(' '.join(project['polished_bullets']), '登录模块.*同学')
        work = result['resume_data']['work_experience'][0]
        body = ' '.join(work['bullets'])
        self.assertEqual(body.count('420'), 1, body)
        self.assertEqual(body.count('170'), 1, body)
        self.assertIn('12', body)
        self.assertIn('Redis', body)
        self.assertIn('测试环境', body)
        self.assertIn('线上压测', body)
        for item, field in ((project, 'polished_bullets'), (work, 'bullets')):
            records = result['resume_meta']['bullets'][item['item_id']]
            self.assertEqual([r['text_hash'] for r in records], [text_hash(t) for t in item[field]])
        self.assertEqual(source, original)

    def test_metric_fallback_recognizes_existing_numbers_without_duplicate_citation(self):
        metric = new_fact('慢查询平均耗时由约 420ms 降到约 170ms', kind='result_metric')
        action = new_fact('在测试环境对慢查询加联合索引')
        written = WrittenItem(item_id='w', section='work_experience', bullets=[WrittenBullet(
            text='在测试环境对慢查询加联合索引，平均耗时由约 420ms 降至约 170ms，没做线上压测',
            fact_ids=[action['id']])])
        writers, items = {'w': written}, {'w': ('work_experience', {'facts': [action, metric]})}
        self.assertEqual(_missing_metric_facts(writers, items, {'w': 'keep'}, {'w': 3}), {})
        self.assertIn(metric['id'], written.bullets[0].fact_ids)
        _append_metric_bullets(writers, items, {'w': [metric['id']]}, {'w': 3})
        self.assertEqual(len(written.bullets), 1)
        self.assertEqual(written.bullets[0].text.count('420'), 1)

    def test_metric_equivalence_keeps_distinct_objects_and_scopes(self):
        from app.services.fact_coverage import text_covered
        wanted = '慢查询平均耗时由约 420ms 降到约 170ms'
        self.assertTrue(text_covered(wanted, ['对慢查询加联合索引，平均耗时由约 420ms 降至约 170ms']))
        for other in ('页面加载平均耗时由约 420ms 降到约 170ms',
                      '慢查询平均耗时由约 170ms 降到约 420ms',
                      '计划将慢查询平均耗时由约 420ms 降至约 170ms'):
            self.assertFalse(text_covered(wanted, [other]), other)

    def test_ai_skill_dedupe_keeps_specific_original_in_either_order(self):
        short, original = 'Agent工具调用与RAG（了解）', '了解Agent工具调用与RAG基本流程'
        for extra in ([short, original], [original, short]):
            groups = normalize_skill_groups({'AI 与 Agent': [short]}, extra)
            self.assertEqual(groups['AI 与 Agent'], [original])
        groups = normalize_skill_groups({'AI 与 Agent': [short, original]})
        self.assertEqual(groups['AI 与 Agent'], [original])
