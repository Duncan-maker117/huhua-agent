"""Create synthetic browser fixtures with the real renderer; no server/providers."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'tests')]
from app.services.renderer import render_resume  # noqa: E402
from app.services.resume_workspace import build_workspace  # noqa: E402
from test_batch19a import fixture  # noqa: E402


def main():
    data, state = fixture()
    data['projects'][0]['polished_bullets'].append('这一句是我手动写的')
    data['projects'][0].update(role='个人开发', start_date='2026.06', end_date='2026.09')
    meta = state['resume_meta']['bullets']['p'][1]
    meta.update(flags=['transferable'], needs_metric=True, metric_question='一共验证了多少种情况？', req_ids=['r1'])
    state['jd_info'] = {'job_title': '产品实习生', 'role_profile': {'requirements': [{'id': 'r1', 'text': '整理用户反馈，推动产品迭代'}]}}
    state['match_plan'] = {'requirements': [{'req_id': 'r1', 'status': 'transferable'}]}
    workspace = build_workspace(state, data)
    workspace['focus'] = 'resume'
    result = {'data': data, 'workspace': workspace, 'revision': workspace['resume']['version'],
              'templates': [{'id': 't001-jianyue', 'name': '简约单栏'}, {'id': 't003-shenlan', 'name': '深蓝细线'}],
              'html': {template: render_resume(template, data) for template in ('t001-jianyue', 't003-shenlan')}}
    output = Path('/private/tmp/huhua-19a-browser-fixture.json')
    output.write_text(json.dumps(result, ensure_ascii=False))
    print(output)


if __name__ == '__main__':
    main()
