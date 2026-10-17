"""Fictional multi-turn intake with stale targets and deliberately wrong model IDs."""
import copy
import logging
import re
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from test_campus_and_naming import ExtractorStub, raw, semantic_stub
from app.agents import resume_graph as graph
from app.agents.fact_extractor import apply_fact_patch, extract_facts_patch
from app.agents.triage_chain import TriageAction, TriageDecision
from app.schemas.facts import FACT_SECTIONS
from app.services.candidate_language import PLACEHOLDER_NAMES
from app.services.error_codes import ChatTurnError
from app.services.resume_facts import new_fact
from app.services.followup_context import latest_followup


INTRO = '我在青桥读书协会宣传部担任副部长，组织图书馆活动、海报设计和文字宣传。目前毕业一年做采购和行政工作。还有哪些岗位适合我？'
TOOLS = '协会海报运用了可画，但是是我独立完成的。个人认为能力尚浅。ps和ai以及Word、Exce、pptl都会使用。'
POSTERS = '图书馆活动的海报，大约做了十张，在公众号、馆内展板和线下活动现场均有使用'
COURSE = '大学摄影课作业是淘宝网页设计，产品拍摄和页面排版，基本独立完成'
PRACTICE = '周末自己练手，用即梦和workbuddy做了照片拼贴。用过即梦。有自信能独立完成，我认为可以接单'
NAME_QUESTION = '需要你补充：「工作经历（待补公司/岗位名）」的公司名称和岗位是什么？'


def targeted():
    return {'campus': [{'item_id': 'club', 'name': '青桥读书协会', 'facts': [new_fact('组织图书馆活动和海报宣传')]}],
            'work_experience': [{'item_id': 'work', 'company': PLACEHOLDER_NAMES['work_experience'],
                                 'facts': [new_fact('毕业后从事采购和行政')]}],
            'followup_target': {'item_id': 'work', 'section': 'work_experience',
                                'asked_hash': graph._hash_text(latest_followup(NAME_QUESTION))}}


def wrong_patch(text, *, explicit=False, whole=False):
    # Mimic a model that assigns every clause to the current work follow-up,
    # omits IDs and sometimes even supplies the wrong section.
    parts = [text] if whole else [p for p in re.split(r'[，。]', text) if p]
    return {'items': [{'section': 'open_source', 'name': PLACEHOLDER_NAMES['work_experience'],
                       **({'item_id': 'work'} if explicit else {}), 'facts': [raw(p) for p in parts]}]}


def facts(data, section=None):
    return [f['text'] for key in ([section] if section else FACT_SECTIONS)
            for item in data.get(key, []) for f in item.get('facts', []) if f.get('status') == 'active']


