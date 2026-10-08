"""Regression for evidence-preserving rewrites, not verb blacklists."""
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.fact_guard import (extract_numbers, lexical_fact_errors, verify_semantics,
                                      guard_bullets, validate_skill_groups)


def decision(identifier='b1', passed=True, **extra):
    return {'id':identifier, 'subject_ok':True, 'actions_supported':passed, 'objects_supported':True,
            'results_supported':True, 'limits_kept':True, 'unsupported_spans':[],
            'verdict':'pass' if passed else 'fail', **extra}


class FakeModel:
    def __init__(self, answers):
        self.structured = SimpleNamespace(ainvoke=AsyncMock(return_value={'decisions':answers}))
    def with_structured_output(self, schema):
        return self.structured


def fact(text, identifier='f1', **extra):
    return {'id':identifier, 'text':text, 'source_quote':text, 'status':'active', **extra}


class FactGuardTests(unittest.IsolatedAsyncioTestCase):
    def test_numeric_equivalence_and_non_numeric_one(self):
        for source, target in [('十秒', '10秒'), ('两万条', '20000条'), ('百分之五十', '50%'), ('3千条', '3000条')]:
            with self.subTest(source=source):
                self.assertEqual(extract_numbers(source), extract_numbers(target))
        self.assertEqual(extract_numbers('做过一个项目，进一步优化一体化流程'), set())
        self.assertIn('1', extract_numbers('一等奖'))
        self.assertIn('20', extract_numbers('第二十届'))

    def test_lexical_red_lines_without_rejecting_improvement_synonym(self):
        self.assertEqual(lexical_fact_errors('效果提升', '效果变好了'), [])
        self.assertEqual(lexical_fact_errors('负责 Python 接口编写', '我写了 Python 接口'), [])
        for text, source in [('主导实现', '参与实现'), ('上线服务', '服务未上线'),
                             ('效果提升50%', '效果变好'), ('完成测试', '计划完成测试'),
                             ('开发系统', '开发原型系统')]:
            with self.subTest(text=text):
                self.assertTrue(lexical_fact_errors(text, source))
        self.assertEqual(lexical_fact_errors('使用 FastAPI 实现原型，未上线', '用 FastAPI 做原型，未上线'), [])

    async def test_positive_and_negative_semantic_cases_share_one_batch(self):
        pairs = [{'id':'good','text':'效果提升','source_quotes':['效果变好了']},
                 {'id':'action','text':'清理重复记录','source_quotes':['核对重复记录']},
                 {'id':'workflow','text':'搭建用户反馈流程','source_quotes':['将反馈分类']}]
        model = FakeModel([decision('good'), decision('action',False), decision('workflow',False)])
        result = await verify_semantics(pairs, model)
        self.assertEqual([result[key]['verdict'] for key in ['good','action','workflow']], ['pass','fail','fail'])
        self.assertEqual(model.structured.ainvoke.await_count, 1)
        prompt = model.structured.ainvoke.call_args.args[0][0].content
        self.assertIn('核对重复记录', prompt)
        self.assertIn('分类', prompt)

    async def test_missing_duplicate_and_contradictory_semantic_results_fail(self):
        pairs = [{'id':key,'text':'候选','source_quotes':['来源']} for key in ['missing','duplicate','contradictory']]
        model=FakeModel([decision('duplicate'),decision('duplicate'),decision('contradictory',results_supported=False)])
        checked=await verify_semantics(pairs,model)
        self.assertTrue(all(row['verdict']=='fail' for row in checked.values()))
        missing=await verify_semantics(pairs,None)
        self.assertTrue(all(row['verdict']=='fail' for row in missing.values()))

    async def test_semantic_messages_redact_contacts(self):
        model=FakeModel([decision()])
        await verify_semantics([{'id':'b1','text':'邮箱 person@example.test','source_quotes':['邮箱 person@example.test']}],model)
        messages=model.structured.ainvoke.call_args.args[0]
        self.assertNotIn('person@example.test',json.dumps([m.content for m in messages]))

    async def test_invalid_refs_cross_item_new_numbers_and_java_word_boundary(self):
        facts=[fact('使用 JavaScript 实现页面',item_id='p1'),fact('旧值','old',status='deleted')]
        bullets=[{'id':'inactive','text':'旧值','fact_ids':['old']},
                 {'id':'cross','item_id':'p2','text':'使用 JavaScript 实现页面','fact_ids':['f1']},
                 {'id':'tool','text':'使用 Java 实现页面','fact_ids':['f1']},
                 {'id':'metric','text':'使用 JavaScript 使转化率提升50%','fact_ids':['f1']},
                 {'id':'exact','text':'使用 JavaScript 实现页面','fact_ids':['f1']}]
        result=await guard_bullets(bullets,facts)
        self.assertEqual([row['verdict'] for row in result],['fail','fail','fail','fail','pass'])
        self.assertIn('unsupported_tool:Java',result[2]['lexical_errors'])
        self.assertEqual(validate_skill_groups({'开发':['JavaScript','Java']},facts),['Java'])

    async def test_missing_fact_ownership_cannot_be_assigned_to_an_item(self):
        result = await guard_bullets([{'id': 'b1', 'item_id': 'A', 'text': '设计原型界面', 'fact_ids': ['f1']}],
                                     [fact('设计原型界面')])
        self.assertEqual(result[0]['verdict'], 'fail')
        self.assertIn('wrong_experience_fact', result[0]['lexical_errors'])

    async def test_supported_rewording_uses_semantics_instead_of_exact_sentence_guard(self):
        model=FakeModel([decision()])
        result=await guard_bullets([{'id':'b1','text':'分类整理用户反馈','fact_ids':['f1']}],
                                   [fact('整理用户反馈，并按问题分类')],llm=model)
        self.assertEqual(result[0]['verdict'],'pass')
        self.assertIsNotNone(result[0]['semantic'])

    async def test_method_tool_fact_text_cannot_hide_weaker_original_quote(self):
        original = '训练用的是老师给的 PyTorch 代码'
        stronger = '本人完成模型训练与评估流程'
        model = FakeModel([decision('b1', False, subject_ok=False)])
        checked = await guard_bullets(
            [{'id': 'b1', 'item_id': 'p1', 'text': stronger, 'fact_ids': ['f1']}],
            [fact(stronger, item_id='p1', kind='method_tool', source_quote=original)], llm=model)
        self.assertEqual(checked[0]['verdict'], 'fail')
        self.assertEqual(model.structured.ainvoke.await_count, 1)
        payload = json.loads(model.structured.ainvoke.call_args.args[0][-1].content)
        self.assertEqual(payload[0]['source_quotes'], [original])
        self.assertEqual(payload[0]['source_facts'], [{
            'fact_id': 'f1', 'kind': 'method_tool', 'fact_text': stronger,
            'source_quote': original, 'quote_origin': 'original'}])

    async def test_original_quote_also_controls_lexical_limits(self):
        checked = await guard_bullets(
            [{'id': 'b1', 'item_id': 'p1', 'text': '主导上线产品', 'fact_ids': ['f1']}],
            [fact('主导上线产品', item_id='p1', kind='action', source_quote='参与原型，未上线')])
        self.assertEqual(checked[0]['verdict'], 'fail')
        self.assertIn('unsupported_responsibility_or_status:主导', checked[0]['lexical_errors'])
        self.assertIn('missing_negation_or_plan_limit', checked[0]['lexical_errors'])

    async def test_method_tool_with_explicit_first_person_action_remains_eligible(self):
        original = '我用老师提供的代码训练模型，并在验证集评估结果'
        model = FakeModel([decision('b1')])
        checked = await guard_bullets(
            [{'id': 'b1', 'item_id': 'p1', 'text': '使用老师代码完成训练与评估', 'fact_ids': ['f1']}],
            [fact('用老师代码训练和评估', item_id='p1', kind='method_tool', source_quote=original)], llm=model)
        self.assertEqual(checked[0]['verdict'], 'pass')
        self.assertEqual(checked[0]['lexical_errors'], [])
        payload = json.loads(model.structured.ainvoke.call_args.args[0][-1].content)
        self.assertEqual(payload[0]['source_facts'][0]['kind'], 'method_tool')
        self.assertEqual(payload[0]['source_facts'][0]['source_quote'], original)

    async def test_long_bullet_preserves_each_cited_kind_and_ambiguous_subject_fails(self):
        facts = [fact('课程小组做图像分类', 'project', item_id='p1', kind='context'),
                 fact('训练使用老师代码', 'tool', item_id='p1', kind='method_tool',
                      source_quote='训练用的是老师给的代码'),
                 fact('查看错分图片', 'action', item_id='p1', kind='action',
                      source_quote='我查看了预测错误的图片')]
        model = FakeModel([decision('b1', False, subject_ok=False)])
        checked = await guard_bullets(
            [{'id': 'b1', 'item_id': 'p1', 'text': '本人完成训练与评估流程，并查看错分图片',
              'fact_ids': ['project', 'tool', 'action']}], facts, llm=model)
        self.assertEqual(checked[0]['verdict'], 'fail')
        payload = json.loads(model.structured.ainvoke.call_args.args[0][-1].content)
        self.assertEqual([row['kind'] for row in payload[0]['source_facts']],
                         ['context', 'method_tool', 'action'])
        self.assertEqual(payload[0]['source_quotes'][1], '训练用的是老师给的代码')
        prompt = model.structured.ainvoke.call_args.args[0][0].content
        self.assertIn('逐子句核对', prompt)
        self.assertIn('项目/团队做过某事，不自动等于本人做过', prompt)

    async def test_missing_metric_is_not_evidence_of_no_quantitative_analysis(self):
        source = '我查看错分图片，发现模糊图片更容易出错；项目没有部署'
        explicit = '我查看错分图片，没有做量化统计；项目没有部署'
        model = FakeModel([
            decision('unstated', False, results_supported=False,
                     unsupported_spans=['未做量化统计']),
            decision('explicit'),
            decision('unrelated', False, results_supported=False,
                     unsupported_spans=['未测试']),
        ])
        checked = await guard_bullets([
            {'id': 'unstated', 'item_id': 'p1', 'text': '查看错分图片，未做量化统计；项目没有部署',
             'fact_ids': ['observed']},
            {'id': 'explicit', 'item_id': 'p1', 'text': '查看错分图片，未做量化统计；项目没有部署',
             'fact_ids': ['stated']},
            {'id': 'unrelated', 'item_id': 'p1', 'text': '项目未测试', 'fact_ids': ['observed']},
        ], [fact(source, 'observed', item_id='p1', kind='result_qualitative'),
            fact(explicit, 'stated', item_id='p1', kind='status_limit')], llm=model)
        self.assertEqual([row['verdict'] for row in checked], ['fail', 'pass', 'fail'])
        self.assertEqual(model.structured.ainvoke.await_count, 1)
        payload = json.loads(model.structured.ainvoke.call_args.args[0][-1].content)
        self.assertEqual(payload[0]['source_quotes'], [source])
        self.assertEqual(payload[1]['source_quotes'], [explicit])
        prompt = model.structured.ainvoke.call_args.args[0][0].content
        self.assertIn('否定断言也必须逐项有原文支持', prompt)
        self.assertIn('没有部署”不等于“未测试”或“未统计', prompt)

    async def test_observing_fields_does_not_establish_diagnosed_mismatch(self):
        observed = '我使用浏览器开发者工具查看请求返回，配合队友核对列表字段'
        diagnosed = '我使用浏览器开发者工具查看请求返回，和队友排查了列表字段与接口返回不一致的问题'
        model = FakeModel([
            decision('added_issue', False, actions_supported=False, objects_supported=False,
                     unsupported_spans=['排查列表数据与接口不一致的问题']),
            decision('same_actions'),
            decision('explicit_issue'),
        ])
        checked = await guard_bullets([
            {'id': 'added_issue', 'item_id': 'p1',
             'text': '查看请求返回，核对列表字段，排查列表数据与接口不一致的问题',
             'fact_ids': ['observed']},
            {'id': 'same_actions', 'item_id': 'p1',
             'text': '查看请求返回并与队友核对列表字段', 'fact_ids': ['observed']},
            {'id': 'explicit_issue', 'item_id': 'p1',
             'text': '配合队友排查列表与接口字段不一致', 'fact_ids': ['diagnosed']},
        ], [fact(observed, 'observed', item_id='p1', kind='action'),
            fact(diagnosed, 'diagnosed', item_id='p1', kind='action')], llm=model)
        self.assertEqual([row['verdict'] for row in checked], ['fail', 'pass', 'pass'])
        self.assertEqual(model.structured.ainvoke.await_count, 1)
        payload = json.loads(model.structured.ainvoke.call_args.args[0][-1].content)
        self.assertEqual([row['source_quotes'] for row in payload],
                         [[observed], [observed], [diagnosed]])
        prompt = model.structured.ainvoke.call_args.args[0][0].content
        self.assertIn('观察和诊断也要分开核对', prompt)
        self.assertIn('“问题”一词本身不是禁词', prompt)

    def test_negative_and_future_mentions_do_not_establish_skills(self):
        for quote in ['未使用 Kubernetes，仅完成 Python 原型', '计划使用 Kubernetes',
                      'Kubernetes 尚未使用', 'Kubernetes 准备学习',
                      'I have never used Kubernetes', 'Kubernetes is not familiar to me',
                      'I plan to learn Kubernetes']:
            with self.subTest(quote=quote):
                self.assertEqual(validate_skill_groups({'技术': ['Kubernetes']}, [fact(quote)]), ['Kubernetes'])

    def test_skill_limits_are_scoped_to_the_tool_clause(self):
        for quote in ['不会 K8s，但会 Python', '不会 K8s 与会 Python',
                      'K8s 尚未使用，Python 用过', '会 Python，不会 K8s',
                      'I do not know K8s but I know Python',
                      'I do not know K8s and know Python']:
            with self.subTest(quote=quote):
                self.assertEqual(validate_skill_groups({'技术': ['K8s', 'Python']}, [fact(quote)]), ['K8s'])
        self.assertEqual(validate_skill_groups({'技术': ['Python', 'FastAPI']},
                                               [fact('未上线的原型使用 Python 和 FastAPI 实现')]), [])
        self.assertEqual(validate_skill_groups({'技术': ['Kubernetes', 'Docker']},
                                               [fact('未使用 Kubernetes 和 Docker')]), ['Kubernetes', 'Docker'])

    def test_skill_source_quote_and_active_status_are_authoritative(self):
        skills = [{'name': 'Kubernetes', 'source_quote': '计划学习 Kubernetes'},
                  {'name': 'Docker', 'source_quote': '使用 Docker', 'status': 'deleted'},
                  {'name': 'Python', 'source_quote': '使用 Python 实现接口', 'status': 'active'}]
        facts = [fact('熟悉 Java', source_quote='未使用 Java'),
                 fact('使用 Redis', 'old', status='superseded')]
        self.assertEqual(validate_skill_groups({'技术': ['Kubernetes', 'Docker', 'Python', 'Java', 'Redis']}, facts, skills),
                         ['Kubernetes', 'Docker', 'Java', 'Redis'])
        self.assertEqual(validate_skill_groups({'技术': ['Python']}, [], ['Python']), [])

    async def test_guard_known_tools_cannot_borrow_negative_or_deleted_evidence(self):
        model = FakeModel([decision()])
        result = await guard_bullets(
            [{'id': 'b1', 'text': '使用 Kubernetes 和 Docker 实现接口', 'fact_ids': ['f1']}],
            [fact('实现接口'), fact('未使用 Kubernetes', 'f2')],
            user_skills=[{'name': 'Docker', 'source_quote': '使用 Docker', 'status': 'deleted'}], llm=model)
        self.assertIn('unsupported_tool:Kubernetes', result[0]['lexical_errors'])
        self.assertIn('unsupported_tool:Docker', result[0]['lexical_errors'])
        self.assertEqual(model.structured.ainvoke.await_count, 0)

    async def test_guard_can_preserve_a_negative_tool_statement(self):
        quote = '未使用 Kubernetes，仅完成 Python 原型'
        result = await guard_bullets([{'text': quote, 'fact_ids': ['f1']}], [fact(quote)])
        self.assertEqual(result[0]['verdict'], 'pass')

    async def test_exact_one_of_multiple_citations_cannot_bypass_limit_review(self):
        facts = [fact('实现接口', item_id='p1'),
                 fact('仅供内部验证', 'limit', item_id='p1', kind='status_limit')]
        bullets = [{'id': 'single', 'text': '实现接口', 'fact_ids': ['f1']},
                   {'id': 'multi', 'text': '实现接口', 'fact_ids': ['f1', 'limit']}]
        model = FakeModel([decision('multi', limits_kept=False)])
        checked = await guard_bullets(bullets, facts, llm=model)
        self.assertEqual([row['verdict'] for row in checked], ['pass', 'fail'])
        self.assertIsNone(checked[0]['semantic'])
        self.assertFalse(checked[1]['semantic']['limits_kept'])
        self.assertEqual(model.structured.ainvoke.await_count, 1)
        prompt = str(model.structured.ainvoke.call_args.args[0])
        self.assertIn('仅供内部验证', prompt)
        unavailable = await guard_bullets(bullets, facts)
        self.assertEqual([row['verdict'] for row in unavailable], ['pass', 'fail'])


if __name__ == '__main__':
    unittest.main()
