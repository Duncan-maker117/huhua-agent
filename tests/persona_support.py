"""Synthetic acceptance data; shared by checks, report and HTTP stub tests."""
from copy import deepcopy
from importlib import import_module
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
checks = import_module("evaluation.persona-ux.checks")
runner = import_module("evaluation.persona-ux.run_persona")
report = import_module("evaluation.persona-ux.report")
MATERIALS = ROOT / "evaluation" / "persona-ux-2026-10-15"
FIXTURES = json.loads((MATERIALS / "fixtures.json").read_text(encoding="utf-8"))


def golden_data(persona):
    names = {"tech": "林泽", "ops": "陈夏", "career": "周宁", "service": "赵悦", "design": "许禾"}
    schools = {"tech": ("海城理工大学", "计算机科学与技术", "本科"), "ops": ("江城学院", "新闻学", "本科"),
               "career": ("南川大学", "工商管理", "本科"), "service": ("新城职业学院", "电子商务", "大专"),
               "design": ("江湾艺术学院", "视觉传达设计", "本科")}
    roles = {"tech": "Java 后端开发", "ops": "新媒体运营", "career": "SaaS 客户成功", "service": "电商客服", "design": "UI 设计实习生"}
    school, major, degree = schools[persona]
    result = {"basic_info": {"name": names[persona], "objective": roles[persona]},
              "education": [{"school": school, "major": major, "degree": degree, "start_date": "2022.09", "end_date": "2026.06"}],
              "projects": [], "campus": [], "work_experience": [], "skills": [], "skill_groups": {}}
    if persona == "tech":
        result["work_experience"] = [{"company": "云舟科技", "title": "后端开发实习生", "start_date": "2025.07", "end_date": "2025.09",
                                      "bullets": ["4 人团队中负责订单查询接口与参数校验。", "在导师指导下添加 Redis 缓存。",
                                                  "在测试环境加联合索引，平均耗时从约420ms降至约170ms，没做线上压测。",
                                                  "编写12条接口测试用例，并与前端联调。"]}]
        result["projects"] = [{"name": "校园二手交易系统", "start_date": "2025.03", "end_date": "2025.06",
                               "polished_bullets": ["3人小组，负责商品发布和搜索接口，登录模块由同学实现；实验室服务器演示，没有真实用户。"]}]
        result["skills"] = ["Java", "Git", "Redis（了解）"]
    elif persona == "ops":
        result["campus"] = [{"name": "校园读书协会", "start_date": "2024.09", "end_date": "2025.06",
                             "bullets": ["完成8篇公众号文章排版，其中3篇初稿由本人撰写，选题由部长决定。"]}]
        result["work_experience"] = [{"company": "小巷咖啡", "bullets": ["拍摄6条短视频素材，其中2条由店长发布。", "按店长文案用Canva排版4张促销海报。"]}]
        result["skills"] = ["剪映", "Canva", "Excel", "PS"]
    elif persona == "career":
        result["work_experience"] = [{"company": "启明商贸", "title": "行政助理", "start_date": "2024.07", "end_date": "2026.09",
                                      "bullets": ["每月整理约30份报销材料，核对发票和审批单，金额由主管审批。",
                                                  "维护120人员工通讯录。", "协助组织6场内部培训，制作报名表、协调场地与签到。",
                                                  "接待访客，记录客户问题后转交业务同事。"]}]
        result["skills"] = ["Excel", "Word", "PPT"]
    elif persona == "service":
        result["education"][0].update(start_date="2021.09", end_date="2024.06")
        result["work_experience"] = [{"company": "禾木家居", "start_date": "2024.07", "end_date": "2026.09",
                                      "bullets": ["使用千牛承接售前咨询、物流查询和售后问题登记，每月处理约800次咨询。",
                                                  "退款提交主管审批，复杂投诉转交主管跟进。"]}]
        result["skills"] = ["Excel", "千牛"]
    else:
        result["projects"] = [{"name": "校园借物 App 概念设计", "start_date": "2025.03", "end_date": "2025.06",
                               "polished_bullets": ["访谈5位同学，Figma绘制12个高保真页面，整理18个按钮和表单组件，做2轮组内评审。课程概念作品，未上线。"]}]
        result["campus"] = [{"name": "江湾艺术学院青年志愿者协会", "bullets": ["按部长文案用Photoshop和Illustrator制作6张活动海报。"]}]
        result["skills"] = ["Figma", "Photoshop", "Illustrator", "Auto Layout（了解）"]
    return result


def golden_turns(persona, with_recovery=False):
    base = golden_data(persona)
    turns = []
    for action, text in runner.fixture_actions(FIXTURES[persona], with_recovery):
        data = deepcopy(base)
        if action == "correction":
            old, new = ("170ms", "190ms") if persona == "tech" else ("6场", "4场")
            data = json.loads(json.dumps(data, ensure_ascii=False).replace(old, new))
        reply = "已根据已有材料成稿，保留分工与限制。"
        if persona == "career":
            reply += "沟通、记录、协调能力可以迁移；缺少客户续费、CRM使用与产品培训证据，需要补充真实案例。"
        turns.append({"action": action, "trigger_action": action, "kind": "fixture", "input": text,
                      "resume_data": data, "workspace": {}, "reply": reply, "status": "ok", "sse_done": True})
    return turns


def golden_run(personas=checks.PERSONAS, with_recovery=False, run_id="golden"):
    return {"schema_version": 1, "run_id": run_id, "fixture_sha256": "synthetic-fixtures",
            "with_recovery": with_recovery, "stream_requests": sum(len(golden_turns(p, with_recovery)) for p in personas),
            "personas": {p: {"turns": golden_turns(p, with_recovery)} for p in personas}}