class FollowupTargetScopeTest(unittest.IsolatedAsyncioTestCase):
    async def extract(self, text, data, output=None, previous=NAME_QUESTION):
        result = await extract_facts_patch(text, data, ExtractorStub(output if output is not None else wrong_patch(text)),
                                           previous_assistant=previous, semantic_check=semantic_stub)
        return apply_fact_patch(data, result)

    async def test_multiturn_wrong_sections_and_missing_ids(self):
        data = await self.extract(INTRO, {}, previous='')
        self.assertEqual(len(data['campus']), 1)
        self.assertEqual(len(data['work_experience']), 1)
        work_id = data['work_experience'][0]['item_id']
        replies = []
        for text in (TOOLS, POSTERS, COURSE, PRACTICE):
            data['followup_target'] = {'item_id': work_id, 'section': 'work_experience',
                                       'asked_hash': graph._hash_text(latest_followup(NAME_QUESTION))}
            before = copy.deepcopy(data)
            data = await self.extract(text, data)
            result = graph._finish_followup_turn({'collected_info': before, 'messages': [HumanMessage(content=text)]},
                {'collected_info': data, 'messages': [AIMessage(content='需要你补充：这些作品用在什么场合？')]})
            replies.append('\n'.join(m.content for m in result['messages']))
            data = result['collected_info']
        self.assertEqual(len(data['work_experience']), 1)
        self.assertTrue(all('采购' in text or '行政' in text for text in facts(data, 'work_experience')))
        campus = ' '.join(facts(data, 'campus'))
        for token in ('十张', '公众号', '馆内展板', '线下活动现场', '可画'):
            self.assertIn(token, campus)
        courses = [item for item in data['projects'] if item['name'] == '淘宝网页设计']
        self.assertEqual(len(courses), 1)
        course_facts = courses[0]['facts']
        self.assertIn('产品拍摄和页面排版', ' '.join(f['text'] for f in course_facts))
        self.assertTrue(any(f['kind'] == 'status_limit' and f['text'] == '课程作业' for f in course_facts))
        self.assertEqual(len(data['projects']), 2)
        skill_text = ' '.join(row['name'] for row in data['skills'])
        for token in ('Photoshop', 'Illustrator', 'Word', 'Excel', 'PPT', '可画', '即梦', 'WorkBuddy'):
            self.assertIn(token, skill_text)
        all_facts = ' '.join(facts(data))
        for token in ('能力尚浅', '有自信', '可以接单', '哪些岗位', '都会使用', '用过即梦'):
            self.assertNotIn(token, all_facts)
        self.assertTrue(all(len(re.findall('[？?]', reply)) <= 1 for reply in replies))

    async def test_name_followup_ignores_non_name_answers_even_with_explicit_id(self):
        for text in (POSTERS, COURSE, PRACTICE, '会使用PS和AI，Word、Excel、PPT都会使用', '我整理了三份材料'):
            for whole in (False, True):
                with self.subTest(text=text, whole=whole):
                    data = await self.extract(text, targeted(), wrong_patch(text, explicit=True, whole=whole))
                    self.assertEqual(facts(data, 'work_experience'), ['毕业后从事采购和行政'])
                    self.assertEqual(data['work_experience'][0]['company'], PLACEHOLDER_NAMES['work_experience'])

    async def test_content_followup_routes_each_clause_not_entire_turn(self):
        data = targeted()
        data['work_experience'][0]['company'] = '青桥设备公司'
        text = '采购对接三家客户。协会海报做了十张。' + COURSE + '。' + PRACTICE
        updated = await self.extract(text, data, wrong_patch(text, explicit=True), previous='采购覆盖多少客户？')
        work = ' '.join(facts(updated, 'work_experience'))
        self.assertIn('三家客户', work)
        for token in ('海报', '拍摄', '拼贴'):
            self.assertNotIn(token, work)
        self.assertTrue(facts(updated, 'campus'))
        self.assertEqual(len(updated['projects']), 2)

    async def test_unrelated_content_and_note_only_output_do_not_use_target(self):
        for previous in (NAME_QUESTION, '采购覆盖多少客户？'):
            data = targeted()
            if previous != NAME_QUESTION:
                data['work_experience'][0]['company'] = '青桥设备公司'
            text = '我画了三幅插画'
            for output in (wrong_patch(text, explicit=True), {'items': [{
                    'section': 'work_experience', 'item_id': 'work', 'raw_notes': [text]}]}):
                with self.subTest(previous=previous, output=output):
                    updated = await self.extract(text, data, output, previous=previous)
                    self.assertEqual(facts(updated, 'work_experience'), ['毕业后从事采购和行政'])

    async def test_cropped_self_assessment_cannot_become_completed_fact(self):
        text = '有自信能独立完成海报设计'
        data = await self.extract(text, targeted(), {'items': [{
            'section': 'work_experience', 'item_id': 'work', 'facts': [raw('独立完成海报设计')]}]})
        self.assertFalse(any('独立完成' in value for value in facts(data)))

    async def test_explicit_company_design_is_allowed_but_negation_is_not_a_bridge(self):
        text = '在公司里也用 PS 做过产品图'
        data = await self.extract(text, targeted(), wrong_patch(text, explicit=True))
        self.assertIn(text, facts(data, 'work_experience'))
        text = '几乎没有再做过设计的工作。' + COURSE
        data = await self.extract(text, targeted(), wrong_patch(text, explicit=True))
        self.assertFalse(any('拍摄' in f or '排版' in f for f in facts(data, 'work_experience')))
        self.assertEqual(len(data['projects']), 1)

    async def test_literal_name_and_refusal_do_not_create_experience_facts(self):
        data = await self.extract('青桥设备公司', targeted(), {})
        self.assertEqual(data['work_experience'][0]['company'], '青桥设备公司')
        for text in ('不方便说', '没有'):
            data = await self.extract(text, targeted(), {})
            self.assertEqual(facts(data, 'work_experience'), ['毕业后从事采购和行政'])

    async def test_tool_only_answer_cannot_rename_a_placeholder(self):
        for text in ('用过即梦', '会使用PS和AI', '十张'):
            data = await self.extract(text, targeted(), {})
            self.assertEqual(data['work_experience'][0]['company'], PLACEHOLDER_NAMES['work_experience'])
            self.assertEqual(facts(data, 'work_experience'), ['毕业后从事采购和行政'])

    async def test_same_clause_tool_delivery_is_both_skill_and_campus_fact(self):
        text = '用可画做了协会海报'
        data = await self.extract(text, targeted(), wrong_patch(text, explicit=True))
        self.assertIn(text, facts(data, 'campus'))
        self.assertTrue(any('可画' in row['name'] for row in data['skills']))
        self.assertNotIn(text, facts(data, 'work_experience'))

    async def test_negated_course_status_is_not_promoted_to_assignment(self):
        text = '这个摄影练习不是课程作业'
        data = await self.extract(text, {}, {'items': [{'section': 'projects', 'facts': [raw(text)]}]}, previous='')
        self.assertFalse(any(f['kind'] == 'status_limit' and f['text'] == '课程作业'
                             for item in data.get('projects', []) for f in item['facts']))

    async def test_omitted_course_and_poster_rows_recovered_without_target_binding(self):
        for text, section, token in ((COURSE, 'projects', '产品拍摄'), (POSTERS, 'campus', '十张')):
            with self.subTest(text=text):
                data = await self.extract(text, targeted(), {})
                self.assertIn(token, ' '.join(facts(data, section)))
                self.assertEqual(facts(data, 'work_experience'), ['毕业后从事采购和行政'])

    async def test_fourth_turn_wrap_preserves_facts_even_if_public_model_is_empty(self):
        for reply in ('需要你补充：海报面向哪些读者？', '', '   '):
            with self.subTest(reply=reply):
                data = targeted()
                state = {'collected_info': data, 'messages': [AIMessage(content=NAME_QUESTION), HumanMessage(content=POSTERS)],
                         'candidate_history_reconciled': True, 'stage': 'COLLECTING'}
                class PublicStub:
                    async def ainvoke(self, messages):
                        return AIMessage(content=reply)
                with (patch.object(graph, '_make_non_streaming_llm', return_value=ExtractorStub(wrong_patch(POSTERS))),
                      patch.object(graph, 'run_triage', AsyncMock(return_value=TriageDecision(action=TriageAction.WRAP_EXPERIENCE, reason='合成回放'))),
                      patch('app.agents.interviewer.first_draft_ready', return_value=False)):
                    result = await graph.collecting_node(state, PublicStub())
                self.assertIn('十张', ' '.join(facts(result['collected_info'], 'campus')))
                self.assertEqual(facts(result['collected_info'], 'work_experience'), ['毕业后从事采购和行政'])
                self.assertLessEqual(sum(m.content.count('？') for m in result['messages']), 1)

    async def test_one_question_is_enforced_before_public_stream(self):
        class PublicStub:
            async def ainvoke(self, messages):
                return AIMessage(content='需要你补充：海报用途是什么？\n公司名称是什么？\n学校名称是什么？')
        events = []
        with (patch('app.agents.public_reply.get_stream_writer', return_value=events.append),
              patch('app.agents.public_reply.get_config', return_value={})):
            reply = await graph._collection_reply(PublicStub(), [], targeted(), POSTERS)
        self.assertEqual(reply.content.count('？'), 1)
        self.assertEqual(''.join(e['content'] for e in events), reply.content)

    async def test_debug_traceback_only_in_local_environment(self):
        class BrokenGraph:
            async def astream(self, *args, **kwargs):
                raise ValueError('synthetic scope failure')
                yield
        for env in ('local', 'production'):
            with (patch.object(graph, 'get_graph', return_value=BrokenGraph()),
                  patch('app.config.get_settings', return_value=SimpleNamespace(APP_ENV=env, LLM_PLAN_CONFIRM=False)),
                  self.assertLogs(graph.logger, logging.DEBUG) as captured):
                with self.assertRaises(ChatTurnError):
                    async for _ in graph.stream_agent([{'content': '合成输入'}], 'scope-error', object()):
                        pass
            traces = [record for record in captured.records if record.exc_info]
            self.assertEqual(bool(traces), env == 'local')
            if env == 'production':
                self.assertNotIn('synthetic scope failure', '\n'.join(captured.output))


