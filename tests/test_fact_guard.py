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
    def test_course_project_and_feedback_do_not_establish_team_project(self):
        for source in ['我参加过课程项目，问过同学，也画了提交和确认流程',
                       'I built a course project and asked classmates for feedback']:
            with self.subTest(source=source):
                self.assertIn('unsupported_team_project_context',
                              lexical_fact_errors('课程团队项目', source))
        for source in ['课程小组共同完成项目', '我和同学一起设计项目',
                       '我与同学开发页面', '队友负责后端，我画原型', 'We built a team project',
                       '同学们一起设计项目', '我们开发课程项目', 'We developed this project as a group']:
            with self.subTest(source=source):
                self.assertNotIn('unsupported_team_project_context',
                                 lexical_fact_errors('团队项目', source))

    async def test_team_marker_does_not_bypass_subject_semantic_check(self):
        model = FakeModel([decision('b1', False, subject_ok=False,
                                    unsupported_spans=['团队项目'])])
        checked = await guard_bullets([{'id': 'b1', 'text': '团队项目', 'fact_ids': ['f1']}],
                                     [fact('这是独立项目，参考过其他团队的方案')], llm=model)
        self.assertEqual(checked[0]['lexical_errors'], [])
        self.assertEqual(checked[0]['verdict'], 'fail')
        self.assertEqual(model.structured.ainvoke.await_count, 1)

    async def test_empty_result_ui_label_is_not_a_negative_experience_limit(self):
        source = '我还补了加载中、没结果和请求失败的界面'
        model = FakeModel([decision()])
        checked = await guard_bullets(
            [{'id': 'b1', 'text': '补充加载、空结果和请求失败界面', 'fact_ids': ['f1']}],
            [fact(source)], llm=model)
        self.assertEqual(checked[0]['lexical_errors'], [])
        self.assertEqual(checked[0]['verdict'], 'pass')
        self.assertEqual(model.structured.ainvoke.await_count, 1)

    def test_empty_state_label_does_not_erase_actual_negative_work_status(self):
        for source in ['我设计了没结果界面，网站没上线', '我没开发空结果页面',
                       '我设计页面但没有结果', '我处理请求没有结果',
                       '处理请求失败提示，但没有增长结果', '项目没有结果']:
            with self.subTest(source=source):
                self.assertNotIn('missing_negation_or_plan_limit',
                                 lexical_fact_errors('设计结果页面', source))

    async def test_undisclosed_negative_measurement_cannot_pass_semantic_approval(self):
        model = FakeModel([decision()])
        checked = await guard_bullets(
            [{'id': 'b1', 'item_id': 'p1',
              'text': '查看错分图片并调整输入尺寸后重跑，未做量化统计',
              'fact_ids': ['observed']}],
            [fact('我看了错分图片，调整了输入尺寸并重跑，还记录了变化',
                  'observed', item_id='p1', kind='action')], llm=model)
        self.assertEqual(checked[0]['verdict'], 'fail')
        self.assertIn('unsupported_negative_measurement_status', checked[0]['lexical_errors'])
        self.assertEqual(model.structured.ainvoke.await_count, 0)

    def test_negative_measurement_needs_work_status_not_missing_report_or_other_limit(self):
        for source in ['项目没有部署，我查看了错例', '没有提供准确率数字',
                       '没有量化结果记录', '我做过准确率统计，但没有在简历中写数值',
                       '统计做过，但没有统计报告可提供', '没有统计数据', '没有量化统计报告',
                       '统计做过，但没有统计的报告', '没有量化分析的记录', '没有统计学知识',
                       '并非只做了定性分析', '不是仅仅做了定性观察',
                       '我不只做了定性分析，也做了量化分析', '我不仅做了定性分析，也做了量化分析',
                       'I reviewed errors but did not deploy the model']:
            for claim in ['未做量化统计', '尚未开展定量评估', '没有进行统计',
                          'Did not conduct quantitative analysis']:
                with self.subTest(source=source, claim=claim):
                    self.assertIn('unsupported_negative_measurement_status',
                                  lexical_fact_errors(claim, source))

    def test_explicit_measurement_limits_remain_semantically_reviewable(self):
        for source in ['没有做过量化统计', '未统计准确率', '尚未开展定量评估',
                       '没有做过任何量化统计', '只做了定性分析',
                       'No quantitative analysis was performed',
                       'I have not conducted a quantitative analysis',
                       'I have not performed quantitative analysis']:
            with self.subTest(source=source):
                self.assertNotIn('unsupported_negative_measurement_status',
                                 lexical_fact_errors('未做量化统计', source))
        self.assertNotIn('unsupported_negative_measurement_status',
                         lexical_fact_errors('并非未统计，已统计准确率', '已统计准确率'))

    async def test_measurement_limit_must_belong_to_same_object(self):
        model = FakeModel([decision('b1', False, results_supported=False,
                                    unsupported_spans=['模型A未做量化统计'])])
        checked = await guard_bullets(
            [{'id': 'b1', 'text': '模型A未做量化统计', 'fact_ids': ['f1']}],
            [fact('模型A已统计准确率，模型B未做量化统计')], llm=model)
        self.assertEqual(checked[0]['lexical_errors'], [])
        self.assertEqual(checked[0]['verdict'], 'fail')
        self.assertEqual(model.structured.ainvoke.await_count, 1)

    async def test_source_quote_overrides_extractor_added_negative_measurement(self):
        checked = await guard_bullets(
            [{'text': '查看错例，未做量化统计', 'fact_ids': ['f1']}],
            [fact('查看错例，未做量化统计', source_quote='查看错例并记录变化')])
        self.assertIn('unsupported_negative_measurement_status', checked[0]['lexical_errors'])

    async def test_prototype_does_not_prove_unreleased_status(self):
        model = FakeModel([decision()])
        checked = await guard_bullets(
            [{'id': 'b1', 'text': '实现页面原型，尚未上线', 'fact_ids': ['f1']}],
            [fact('实现页面原型')], llm=model)
        self.assertIn('unsupported_negative_release_status', checked[0]['lexical_errors'])
        self.assertEqual(checked[0]['verdict'], 'fail')
        self.assertEqual(model.structured.ainvoke.await_count, 0)

    def test_unreleased_status_requires_source_even_with_other_limits(self):
        for quote, text in [
            ('实现页面原型，未做量化统计', '实现页面原型，未上线且未做量化统计'),
            ('Built a prototype', 'Built a prototype, not deployed'),
            ('做了内部演示', '完成内部演示，未发布'),
        ]:
            with self.subTest(quote=quote):
                self.assertIn('unsupported_negative_release_status', lexical_fact_errors(text, quote))

    def test_explicit_unreleased_synonyms_remain_reviewable(self):
        for quote, text in [
            ('这是尚未上线的原型', '这是未上线原型'),
            ('原型还没有部署', '原型尚未上线'),
            ('Built a prototype, not yet deployed', 'Prototype has not been deployed'),
            ('The prototype has not yet been deployed', 'The prototype is not deployed'),
            ('The prototype has not yet been deployed', 'The prototype has not been deployed yet'),
            ('原型没有被部署', '原型尚未部署'),
            ('原型计划上线', '原型尚未上线'),
        ]:
            with self.subTest(quote=quote):
                self.assertNotIn('unsupported_negative_release_status', lexical_fact_errors(text, quote))

    def test_occasional_observation_cannot_become_frequent(self):
        self.assertIn('unsupported_frequency_upgrade', lexical_fact_errors(
            '报名条件与安排常混在一起，于是改写说明', '报名条件与安排有时混在一起，于是改写说明'))
        for text in ['偶尔发现条件与安排混在一起', '有时发现条件与安排混在一起',
                     '有时发现异常，随后检查正常页面']:
            self.assertNotIn('unsupported_frequency_upgrade', lexical_fact_errors(text, '有时发现问题'))
        self.assertNotIn('unsupported_frequency_upgrade', lexical_fact_errors(
            '经常核对报名条件', '经常核对报名条件'))
        self.assertNotIn('unsupported_frequency_upgrade', lexical_fact_errors(
            '我有时检查平常的运行记录', '我有时检查日常运行记录'))
        self.assertNotIn('unsupported_frequency_upgrade', lexical_fact_errors(
            '有时观察到故障，服务一直在线', '有时观察到故障，服务长期在线'))

    async def test_release_markers_do_not_skip_object_and_version_review(self):
        for source, target in [
            ('后端未部署，前端已上线', '前端未上线'),
            ('项目已经上线，计划上线下一版本', '项目尚未上线'),
        ]:
            model = FakeModel([decision(passed=False, objects_supported=False)])
            checked = await guard_bullets([{'id': 'b1', 'text': target, 'fact_ids': ['f1']}],
                                          [fact(source)], llm=model)
            self.assertEqual(checked[0]['verdict'], 'fail')
            # 「未上线」印进正文本身就是缺失型表述缺陷，词法层先拦；否则必须走语义核验。
            self.assertTrue('negative_absence_printed' in checked[0]['lexical_errors']
                            or model.structured.ainvoke.await_count == 1)

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
                             ('效果提升50%', '效果变好'), ('完成测试', '计划完成测试')]:
            with self.subTest(text=text):
                self.assertTrue(lexical_fact_errors(text, source))
        self.assertEqual(lexical_fact_errors('开发系统', '开发原型系统'), [])
        self.assertEqual(lexical_fact_errors('使用 FastAPI 实现原型', '用 FastAPI 做原型，未上线'), [])


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
        self.assertIn('contradicted_status_limit', checked[0]['lexical_errors'])
        self.assertNotIn('missing_negation_or_plan_limit', checked[0]['lexical_errors'])

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
            {'id': 'unstated', 'item_id': 'p1', 'text': '查看错分图片，未做量化统计',
             'fact_ids': ['observed']},
            {'id': 'explicit', 'item_id': 'p1', 'text': '查看错分图片，未做量化统计',
             'fact_ids': ['stated']},
            {'id': 'unrelated', 'item_id': 'p1', 'text': '项目未测试', 'fact_ids': ['observed']},
        ], [fact(source, 'observed', item_id='p1', kind='result_qualitative'),
            fact(explicit, 'stated', item_id='p1', kind='status_limit')], llm=model)
        self.assertEqual([row['verdict'] for row in checked], ['fail', 'pass', 'fail'])
        self.assertEqual(model.structured.ainvoke.await_count, 1)
        payload = json.loads(model.structured.ainvoke.call_args.args[0][-1].content)
        self.assertEqual([row['id'] for row in payload], ['explicit', 'unrelated'])
        self.assertEqual(payload[0]['source_quotes'], [explicit])
        self.assertEqual(payload[1]['source_quotes'], [source])
        self.assertIn('unsupported_negative_measurement_status', checked[0]['lexical_errors'])
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


