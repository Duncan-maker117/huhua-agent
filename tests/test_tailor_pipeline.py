"""PR4 pipeline checks: page evidence, bounded compression and one snapshot."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.tailor_pipeline import (  # noqa: E402
    constraints_for_turn, infer_edit_scope, run_tailor_pipeline, turn_instruction,
)


def base():
    return {"basic_info": {"name": "Candidate", "objective": ""},
            "work_experience": [{"item_id": "keep", "company": "Example", "bullets": ["K" * 80, "K2"]}],
            "projects": [{"item_id": "brief", "name": "Short", "polished_bullets": ["B" * 80]},
                         {"item_id": "lead", "name": "Long", "polished_bullets": ["L" * 130]}],
            "self_evaluation": "Generic summary"}


def written(data, meta=None):
    return {"resume_data": deepcopy(data), "resume_meta": deepcopy(meta or {"bullets": {}}),
            "match_plan": {"experience_plan": [
                {"item_id": "brief", "treatment": "brief"},
                {"item_id": "keep", "treatment": "keep"},
                {"item_id": "lead", "treatment": "lead"}]},
            "omitted": [], "change_summary": ["更新文稿"], "guard_fallbacks": []}


class TailorPipelineTest(unittest.TestCase):
    def test_quoted_title_alias_is_local_but_stray_word_is_not_a_name(self):
        data = {"projects": [{"item_id": "p1", "name": "“书架角”网页 Demo"},
                             {"item_id": "p2", "name": "的"}]}
        self.assertEqual(infer_edit_scope(data, "请把书架角的描述改短"), ("item", ["p1"]))
        self.assertEqual(infer_edit_scope(data, "把当前的简历整体压缩"), ("whole", []))
        data["projects"].append({"item_id": "p3", "name": "“书架角”桌面版"})
        self.assertEqual(infer_edit_scope(data, "优化书架角"), ("whole", []))

    def test_local_overflow_only_shortens_selected_bullet_and_preserves_other_bytes(self):
        original = base()
        for scope, targets in (("item", ["lead"]),
                               ("bullet", ["/projects/1/polished_bullets/0"])):
            with self.subTest(scope=scope):
                state = {"resume_data": deepcopy(original), "resume_meta": {},
                         "resume_versions": [], "collected_info": {}, "jd_info": {"role_profile": {}}}
                calls = []

                async def fake_writer(_collected, _profile, _llm, **kwargs):
                    calls.append((kwargs["scope"], list(kwargs["targets"])))
                    data = deepcopy(kwargs["current_data"])
                    if "约" in kwargs["instruction"] and kwargs["scope"] == "bullet":
                        data["projects"][1]["polished_bullets"][0] = "L" * 55
                    return written(data, kwargs["resume_meta"])

                def overflow(_data, constraints):
                    return {"status": "test_simulated_overflow", "pages": 3,
                            "page_limit": constraints["page_limit"], "within_page_limit": False}

                with patch("app.agents.tailor_pipeline.run_resume_writer", side_effect=fake_writer), \
                        patch("app.agents.tailor_pipeline.measure_rendered_pages", side_effect=overflow):
                    result = asyncio.run(run_tailor_pipeline(state, original, object(),
                                                             instruction="把目标项目缩短", scope=scope,
                                                             targets=targets))
                output = result["resume_data"]
                for section, index in (("projects", 0), ("work_experience", 0)):
                    before = json.dumps(original[section][index], ensure_ascii=False, sort_keys=True).encode()
                    after = json.dumps(output[section][index], ensure_ascii=False, sort_keys=True).encode()
                    self.assertEqual(after, before)
                self.assertEqual(output["self_evaluation"], original["self_evaluation"])
                self.assertEqual(output["projects"][1]["polished_bullets"], ["L" * 55])
                self.assertEqual([row["op"] for row in result["compression_actions"]], ["shorten_bullet"])
                self.assertEqual(calls, [(scope, targets),
                                         ("bullet", ["/projects/1/polished_bullets/0"])])

    def test_constraints_survive_turns_and_ignore_attached_file_text(self):
        state = {"jd_info": {"role_profile": {"seniority": "intern"}}}
        first = constraints_for_turn(state, "请压到两页")
        self.assertEqual(first["page_limit"], 2)
        second = constraints_for_turn({**state, "session_constraints": first}, "这段项目再简洁些")
        self.assertEqual(second["page_limit"], 2)
        third = constraints_for_turn({**state, "session_constraints": second}, "改成一页")
        self.assertEqual(third["page_limit"], 1)
        self.assertEqual(constraints_for_turn({**state, "session_constraints": third}, "用英文")
                         ["language"], "en")
        attached = "[文件: 报告]\n旧材料称需要两页\n\n---\n\n请继续整理"
        self.assertEqual(turn_instruction(attached), "请继续整理")
        self.assertEqual(constraints_for_turn(state, attached)["page_limit"], 1)

    def test_scope_uses_visible_ordinal_and_returns_no_guess_for_missing_ordinal(self):
        data = {"projects": [{"item_id": "hidden", "name": "一", "hidden": True},
                             {"item_id": "p1", "name": "项目甲"},
                             {"item_id": "p2", "name": "项目乙"}],
                "work_experience": [{"item_id": "w1", "company": "公司甲"}]}
        self.assertEqual(infer_edit_scope(data, "把第二个项目改短"), ("item", ["p2"]))
        self.assertEqual(infer_edit_scope(data, "把公司甲经历改短"), ("item", ["w1"]))
        self.assertEqual(infer_edit_scope(data, "把第九个项目改短"), ("item", []))
        self.assertEqual(infer_edit_scope(data, "整体优化"), ("whole", []))

    def test_overflow_compression_order_two_writer_rounds_one_original_snapshot(self):
        original = base()
        state = {"resume_data": deepcopy(original), "resume_meta": {"version_id": "before-v1"},
                 "resume_versions": [], "collected_info": {"projects": [{"item_id": "lead", "facts": []}]},
                 "jd_info": {"role_profile": {"seniority": "intern"}}}
        untouched_state = deepcopy(state)
        writer_calls = []
        measurements = []

        async def fake_writer(collected, profile, llm, **kwargs):
            writer_calls.append({"collected": deepcopy(collected), "profile": deepcopy(profile),
                                 "scope": kwargs["scope"], "targets": list(kwargs["targets"]),
                                 "constraints": deepcopy(kwargs["constraints"])})
            if kwargs["scope"] == "whole":
                return written(original)
            data = deepcopy(kwargs["current_data"])
            target = kwargs["targets"][0]
            _, section, index, field, bullet = target.split("/")
            prior = data[section][int(index)][field][int(bullet)]
            data[section][int(index)][field][int(bullet)] = prior[0] * (70 if len(writer_calls) == 2 else 55)
            return written(data, kwargs["resume_meta"])

        def fake_measure(data, constraints):
            measurements.append(deepcopy(data))
            return {"status": "rendered", "pages": 3, "page_limit": constraints["page_limit"],
                    "within_page_limit": False}

        with patch("app.agents.tailor_pipeline.run_resume_writer", side_effect=fake_writer), \
                patch("app.agents.tailor_pipeline.measure_rendered_pages", side_effect=fake_measure):
            result = asyncio.run(run_tailor_pipeline(state, original, object(), instruction="压到一页"))
        self.assertEqual([call["scope"] for call in writer_calls], ["whole", "bullet", "bullet"])
        self.assertEqual([action["op"] for action in result["compression_actions"]],
                         ["hide_item", "cap_bullets", "shorten_bullet", "clear_self_evaluation",
                          "shorten_bullet"])
        self.assertTrue(result["resume_data"]["projects"][0]["hidden"])
        self.assertEqual(result["resume_data"]["work_experience"][0]["bullets"], ["K" * 55])
        self.assertEqual(result["resume_data"]["self_evaluation"], "")
        self.assertEqual(len(result["resume_versions"]), 1)
        self.assertEqual(result["resume_versions"][0]["version_id"], "before-v1")
        self.assertEqual(result["resume_versions"][0]["resume_data"], original)
        self.assertEqual(result["page_check"]["pages"], 3)
        self.assertFalse(result["page_check"]["within_page_limit"])
        self.assertEqual(state, untouched_state)
        self.assertGreaterEqual(len(measurements), 3)

    def test_render_error_stays_unknown_and_does_not_start_compression(self):
        original = base()
        state = {"resume_data": deepcopy(original), "resume_meta": {}, "resume_versions": [],
                 "collected_info": {"skills": []}, "jd_info": {"role_profile": {}}}
        calls = []

        async def fake_writer(*args, **kwargs):
            calls.append(kwargs["scope"])
            return written(original)

        with patch("app.agents.tailor_pipeline.run_resume_writer", side_effect=fake_writer), \
                patch("app.agents.tailor_pipeline.measure_rendered_pages", return_value={
                    "status": "render_error", "pages": None, "within_page_limit": None,
                    "error_type": "RuntimeError"}):
            result = asyncio.run(run_tailor_pipeline(state, original, object()))
        self.assertEqual(calls, ["whole"])
        self.assertEqual(result["compression_actions"], [])
        self.assertIsNone(result["page_check"]["pages"])
        self.assertIsNone(result["page_check"]["within_page_limit"])
        self.assertEqual(result["page_check"]["status"], "render_error")

    def test_main_failure_preserves_actual_body_and_evidence_not_serialized_base(self):
        from app.services.resume_versions import text_hash
        original = base()
        original['projects'][0]['hidden'] = True
        original['projects'].reverse()
        prior_meta = {'version_id': 'actual-v1', 'label': '上一版',
                      'bullets': {'lead': [{'fact_ids': ['old'], 'text_hash': text_hash('L' * 130)}]},
                      'summary': {'fact_ids': ['old'], 'text_hash': text_hash('Generic summary')},
                      'match_plan': {'experience_plan': [{'item_id': 'lead', 'treatment': 'lead'}]},
                      'omitted': [{'item_id': 'brief', 'reason': '用户选择备用'}],
                      'guard_fallbacks': [{'reason': 'old_run_only'}]}
        new_facts = {'projects': [{'item_id': 'lead', 'facts': [
            {'id': 'old', 'text': 'L' * 130, 'source_quote': 'L' * 130, 'status': 'active'},
            {'id': 'new', 'text': '新增接口测试', 'source_quote': '新增接口测试', 'status': 'active'}]},
            {'item_id': 'brief', 'facts': [{'id': 'brief-source', 'text': 'B' * 80, 'status': 'active'}]}],
            'work_experience': [{'item_id': 'keep', 'facts': [
                {'id': 'keep-source', 'text': 'K' * 80, 'status': 'active'}]}]}
        state = {'resume_data': deepcopy(original), 'resume_meta': deepcopy(prior_meta),
                 'resume_versions': [{'version_id': 'older', 'resume_data': {'projects': []}}],
                 'collected_info': new_facts, 'session_constraints': {'page_limit': 2}}
        before = deepcopy(state)
        serialized = deepcopy(original)
        serialized['projects'].reverse()
        serialized['projects'][1]['polished_bullets'] = ['新增接口测试']
        serialized['self_evaluation'] = ''
        failed = written(serialized)
        failed['writer_diagnostic'] = {'status': 'model_fallback', 'mode': 'one_pass',
                                       'stage': 'one_pass', 'error_type': 'ValidationError'}
        failed['match_plan'] = {'experience_plan': [{'item_id': 'lead', 'treatment': 'backup'}]}
        def measure(data, constraints):
            self.assertEqual(data, original)
            self.assertEqual(constraints['page_limit'], 1)
            return {'status': 'rendered', 'pages': 2, 'page_limit': 1, 'within_page_limit': False}
        with patch('app.agents.tailor_pipeline.run_resume_writer', return_value=failed) as writer, \
             patch('app.agents.tailor_pipeline.measure_rendered_pages', side_effect=measure), \
             patch('app.agents.tailor_pipeline.plan_compression', side_effect=AssertionError('failed plan is not authoritative')), \
             patch('app.agents.tailor_pipeline.prepare_version', side_effect=AssertionError('failure must not create history')):
            result = asyncio.run(run_tailor_pipeline(state, serialized, object(), instruction='压成一页'))
        writer.assert_called_once()
        self.assertEqual(result['resume_data'], original)
        self.assertEqual(result['resume_meta']['bullets'], prior_meta['bullets'])
        self.assertEqual(result['resume_meta']['summary'], prior_meta['summary'])
        self.assertEqual(result['match_plan'], prior_meta['match_plan'])
        self.assertEqual(result['omitted'], prior_meta['omitted'])
        self.assertEqual(result['resume_versions'], state['resume_versions'])
        self.assertEqual(result['version_id'], 'actual-v1')
        self.assertEqual(result['collected_info'], new_facts)
        self.assertNotIn('新增接口测试', str(result['resume_data']))
        self.assertEqual(result['writer_diagnostic']['error_type'], 'ValidationError')
        self.assertEqual(result['writer_diagnostic']['fallback_action'], 'preserved_existing_draft')
        self.assertEqual(result['page_check']['pages'], 2)
        self.assertEqual(result['compression_actions'], [])
        self.assertFalse(result['changed'])
        self.assertEqual(result['diff'], [])
        self.assertEqual(result['change_summary'], [])
        self.assertEqual(result['guard_fallbacks'], [])
        self.assertEqual(result['resume_meta']['guard_fallbacks'], [])
        self.assertEqual(state, before)

    def test_main_failure_applies_confirmed_corrections_and_removals_without_compression(self):
        original = base()
        original['skills'] = ['Python', 'Excel']
        original['skill_groups'] = {'工具': ['Python', 'Excel']}
        original['projects'][1].update(role='旧角色', start_date='2020')
        collected = {'projects': [{'item_id': 'lead', 'facts': [
            {'id': 'live', 'text': '实现接口', 'source_quote': '实现接口', 'status': 'active'}]}],
            'skills': [{'name': 'Excel', 'status': 'active'}, {'name': 'Python', 'status': 'deleted'}]}
        projection = deepcopy(original)
        projection['basic_info']['name'] = '已确认新姓名'
        projection['projects'] = [deepcopy(original['projects'][1])]
        projection['projects'][0].update(name='已确认项目名', role='新角色', start_date='2022',
                                         polished_bullets=['实现接口'])
        projection['work_experience'] = []
        projection['skills'] = ['Excel']
        projection['skill_groups'] = {'工具': ['Excel']}
        projection['self_evaluation'] = ''
        failed = written(projection)
        failed['writer_diagnostic'] = {'status': 'model_fallback', 'error_type': 'TimeoutError'}
        failed['match_plan'] = {'experience_plan': [{'item_id': 'lead', 'treatment': 'backup'}]}
        state = {'resume_data': original, 'collected_info': collected,
                 'resume_meta': {'version_id': 'previous'}, 'resume_versions': []}
        with patch('app.agents.tailor_pipeline.run_resume_writer', return_value=failed), \
             patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={
                 'status': 'rendered', 'pages': 2, 'within_page_limit': False}), \
             patch('app.agents.tailor_pipeline.plan_compression', side_effect=AssertionError('failed plan')):
            result = asyncio.run(run_tailor_pipeline(state, projection, object()))
        data = result['resume_data']
        self.assertEqual(data['basic_info']['name'], '已确认新姓名')
        self.assertEqual([row['item_id'] for row in data['projects']], ['lead'])
        self.assertEqual(data['projects'][0]['polished_bullets'], ['L' * 130])
        self.assertEqual(data['projects'][0]['role'], '新角色')
        self.assertEqual(data['projects'][0]['start_date'], '2022')
        self.assertEqual(data['projects'][0]['name'], '已确认项目名')
        self.assertFalse(data['projects'][0].get('hidden'))
        self.assertEqual(data['work_experience'], [])
        self.assertEqual(data['skills'], ['Excel'])
        self.assertTrue(result['changed'])
        self.assertTrue(result['writer_diagnostic']['deterministic_updates_applied'])
        self.assertEqual(result['collected_info'], collected)
        self.assertEqual(result['compression_actions'], [])
        self.assertEqual(len(result['resume_versions']), 1)
        snapshot = result['resume_versions'][0]['resume_data']
        self.assertEqual([row['item_id'] for row in snapshot['projects']], ['lead'])
        self.assertEqual(snapshot['work_experience'], [])
        self.assertEqual(snapshot['skills'], ['Excel'])
        self.assertEqual(snapshot['skill_groups'], {'工具': ['Excel']})

    def test_main_failure_revokes_old_citations_and_invalidates_cleaned_history_page_count(self):
        from app.services.resume_versions import text_hash
        from app.services.resume_capacity import resume_data_hash
        old = {'projects': [{'item_id': 'p1', 'name': '原型',
                             'polished_bullets': ['上线并服务用户', '整理接口文档']}]}
        meta = {'version_id': 'old-v', 'bullets': {'p1': [
            {'fact_ids': ['revoked'], 'text_hash': text_hash('上线并服务用户')},
            {'fact_ids': ['live'], 'text_hash': text_hash('整理接口文档')}]},
            'page_check': {'status': 'rendered', 'pages': 1, 'within_page_limit': True,
                           'data_hash': resume_data_hash(old)}}
        facts = {'projects': [{'item_id': 'p1', 'facts': [
            {'id': 'revoked', 'text': '上线并服务用户', 'status': 'deleted'},
            {'id': 'live', 'text': '整理接口文档', 'status': 'active'}]}]}
        projection = {'projects': [{'item_id': 'p1', 'name': '原型', 'polished_bullets': ['整理接口文档']}]}
        failed = written(projection)
        failed['writer_diagnostic'] = {'status': 'model_fallback'}
        state = {'resume_data': old, 'resume_meta': meta, 'collected_info': facts,
                 'resume_versions': [{'version_id': 'earlier', 'resume_data': deepcopy(old),
                                      'resume_meta': deepcopy(meta)}]}
        def measure(data, constraints):
            self.assertNotIn('上线并服务用户', str(data))
            return {'status': 'rendered', 'pages': 2, 'within_page_limit': False,
                    'data_hash': resume_data_hash(data)}
        with patch('app.agents.tailor_pipeline.run_resume_writer', return_value=failed), \
             patch('app.agents.tailor_pipeline.measure_rendered_pages', side_effect=measure):
            result = asyncio.run(run_tailor_pipeline(state, projection, object()))
        self.assertEqual(result['resume_data'], projection)
        self.assertEqual(result['resume_meta']['bullets']['p1'][0]['fact_ids'], ['live'])
        self.assertEqual(result['page_check']['data_hash'], resume_data_hash(projection))
        self.assertEqual(len(result['resume_versions']), 2)
        for version in result['resume_versions']:
            self.assertNotIn('上线并服务用户', str(version['resume_data']))
            page = version['resume_meta']['page_check']
            self.assertEqual(page['status'], 'stale')
            self.assertIsNone(page['pages'])
            self.assertIsNone(page['within_page_limit'])
        self.assertEqual(state['resume_data'], old)

    def test_first_draft_without_visible_body_still_uses_source_fallback(self):
        safe = {'projects': [{'item_id': 'p1', 'name': '原型', 'polished_bullets': ['实现原型接口']} ]}
        for current in ({}, {'projects': [{'item_id': 'p1', 'name': '仅名称'}]},
                        {'projects': [{'item_id': 'p1', 'hidden': True, 'polished_bullets': ['旧隐藏正文']}]}):
            with self.subTest(current=current):
                failed = written(safe)
                failed['writer_diagnostic'] = {'status': 'model_fallback', 'error_type': 'RuntimeError'}
                with patch('app.agents.tailor_pipeline.run_resume_writer', return_value=failed), \
                     patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={
                         'status': 'rendered', 'pages': 1, 'within_page_limit': True}):
                    result = asyncio.run(run_tailor_pipeline({'resume_data': current}, safe, object()))
                self.assertEqual(result['resume_data'], safe)
                self.assertTrue(result['changed'])
                self.assertNotIn('fallback_action', result['writer_diagnostic'])

    def test_compression_writer_fallback_keeps_existing_local_behavior(self):
        original = base()
        main = written(original)
        main['writer_diagnostic'] = {'status': 'model_completed'}
        shortened = deepcopy(original)
        shortened['projects'][1]['polished_bullets'] = ['原始事实回退']
        compressed = written(shortened)
        compressed['writer_diagnostic'] = {'status': 'model_fallback', 'error_type': 'TimeoutError'}
        action = {'op': 'shorten_bullet', 'target': '/projects/1/polished_bullets/0',
                  'target_max_chars_estimate': 55, 'writer_required': True}
        with patch('app.agents.tailor_pipeline.run_resume_writer', side_effect=[main, compressed]) as writer, \
             patch('app.agents.tailor_pipeline.plan_compression', return_value=[action]), \
             patch('app.agents.tailor_pipeline.measure_rendered_pages', side_effect=[
                 {'status': 'rendered', 'pages': 2, 'within_page_limit': False},
                 {'status': 'rendered', 'pages': 1, 'within_page_limit': True}]):
            result = asyncio.run(run_tailor_pipeline({'resume_data': original}, original, object()))
        self.assertEqual(writer.call_count, 2)
        self.assertEqual(result['resume_data'], shortened)
        self.assertEqual(result['compression_writer_diagnostics'], [compressed['writer_diagnostic']])
        self.assertEqual(result['writer_diagnostic']['status'], 'model_completed')


if __name__ == "__main__":
    unittest.main()
