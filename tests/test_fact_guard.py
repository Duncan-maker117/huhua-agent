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


if __name__ == '__main__':
    unittest.main()
