"""Same-experience ownership with deliberately fragmented/stale extractor output."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch as mock_patch

from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from app.agents.fact_extractor import apply_fact_patch, extract_facts_patch
from app.agents.resume_writer import run_resume_writer
from app.agents import resume_graph as graph
from app.agents.turn_actions import parse_education_fields
from app.schemas.facts import FACT_LABELS, FACT_SECTIONS
from app.services.candidate_language import PLACEHOLDER_NAMES, non_fact, placeholder_name
from app.services.resume_facts import active_facts_for_writer, new_fact, normalize_fact_store
from app.services.resume_workspace import build_workspace
from test_campus_and_naming import EchoWriter


A = '''我叫林晓禾，想投新媒体运营实习。
教育：华东理工商学院，市场营销本科，2023.09-2027.06。
实习：麦穗烘焙（连锁烘焙品牌），新媒体运营实习生，2025.03-2025.08。负责小红书账号日常更新，每周写3篇笔记；和店长一起策划过一次新品试吃活动，那周到店人数比平时多，具体数字不记得。
校园：咖啡社副社长，2024.09-至今，组织过4次手冲分享会，每次约20人。
技能：剪映、Canva、Excel 基础函数。'''
B = ('我叫林晓禾，华东某大学市场营销专业大三，想投新媒体运营实习。经历：'
     '1）2025.03-2025.08 在一家本地连锁烘焙品牌做新媒体运营实习，负责小红书账号日常更新，'
     '每周写3篇笔记，跟店长一起策划过一次新品试吃活动，活动那周到店人数比平时多了一些，具体多少我不记得。'
     '2）校咖啡社副社长，组织过4次手冲分享会，每次20人左右。会用剪映、Canva、Excel 基础函数。')
CORRECTION = ('实习公司叫麦穗烘焙（连锁烘焙品牌），岗位是新媒体运营实习生，'
              '小红书笔记和试吃活动都是这同一段实习里的事，不是个人练习。教育时间是2023.09-2027.06。')
TECH = ('以下都是虚构测试材料，请帮我做一份面向 Java 后端开发的中文简历，材料已经给全，'
        '先直接生成，再告诉我哪些地方值得补充。姓名林泽，邮箱 linze@example.invalid。'
        '海城理工大学，计算机科学与技术，本科，2022.09—2026.06。'
        '目标岗位 JD：Java 后端开发校招，要求 Java、Spring Boot、MySQL、Redis，理解事务与缓存，能协作排查问题。'
        '2025.07—2025.09 在云舟科技做后端开发实习生，参与订单服务，团队 4 人；'
        '我负责订单查询接口和参数校验，用 Spring Boot 和 MySQL；'
        '在导师指导下给订单列表加了 Redis 缓存；'
        '在测试环境对一个慢查询加了联合索引，平均耗时由约 420ms 降到约 170ms，没做线上压测；'
        '编写了 12 条接口测试用例，并跟前端同学联调。'
        '课程项目叫校园二手交易系统，2025.03—2025.06，3 人组队，'
        '我负责商品发布和搜索接口，用 Spring Boot、MySQL；登录模块是另一位同学写的；'
        '部署在实验室服务器，只给班里演示，没有真实用户。'
        '会用 Java、Git，了解 Redis，不会 Kubernetes。无奖项。'
        '请保留参与程度和测试环境限制，不写成负责整个系统，也不要编造数据。')


def raw(text, field=None, kind='action'):
    return {'text': text, 'source_quote': text, 'kind': kind, **({'field': field} if field else {})}


def tech_output(*, role_field=True, course_prefix=False):
    return {'items': [
        {'section': 'internship', 'name': '云舟科技', 'facts': [
            raw('后端开发实习生', 'title', 'role'), raw('我负责订单查询接口和参数校验')]},
        {'section': 'projects', 'name': '校园二手交易系统', 'facts': [
            {'text': ('课程项目，' if course_prefix else '') + '2025.03—2025.06，3 人组队',
             'source_quote': '课程项目叫校园二手交易系统，2025.03—2025.06，3 人组队', 'kind': 'context'},
            {'text': '负责商品发布和搜索接口', 'source_quote': '我负责商品发布和搜索接口',
             'kind': 'role' if role_field else 'action', **({'field': 'role'} if role_field else {})},
            {'text': '使用 Spring Boot、MySQL', 'source_quote': '用 Spring Boot、MySQL', 'kind': 'method_tool'},
            raw('登录模块是另一位同学写的', kind='status_limit'),
            raw('部署在实验室服务器，只给班里演示，没有真实用户', kind='status_limit')]}]}


class Stub:
    def __init__(self, output):
        self.output = output

    async def ainvoke(self, _messages):
        return SimpleNamespace(content=json.dumps(self.output, ensure_ascii=False))


class SparseTechWriter(EchoWriter):
    """Reproduce the frozen first draft that mentions only team/demo context."""
    async def ainvoke(self, messages):
        result = await super().ainvoke(messages)
        for row in result['writer']['items']:
            if row['section'] == 'projects':
                facts = next(item['facts'] for item in self.payload['evidence']['projects']
                             if item['item_id'] == row['item_id'])
                context = [f for f in facts if not f.get('field') and (
                    '3 人组队' in f['text'] or f['text'].startswith(('登录模块', '部署在')))]
                row['bullets'] = [{'text': '，'.join(f['text'] for f in context),
                                   'fact_ids': [f['id'] for f in context]}]
        return result


async def semantic(rows):
    return {row['id']: {'verdict': 'pass'} for row in rows}


def fragmented_output(free=False):
    return {'items': [
        {'section': 'education', 'name': '华东某大学' if free else '华东理工商学院',
         'facts': [raw('华东某大学' if free else '华东理工商学院', 'school'),
                   raw('2025.03' if free else '2023.09', 'start_date'),
                   raw('2025.08' if free else '2027.06', 'end_date')]},
        {'section': 'internship', 'name': '本地连锁烘焙品牌' if free else '麦穗烘焙',
         'facts': [raw('新媒体运营实习' if free else '新媒体运营实习生', 'title')]},
        {'section': 'projects', 'name': '个人练习（待补名称）',
         'facts': [raw('负责小红书账号日常更新'), raw('每周写3篇笔记')]},
        {'section': 'work_experience', 'name': PLACEHOLDER_NAMES['work_experience'],
         'facts': [raw(('跟' if free else '和') + '店长一起策划过一次新品试吃活动'),
                   raw('活动那周到店人数比平时多了一些' if free else '那周到店人数比平时多'),
                   raw('具体多少我不记得' if free else '具体数字不记得', kind='status_limit')]},
        {'section': 'campus', 'name': '咖啡社',
         'facts': [raw('组织过4次手冲分享会'), raw('每次20人左右' if free else '每次约20人')]},
    ]}


def legacy_store(named=False):
    def field(text, name):
        return {**new_fact(text), 'field': name}
    store = {
        'education': [{'item_id': 'edu', 'school': '华东某大学',
                       'facts': [field('华东某大学', 'school'), field('2025.03', 'start_date'), field('2025.08', 'end_date')]}],
        'projects': [{'item_id': 'personal', 'name': '个人练习（待补名称）',
                      'facts': [new_fact('负责小红书账号日常更新'), new_fact('每周写3篇笔记')],
                      'raw_notes': ['负责小红书账号日常更新，每周写3篇笔记'],
                      'links': [{'text': '作品', 'url': 'https://example.com/work'}]}],
        'work_experience': [{'item_id': 'work', 'company': PLACEHOLDER_NAMES['work_experience'],
                             'facts': [new_fact('和店长一起策划过一次新品试吃活动'), new_fact('那周到店人数比平时多')]}],
        'campus': [{'item_id': 'club', 'name': '咖啡社', 'facts': [new_fact('组织过4次手冲分享会')]}],
        'followup_target': {'item_id': 'personal', 'section': 'projects', 'question_kind': 'name'},
    }
    if named:
        store['internship'] = [{'item_id': 'named', 'company': '麦穗烘焙',
                                'facts': [field('2025.03', 'start_date'), field('2025.08', 'end_date')]}]
    return normalize_fact_store(store)


def active_fields(item):
    return {fact['field']: fact['text'] for fact in item['facts']
            if fact.get('field') and fact['status'] == 'active'}


class Batch10Test(unittest.IsolatedAsyncioTestCase):
    async def extract(self, message, store=None, output=None):
        store = store or {}
        patch = await extract_facts_patch(message, store, Stub(output or {}), semantic_check=semantic,
                                         previous_assistant='个人练习的名称是什么？' if store else '', turn_id='batch10')
        return apply_fact_patch(store, patch), patch

    async def test_10c_project_duty_mislabelled_as_role_remains_a_body_fact(self):
        store, _ = await self.extract(TECH, output=tech_output())
        self.assertEqual(len(store['projects']), 1)
        project = store['projects'][0]
        duty = next(f for f in project['facts'] if f['text'] == '负责商品发布和搜索接口')
        self.assertFalse(duty.get('field'))
        self.assertEqual(duty['kind'], 'action')
        self.assertEqual(duty['source_quote'], '我负责商品发布和搜索接口')
        self.assertNotIn('订单查询', ' '.join(f['text'] for f in project['facts']))
        self.assertNotIn('商品发布', ' '.join(f['text'] for f in store['internship'][0]['facts']))

    async def test_10c_compound_date_header_keeps_team_and_original_quote(self):
        for prefix in (False, True):
            with self.subTest(course_prefix=prefix):
                store, _ = await self.extract(TECH, output=tech_output(course_prefix=prefix))
                project = store['projects'][0]
                self.assertEqual((project['start_date'], project['end_date']), ('2025.03', '2025.06'))
                team = next(f for f in project['facts'] if '3 人组队' in f['text'])
                self.assertEqual(team['text'], ('课程项目，' if prefix else '') + '3 人组队')
                self.assertEqual(team['source_quote'],
                                 '课程项目叫校园二手交易系统，2025.03—2025.06，3 人组队')
                body = [f['text'] for f in project['facts'] if not f.get('field')]
                self.assertNotIn('2025.', ' '.join(body))

    async def test_10c_tech_initial_writer_keeps_interfaces_tools_and_scope_without_date_bullet(self):
        for role_field, writer_type in ((False, EchoWriter), (True, EchoWriter), (True, SparseTechWriter)):
            with self.subTest(role_field=role_field, writer=writer_type.__name__):
                store, _ = await self.extract(TECH, output=tech_output(role_field=role_field))
                initial = graph._serialize_to_resume_data({'collected_info': store})
                written = await run_resume_writer(store, {}, writer_type(), current_data=initial)
                projects = written['resume_data']['projects']
                self.assertEqual(len(projects), 1)
                project = projects[0]
                self.assertEqual(project['name'], '校园二手交易系统')
                self.assertEqual((project['start_date'], project['end_date']), ('2025.03', '2025.06'))
                body = ' '.join(project['polished_bullets'])
                for value in ('商品发布', '搜索接口', 'Spring Boot', 'MySQL', '3 人', '登录', '同学', '实验室', '只给班里演示'):
                    self.assertIn(value, body)
                self.assertNotIn('没有真实用户', body)  # Batch 11b: absence stays a guard constraint.
                self.assertNotIn('2025.', body)
                self.assertNotIn('2025.', project['description'])

    async def test_10c_project_role_titles_are_not_demoted_to_actions(self):
        for role in ('后端开发负责人', '接口开发成员'):
            with self.subTest(role=role):
                text = f'课程项目叫校园二手交易系统，我担任{role}。'
                store, _ = await self.extract(text, output={'items': [
                    {'section': 'projects', 'name': '校园二手交易系统', 'facts': [raw(role, 'role', 'role')]}]})
                self.assertEqual(active_fields(store['projects'][0])['role'], role)

    def assert_single_internship(self, store, name):
        self.assertEqual(len(store.get('internship', [])), 1)
        self.assertFalse(store.get('projects'))
        self.assertFalse(store.get('work_experience'))
        self.assertEqual(len(store['education']), 1)
        self.assertEqual(len(store['campus']), 1)
        for section in FACT_SECTIONS:
            self.assertFalse(any(placeholder_name(row.get(FACT_LABELS[section], '')) for row in store.get(section, [])))
        job = store['internship'][0]
        self.assertEqual(job['company'], name)
        facts = ' '.join(f['text'] for f in job['facts'] if not f.get('field') and f['status'] == 'active')
        for text in ('小红书', '每周写3篇', '试吃活动', '到店人数'):
            self.assertIn(text, facts)
        self.assertNotIn('手冲', facts)
        self.assertEqual(active_fields(job)['start_date'], '2025.03')
        self.assertEqual(active_fields(job)['end_date'], '2025.08')
        return job

    def assert_job_metadata(self, store):
        job = store['internship'][0]
        self.assertEqual((job.get('start_date'), job.get('end_date')), ('2025.03', '2025.08'))
        self.assertEqual((active_fields(job)['start_date'], active_fields(job)['end_date']), ('2025.03', '2025.08'))
        workspace = build_workspace({'collected_info': store})
        row = next(row for row in workspace['experiences']['items'] if row['item_id'] == job['item_id'])
        self.assertNotIn('经历时间', row['missing'])
        self.assertEqual(row['period'], '2025.03 — 2025.08')
        projected = next(row for row in graph._serialize_to_resume_data({'collected_info': store})['work_experience']
                         if row['item_id'] == job['item_id'])
        self.assertEqual((projected['start_date'], projected['end_date']), ('2025.03', '2025.08'))
        bodies = [row['bullets'], projected['bullets'],
                  [f['text'] for f in active_facts_for_writer(store)['internship'][0]['facts'] if not f.get('field')]]
        for body in bodies:
            self.assertNotIn('2025.03', ' '.join(body))
            self.assertNotIn('连锁烘焙品牌', ' '.join(body))

    async def test_10b_a_model_metadata_bullets_become_fields_or_are_excluded(self):
        output = fragmented_output()
        output['items'][1]['facts'] += [raw('2025.03-2025.08', kind='context'),
                                       raw('连锁烘焙品牌', kind='context')]
        store, _ = await self.extract(A, output=output)
        self.assert_single_internship(store, '麦穗烘焙')
        self.assert_job_metadata(store)
        written = await run_resume_writer(store, {}, EchoWriter())
        job = written['resume_data']['work_experience'][0]
        self.assertEqual((job['start_date'], job['end_date']), ('2025.03', '2025.08'))
        self.assertNotIn('2025.03', ' '.join(job['bullets']))
        self.assertNotIn('连锁烘焙品牌', ' '.join(job['bullets']))

    async def test_10b_b_omitted_dates_and_normalized_description_survive_two_turns(self):
        output = fragmented_output(free=True)
        for item in output['items']:
            item['facts'] = [f for f in item['facts'] if f.get('field') not in {'start_date', 'end_date'}]
        initial, _ = await self.extract(B, output=output)
        self.assert_job_metadata(initial)
        self.assertNotIn('start_date', active_fields(initial['education'][0]))
        correction = {'items': [{'section': 'internship', 'name': '麦穗烘焙', 'facts': [
            {'text': '麦穗烘焙，连锁烘焙品牌', 'source_quote': '实习公司叫麦穗烘焙（连锁烘焙品牌）',
             'kind': 'context'}, raw('连锁烘焙品牌', kind='context')]}]}
        store, _ = await self.extract(CORRECTION, initial, correction)
        self.assert_single_internship(store, '麦穗烘焙')
        self.assert_job_metadata(store)
        self.assertEqual(active_fields(store['education'][0])['start_date'], '2023.09')

    async def test_10b_merge_retires_old_company_description_but_keeps_original_evidence(self):
        previous = legacy_store(named=True)
        description = new_fact('麦穗烘焙，连锁烘焙品牌', quote='实习公司叫麦穗烘焙（连锁烘焙品牌）')
        previous['projects'][0]['facts'].append(description)
        store, _ = await self.extract(CORRECTION, previous)
        self.assert_job_metadata(store)
        saved = next(f for f in store['internship'][0]['facts'] if f['id'] == description['id'])
        self.assertEqual(saved, {**description, 'status': 'deleted'})

    async def test_10b_numbered_ranges_are_scoped_even_without_sentence_breaks(self):
        text = ('我叫林晓禾，经历：1）2025.03-2025.08 在一家本地连锁烘焙品牌做新媒体运营实习，负责账号更新，'
                '2）2025.09-2025.10 在云河商贸做行政助理，整理考勤。')
        store, _ = await self.extract(text)
        self.assert_job_metadata(store)
        self.assertEqual((store['work_experience'][0]['start_date'], store['work_experience'][0]['end_date']),
                         ('2025.09', '2025.10'))

    async def test_10b_metadata_filter_preserves_actions_with_dates_and_parentheses(self):
        action = '2025.03-2025.08 负责连锁烘焙品牌的账号更新'
        text = '实习：麦穗烘焙（负责账号更新），新媒体运营实习生。' + action + '。'
        store, _ = await self.extract(text, output={'items': [{'section': 'internship', 'name': '麦穗烘焙',
            'facts': [raw('负责账号更新'), raw(action)]}]})
        body = [f['text'] for f in store['internship'][0]['facts'] if not f.get('field') and f['status'] == 'active']
        self.assertIn('负责账号更新', body)
        self.assertIn(action, body)

    async def test_10b_free_text_date_correction_and_removal_update_item_fields(self):
        initial, _ = await self.extract(A)
        updated, _ = await self.extract('麦穗烘焙，2025 年 4 月到 7 月。', initial)
        job = updated['internship'][0]
        self.assertEqual(job['item_id'], initial['internship'][0]['item_id'])
        self.assertEqual((job['start_date'], job['end_date']), ('2025.04', '2025.07'))
        self.assertEqual(updated['education'], initial['education'])
        self.assertEqual(updated['campus'], initial['campus'])
        removals = [{'item_id': job['item_id'], 'fact_id': f['id']} for f in job['facts']
                    if f.get('field') in {'start_date', 'end_date'} and f['status'] == 'active']
        cleared = apply_fact_patch(updated, {'removals': removals})
        self.assertEqual((cleared['internship'][0]['start_date'], cleared['internship'][0]['end_date']), ('', ''))
        row = next(row for row in build_workspace({'collected_info': cleared})['experiences']['items']
                   if row['item_id'] == job['item_id'])
        self.assertIn('经历时间', row['missing'])

    async def test_a_structured_line_owns_all_sentences_even_with_fragmented_model_rows(self):
        store, _ = await self.extract(A, output=fragmented_output())
        job = self.assert_single_internship(store, '麦穗烘焙')
        self.assertEqual(active_fields(job)['title'], '新媒体运营实习生')
        self.assertEqual(active_fields(store['education'][0])['start_date'], '2023.09')
        self.assertEqual(active_fields(store['education'][0])['end_date'], '2027.06')

    async def test_b_numbered_internship_owns_duties_and_dates_not_education(self):
        store, _ = await self.extract(B, output=fragmented_output(free=True))
        self.assert_single_internship(store, '本地连锁烘焙品牌')
        self.assertNotIn('start_date', active_fields(store['education'][0]))
        self.assertNotIn('end_date', active_fields(store['education'][0]))
        self.assertNotIn('start_date', parse_education_fields(B))

    async def test_same_turn_new_subjects_are_independent_of_model_row_order(self):
        output = fragmented_output()
        output['items'].reverse()
        store, _ = await self.extract(A, output=output)
        self.assert_single_internship(store, '麦穗烘焙')

    async def test_b_correction_merges_legacy_placeholders_and_corrects_education(self):
        for named in (False, True):
            with self.subTest(named=named):
                previous = legacy_store(named)
                before = copy.deepcopy(previous)
                ids = {f['id'] for key in ('projects', 'work_experience') for row in previous[key] for f in row['facts']}
                output = {'items': [{'section': 'projects', 'item_id': 'personal',
                                     'facts': [raw('实习公司叫麦穗烘焙（连锁烘焙品牌）'),
                                               raw('岗位是新媒体运营实习生'),
                                               raw('小红书笔记和试吃活动都是这同一段实习里的事'), raw('不是个人练习')]}]}
                store, patch = await self.extract(CORRECTION, previous, output)
                self.assertEqual(previous, before)
                self.assertFalse(store.get('projects'))
                self.assertFalse(store.get('work_experience'))
                self.assertEqual(len(store['internship']), 1)
                job = store['internship'][0]
                self.assertEqual(job['company'], '麦穗烘焙')
                self.assertTrue(ids <= {f['id'] for f in job['facts']})
                self.assertEqual(active_fields(job)['title'], '新媒体运营实习生')
                self.assertEqual(active_fields(store['education'][0])['start_date'], '2023.09')
                self.assertEqual(active_fields(store['education'][0])['end_date'], '2027.06')
                self.assertEqual(store['campus'], before['campus'])
                self.assertEqual(job['links'], previous['projects'][0]['links'])
                self.assertEqual({row['item_id'] for row in job['merged_from']}, {'personal', 'work'})
                self.assertNotIn('followup_target', store)
                self.assertFalse(any(non_fact(f['text']) for section in FACT_SECTIONS
                                     for row in active_facts_for_writer(store).get(section, []) for f in row['facts']))
                self.assertTrue(patch['merges'])
                if named:
                    self.assertEqual(job['item_id'], 'named')

    async def test_merge_correction_works_when_model_omits_every_operation(self):
        store, _ = await self.extract(CORRECTION, legacy_store(), {})
        self.assertEqual(len(store['internship']), 1)
        self.assertFalse(store.get('projects'))
        self.assertFalse(store.get('work_experience'))
        self.assertEqual(active_fields(store['education'][0])['end_date'], '2027.06')

    async def test_b_two_turns_preserve_dates_and_update_employer_and_role(self):
        initial, _ = await self.extract(B, output=fragmented_output(free=True))
        store, _ = await self.extract(CORRECTION, initial)
        job = self.assert_single_internship(store, '麦穗烘焙')
        self.assertEqual(active_fields(job)['title'], '新媒体运营实习生')
        data = graph._serialize_to_resume_data({'collected_info': store})
        self.assertFalse(data['projects'])
        self.assertEqual(len(data['work_experience']), 1)
        self.assertEqual(data['work_experience'][0]['title'], '新媒体运营实习生')
        self.assertEqual(data['work_experience'][0]['employment_type'], 'internship')
        self.assertEqual(data['education'][0]['start_date'], '2023.09')

    async def test_graph_intake_and_projection_do_not_reask_deleted_placeholder_names(self):
        previous = legacy_store(named=True)
        saved = graph._serialize_to_resume_data({'collected_info': previous})
        with mock_patch('app.services.fact_guard.verify_semantics', side_effect=semantic):
            collected = await graph._extract_with_previous_assistant(
                CORRECTION, previous, Stub({}), '个人练习的名称是什么？')
        result = graph._live_resume_update({'resume_data': saved}, collected)
        self.assertFalse(result['resume_data']['projects'])
        self.assertEqual(len(result['resume_data']['work_experience']), 1)
        self.assertEqual(result['resume_data']['work_experience'][0]['company'], '麦穗烘焙')
        self.assertEqual(result['resume_data']['education'][0]['end_date'], '2027.06')
        finished = graph._finish_followup_turn(
            {'collected_info': collected, 'messages': [HumanMessage(content='先这样')]},
            {'collected_info': collected, 'messages': [AIMessage(content='已整理好。')]})
        self.assertFalse(any('待补' in message.content or '名称是什么' in message.content
                             for message in finished['messages']))

    async def test_labelled_lines_stop_at_next_subject_and_keep_separate_dates(self):
        text = ('实习：麦穗烘焙，新媒体运营实习生，2025.03-2025.08。负责账号日常更新。\n'
                '工作：云河商贸，行政助理，2025.09-2025.10。和店长一起整理考勤。')
        store, _ = await self.extract(text, output={'items': [{'section': 'projects', 'facts': [
            raw('负责账号日常更新'), raw('和店长一起整理考勤')]}]})
        self.assertFalse(store.get('projects'))
        job, work = store['internship'][0], store['work_experience'][0]
        self.assertEqual(active_fields(job)['end_date'], '2025.08')
        self.assertEqual(active_fields(work)['start_date'], '2025.09')
        self.assertNotIn('考勤', ' '.join(f['text'] for f in job['facts']))
        self.assertNotIn('账号', ' '.join(f['text'] for f in work['facts']))

    async def test_shared_month_values_do_not_erase_other_experience_dates(self):
        text = ('教育：华东理工商学院，市场营销本科，2025.03-2027.06。\n'
                '实习：麦穗烘焙，新媒体运营实习生，2025.03-2025.08。负责账号日常更新。\n'
                '校园：咖啡社副社长，2025.03-2025.08。组织过4次手冲分享会。')
        store, _ = await self.extract(text)
        for section, end in (('education', '2027.06'), ('internship', '2025.08'), ('campus', '2025.08')):
            fields = active_fields(store[section][0])
            self.assertEqual((fields['start_date'], fields['end_date']), ('2025.03', end))

    async def test_explicit_not_a_project_with_named_company_merges_matching_topics(self):
        text = CORRECTION.replace('都是这同一段实习里的事，不是个人练习', '不是个人练习')
        store, _ = await self.extract(text, legacy_store())
        self.assertEqual(len(store['internship']), 1)
        self.assertFalse(store.get('projects'))
        self.assertFalse(store.get('work_experience'))

    async def test_merge_reuses_named_item_from_same_model_patch_without_followup_target(self):
        previous = legacy_store()
        previous.pop('followup_target')
        output = {'items': [{'section': 'internship', 'name': '麦穗烘焙', 'facts': [
            raw('实习公司叫麦穗烘焙（连锁烘焙品牌）'), raw('新媒体运营实习生', 'title', 'role')]}]}
        store, _ = await self.extract(CORRECTION, previous, output)
        self.assertEqual(len(store['internship']), 1)
        self.assertEqual(store['internship'][0]['company'], '麦穗烘焙')
        self.assertFalse(store.get('projects'))
        self.assertFalse(store.get('work_experience'))

    async def test_merge_retires_old_meta_fact_but_preserves_fact_provenance(self):
        previous = legacy_store()
        meta = new_fact('小红书笔记和试吃活动属于同一段实习经历，非个人练习')
        previous['projects'][0]['facts'].append(meta)
        original = copy.deepcopy(previous['projects'][0]['facts'][0])
        store, _ = await self.extract(CORRECTION.replace('不是个人练习', '不是项目'), previous)
        job = store['internship'][0]
        self.assertEqual(next(f for f in job['facts'] if f['id'] == original['id']), original)
        self.assertEqual(next(f for f in job['facts'] if f['id'] == meta['id'])['status'], 'deleted')
        self.assertFalse(any(non_fact(f['text']) for f in active_facts_for_writer(store)['internship'][0]['facts']))

    async def test_ambiguous_or_negated_merge_does_not_remove_items(self):
        for message, ambiguous in ((CORRECTION.replace('都是这同一段', '不是同一段'), False), (CORRECTION, True)):
            previous = legacy_store()
            if ambiguous:
                previous['projects'].append({'item_id': 'other', 'name': '个人练习（待补名称）',
                                             'facts': [new_fact('每周写小红书笔记')]})
            store, patch = await self.extract(message, previous)
            self.assertFalse(patch.get('merges'))
            self.assertEqual({r['item_id'] for r in store['projects']}, {r['item_id'] for r in previous['projects']})
            self.assertEqual(store['work_experience'], previous['work_experience'])

    async def test_unrelated_personal_project_and_admin_remain_distinct(self):
        text = '周末自己练手做的个人项目，用Python做了照片拼贴。日常行政工作负责员工考勤管理。'
        store, _ = await self.extract(text, output={'items': [{'section': 'projects', 'facts': [
            raw('周末自己练手做的个人项目'), raw('用Python做了照片拼贴'), raw('日常行政工作负责员工考勤管理')]}]})
        self.assertEqual(len(store['projects']), 1)
        self.assertEqual(len(store['work_experience']), 1)
        self.assertIn('考勤', ' '.join(f['text'] for f in store['work_experience'][0]['facts']))
        self.assertNotIn('考勤', ' '.join(f['text'] for f in store['projects'][0]['facts']))

    async def test_meta_statements_are_not_facts_even_with_cropped_quotes(self):
        for text in ('我不是项目负责人，只负责账号更新', '在同一段实习中负责账号更新'):
            self.assertFalse(non_fact(text))
        for text in ('小红书笔记和试吃活动属于同一段实习经历', '这不是个人练习', '这不是项目'):
            store, _ = await self.extract(text, output={'items': [{'section': 'projects',
                  'facts': [raw(text), raw('试吃活动' if '试吃活动' in text else '个人练习' if '个人练习' in text else '项目')]}]})
            self.assertFalse(any(row.get('facts') for section in FACT_SECTIONS for row in store.get(section, [])))


if __name__ == '__main__':
    unittest.main()
