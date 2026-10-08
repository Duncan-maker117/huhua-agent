"""Complete chat submissions retain factual sections without Markdown headings."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.candidate_material import looks_like_existing_resume, parse_existing_resume


# Same structure as the reported failed input, with synthetic personal/project data.
CHAT_MATERIAL = """请直接为我制作一份中文一页简历，目标是 AI 产品／Agent 应用方向，暂无具体 JD。以下都是本人已确认的信息，不虚构实习、用户量或未提供的教育起始日期。使用项目经历、教育背景、产品与技术能力、竞赛与活动四个模块。

姓名：林同学
求职方向：AI 产品｜Agent 应用方向
电话：13800000000
邮箱：candidate@example.org

教育背景：示例大学，计算机科学与技术，本科，预计2027年6月毕业。

ResumeLab｜对话式材料工作台　2025.09
个人项目｜产品设计与原型实现
- 将零散经历整理拆为对话收集、构建、核对与导出，支持生成后继续补充。
- 使用结构化数据连接聊天、预览与 DOCX 导出；仅本地验证，尚未上线。

CodeLab｜代码 Agent　2026.05
示例AI训练营项目｜负责Agent设计
- 组织 Skill、代码索引与执行模块；相关改动通过 PR #6、#8 合入。
- 设计固定 Step 与 Contract 两条路径，保留人工暂停和工具权限边界。
贡献链接：https://github.com/example/CodeLab/pull/6

RouteFlow｜旅行规划原型　2026.05—2026.07
示例黑客松项目｜产品方案与原型实现
- 负责产品方案与原型落地，支持加站、换站与删站。
- 区分当次调整与长期偏好，真实旅行效果尚未验证。

产品与技术能力：
产品与Agent：需求拆解、交互流程、Prompt与Skill设计、工具调用及MCP。
开发实践：Python、FastAPI、LangGraph、Git/GitHub。

竞赛与活动：
示例省大学生程序设计竞赛，算法组三等奖。
示例程序设计大赛，Python组三等奖。
示例AI训练营，结营证书。

不需要自我评价或重复摘要；没有真实业务成效数字就不添加。请现在生成完整简历。
"""


class CandidateMaterialChatTest(unittest.TestCase):
    def test_complete_chat_is_recognized_without_project_section_heading(self):
        self.assertTrue(looks_like_existing_resume(CHAT_MATERIAL))
        result = parse_existing_resume(CHAT_MATERIAL)
        self.assertEqual([p["name"] for p in result["projects"]], ["ResumeLab", "CodeLab", "RouteFlow"])
        self.assertEqual(len(result["education"]), 1)
        self.assertEqual(len(result["skills"]), 2)
        self.assertEqual(len(result["certificates"]), 3)

    def test_explicit_identity_and_inline_comma_separated_education_are_preserved(self):
        result = parse_existing_resume(CHAT_MATERIAL)
        self.assertEqual(result["basic_info"], {
            "name": "林同学", "objective": "AI 产品｜Agent 应用方向",
            "phone": "13800000000", "email": "candidate@example.org",
        })
        education = result["education"][0]
        self.assertEqual((education["school"], education["major"], education["degree"]),
                         ("示例大学", "计算机科学与技术", "本科"))
        self.assertFalse(education.get("start_date"))
        self.assertEqual(education["end_date"], "预计2027年6月毕业")

    def test_project_kind_role_lines_never_become_extra_projects(self):
        result = parse_existing_resume(CHAT_MATERIAL)
        self.assertEqual([p["role"] for p in result["projects"]],
                         ["产品设计与原型实现", "负责Agent设计", "产品方案与原型实现"])
        self.assertEqual(result["projects"][0]["start_date"], "2025.9")
        self.assertEqual(result["projects"][2]["end_date"], "2026.7")

    def test_instructions_do_not_become_certificates_or_project_facts(self):
        result = parse_existing_resume(CHAT_MATERIAL)
        rendered = str(result)
        for instruction in ("请直接为我", "不虚构实习", "不需要自我评价", "请现在生成"):
            self.assertNotIn(instruction, rendered)
        for fact in ("尚未上线", "真实旅行效果尚未验证", "PR #6、#8", "结营证书", "Prompt与Skill"):
            self.assertIn(fact, rendered)

    def test_colon_markdown_headings_and_inline_skills_work_together(self):
        material = CHAT_MATERIAL.replace("教育背景：", "**教育背景：**").replace(
            "产品与技术能力：\n", "## 产品与技术能力："
        ).replace("竞赛与活动：", "## 竞赛与活动：")
        result = parse_existing_resume(material)
        self.assertEqual(len(result["projects"]), 3)
        self.assertEqual(len(result["skills"]), 2)
        self.assertEqual(len(result["certificates"]), 3)
        self.assertEqual(result["education"][0]["school"], "示例大学")

    def test_reference_and_job_descriptions_are_not_candidate_material(self):
        for prefix in ("参考简历：\n", "示例简历：\n", "他人简历：\n", "任职要求：\n", "目标 JD：\n"):
            with self.subTest(prefix=prefix):
                self.assertFalse(looks_like_existing_resume(prefix + CHAT_MATERIAL))
                self.assertIsNone(parse_existing_resume(prefix + CHAT_MATERIAL))

    def test_structured_reference_attachment_cannot_add_another_candidates_facts(self):
        reference = "参考简历：\n" + CHAT_MATERIAL.replace("ResumeLab", "OtherPersonsProject")
        material = f"[文件: my-resume.txt]\n{CHAT_MATERIAL}\n[文件: example.txt]\n{reference}"
        result = parse_existing_resume(material)
        self.assertEqual([p["name"] for p in result["projects"]], ["ResumeLab", "CodeLab", "RouteFlow"])
        self.assertEqual([d["name"] for d in result["imported_documents"]], ["my-resume.txt"])

    def test_instruction_only_outline_is_not_a_resume(self):
        outline = "请生成一份简历。\n教育背景：\n产品与技术能力：\n请使用项目名称｜项目说明的格式，并填满三项，注意使用足够详细的内容，凑满完整一页，提供技能与奖项。"
        self.assertFalse(looks_like_existing_resume(outline))
        self.assertIsNone(parse_existing_resume(outline))

    def test_negated_project_capability_is_not_mistaken_for_an_instruction(self):
        material = CHAT_MATERIAL.replace("- 负责产品方案与原型落地，支持加站、换站与删站。",
                                         "不需要数据库，所有配置保存在本地文件中。")
        result = parse_existing_resume(material)
        self.assertIn("不需要数据库", result["projects"][2]["description"])


if __name__ == "__main__":
    unittest.main()