CASES = Path(__file__).resolve().parents[1] / 'evaluation' / 'tailor-bench' / 'cases'


def opening(case):
    return json.loads((CASES / f'{case}.json').read_text(encoding='utf-8'))['opening_turns'][0]


class ExpansionGuardTests(unittest.TestCase):
    def test_review_sentences_fail_closed(self):
        """PR5 v3 评审 Q2：六句新增事实/修饰，事实来源取用例开场原话。"""
        samples = [
            ("career-switch-01", "尝试用 GPT 对整理出的问题进行归类，减少人工逐条分组的工作", "unsupported_effect"),
            ("career-switch-01", "尝试用 GPT 对整理出的问题进行归类，减少人工逐条分组的工作", "unsupported_manner:逐条"),
            ("career-switch-01", "逐条人工检查分类结果", "unsupported_manner:逐条"),
            ("ops-01", "在活动前后收集参与者提出的问题", "unsupported_scope:活动前后"),
            ("pm-01", "梳理出清单对不上的具体场景", "unsupported_action:梳理出"),
            ("pm-01", "梳理出清单对不上的具体场景", "unsupported_scope:具体场景"),
            ("algorithm-01", "逐张查看预测错误的图片", "unsupported_manner:逐张"),
        ]
        for case, text, marker in samples:
            with self.subTest(case=case, text=text):
                errors = lexical_fact_errors(text, opening(case))
                self.assertIn(marker, errors)
                self.assertNotIn("missing_negation_or_plan_limit", errors)

    def test_faithful_rewrites_of_the_same_sources_still_pass(self):
        samples = [("career-switch-01", "用 GPT 对整理出的问题试分类，并人工检查"),
                   ("ops-01", "活动后把反馈按主题整理"),
                   ("pm-01", "访谈同学平时如何记录清单，并画出提交与确认流程"),
                   ("algorithm-01", "把预测错误的图片挑出来查看")]
        for case, text in samples:
            with self.subTest(case=case):
                errors = lexical_fact_errors(text, opening(case))
                self.assertFalse([e for e in errors if e.startswith("unsupported_")], errors)

    async def test_guard_bullets_rejects_review_sentences_without_the_model(self):
        model = FakeModel([])
        for case, text in [("ops-01", "在活动前后收集参与者提出的问题"), ("algorithm-01", "逐张查看错分图片")]:
            checked = await guard_bullets([{'id': 'b1', 'text': text, 'fact_ids': ['f1']}],
                                          [fact(opening(case))], llm=model)
            self.assertEqual(checked[0]['verdict'], 'fail', text)
        model.structured.ainvoke.assert_not_awaited()

    def test_semantic_contract_lists_new_effect_scope_action_and_manner_failures(self):
        from app.services.fact_guard import SEMANTIC_CONTRACT
        for phrase in ("减少人工逐条分组的工作", "在活动前后收集参与者提出的问题", "梳理出清单对不上的具体场景",
                       "逐张查看错分图片", "逐条人工检查分类结果", "新增成效", "新增范围", "新增动作",
                       "方式修饰", "频次修饰"):
            self.assertIn(phrase, SEMANTIC_CONTRACT)

    async def test_guard_bullets_flags_absence_printed_in_a_bullet(self):
        checked = await guard_bullets([{'id': 'b1', 'text': '使用 FastAPI 实现原型，未上线', 'fact_ids': ['f1']}],
                                      [fact('用 FastAPI 做原型，未上线')], llm=FakeModel([]))
        self.assertEqual(checked[0]['verdict'], 'fail')
        self.assertIn('negative_absence_printed', checked[0]['lexical_errors'])

    def test_absence_sentences_are_flagged_and_stripped(self):
        from app.services.fact_guard import absence_printed, strip_absence
        for text in ("还没上线", "没有用户量", "仓库公开，没有星数", "项目尚未上线", "没有统计阅读量"):
            self.assertTrue(absence_printed(text), text)
            self.assertNotIn("negative_absence_printed", lexical_fact_errors(text, text))  # 事实可以是缺失型
        self.assertFalse(absence_printed("实现接口并联调"))
        self.assertEqual(strip_absence("实现接口并联调。"), "实现接口并联调。")
        self.assertNotIn("没有用户量", strip_absence("先查候选店铺再编排行程；没有用户量"))

    def test_f2_frequency_and_purpose_additions_fail(self):
        samples = [
            ("此前主要做社团运营，长期接触群内同学的实际问题，现转向 AI 产品方向", opening("career-switch-01"), "unsupported_frequency_duration:长期"),
            ("使用 SQL 按商品和日期汇总模拟采购流水，将汇总结果导入表格，供小组后续分析使用",
             "我用 SQL 按商品和日期汇总采购流水，将汇总结果导入表格", "unsupported_purpose:供"),
            ("核对汇总结果中的疑似重复记录并标记，保留原始数据，供后续复核", "核对疑似重复的记录并作标记，没有删除原始数据", "unsupported_purpose:供"),
            ("用于验证效果", "我做了一个原型", "unsupported_purpose:用于"),
            ("为小组提供清单", "我整理了清单", "unsupported_purpose:提供"),
            ("多次修改提示", "我改了提示", "unsupported_frequency_duration:多次"),
        ]
        for text, source, marker in samples:
            with self.subTest(text=text):
                self.assertIn(marker, lexical_fact_errors(text, source))
        # 来源已有同样说法时放行（语义阶段仍会核对）
        self.assertEqual([e for e in lexical_fact_errors("供老师查看原型", "原型链接提交给老师，供老师查看")
                          if e.startswith("unsupported_purpose")], [])

    def test_f5_enumeration_count_is_a_synonym_not_a_new_number(self):
        source = "我用接口请求手动检查了正常借还、缺少编号和重复归还的情况"
        self.assertNotIn("unsupported_numbers", "".join(lexical_fact_errors("手动检查正常借还、缺少编号、重复归还三项情况", source)))
        self.assertIn("unsupported_numbers:3", lexical_fact_errors("手动检查三项情况", "我手动检查了几个情况"))


    async def test_f5_role_fact_of_the_same_item_supports_independent(self):
        facts = [{'id': 'f1', 'item_id': 'p1', 'kind': 'action', 'text': '做行程推荐', 'source_quote': '做行程推荐', 'status': 'active'},
                 {'id': 'f2', 'item_id': 'p1', 'kind': 'role', 'text': '途记基本是我一个人做的', 'source_quote': '途记基本是我一个人做的', 'status': 'active'}]
        checked = await guard_bullets([{'id': 'b1', 'item_id': 'p1', 'text': '独立完成行程推荐', 'fact_ids': ['f1']}],
                                      facts, llm=FakeModel([decision()]))
        self.assertNotIn('unsupported_responsibility_or_status:独立', checked[0]['lexical_errors'])
        other = [{**facts[0], 'item_id': 'p1'}, {**facts[1], 'item_id': 'p2'}]
        checked = await guard_bullets([{'id': 'b1', 'item_id': 'p1', 'text': '独立完成行程推荐', 'fact_ids': ['f1']}],
                                      other, llm=FakeModel([decision()]))
        self.assertIn('unsupported_responsibility_or_status:独立', checked[0]['lexical_errors'])

    def test_omitting_a_negation_is_allowed_and_reversing_it_is_not(self):
        self.assertNotIn("contradicted_status_limit", lexical_fact_errors("实现接口", "还没上线，没有用户量"))
        self.assertIn("contradicted_status_limit", lexical_fact_errors("项目已上线并有用户量增长", "还没上线，没有用户量"))


if __name__ == '__main__':
    unittest.main()


class E5Tests(unittest.TestCase):
    def test_result_upgrade_and_attribution_examples(self):
        errors = lexical_fact_errors("基于 SQLite 完成登记数据的读写，本地演示通过", "用 FastAPI 和 SQLite，本地演示过，没部署")
        self.assertIn("unsupported_result_upgrade:演示通过", errors)
        self.assertEqual([e for e in lexical_fact_errors("本地演示通过", "本地演示通过了") if e.startswith("unsupported_result")], [])
        from app.services.fact_guard import SEMANTIC_CONTRACT
        for phrase in ("新增归因/诊断", "定位为候选由模型自行生成", "结果升级", "本地演示通过"):
            self.assertIn(phrase, SEMANTIC_CONTRACT)