class FollowupQuestionScopeTest(unittest.TestCase):
    def test_content_question_wins_and_names_are_section_specific_and_asked_once(self):
        data = targeted()
        data['education'] = [{'item_id': 'edu', 'school': PLACEHOLDER_NAMES['education'], 'facts': [new_fact('艺术设计专科')]}]
        question = '需要你补充：海报用在什么场合？'
        result = graph._finish_followup_turn({'collected_info': data}, {'collected_info': data, 'messages': [AIMessage(content=question)]})
        self.assertEqual([m.content for m in result['messages']], [question])
        for section, field, token in (('education', 'school', '学校名称'), ('work_experience', 'company', '公司名称和岗位'),
                                      ('campus', 'name', '组织名称')):
            store = {section: [{'item_id': section, field: PLACEHOLDER_NAMES[section], 'facts': [new_fact('合成经历')]}]}
            result = graph._finish_followup_turn({'messages': [HumanMessage(content='没有更多内容了')]},
                {'collected_info': store, 'messages': [AIMessage(content='可以整理。')]})
            text = '\n'.join(m.content for m in result['messages'])
            self.assertIn(token, text)
            self.assertEqual(text.count('？'), 1)
            again = graph._finish_followup_turn({'collected_info': result['collected_info']},
                {'collected_info': result['collected_info'], 'messages': [AIMessage(content='可以整理。')]})
            self.assertEqual(len(again['messages']), 1)


if __name__ == '__main__':
    unittest.main()
