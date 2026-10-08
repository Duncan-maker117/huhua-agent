"""De-identified regressions for independent PDF/Markdown resume imports."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.candidate_material import looks_like_existing_resume, parse_existing_resume

PDF_TEXT = """林同学
求职意向 | AI 产品实习
教育背景
示例大学 | 软件工程（本科） | 大三在读 | 预计 2028 年 6 月毕业
个人定位
学生开发者 | AI 产品工程方向
项目经历
Mirror Skill | 开源偏好配置工具
独立开发者 2025 - 至今
▸ 问题：用户切换项目时需要重复描述个人偏好，体验
割裂。
▸ 产品：设计两条配置路径，通过对话生成配置文件。
RouteFlow | 本地路线规划 Agent
基于 POI 的路线规划系统 项目发起人 2026 - 至今
▸ 技术方案：通过候选地点与路线约束生成方案。
技能与工具
产品能力：需求分析 / PRD 撰写
开发实践：Python / FastAPI / GitHub
AI 工具：Cursor / Google
Stitch
自我评价
学生开发者，关注用户需求。
"""

MARKDOWN_TEXT = """# 林同学｜AI 产品实习

## 教育背景
示例大学 · 软件工程（本科） · 预计 2028 年 6 月毕业

## 项目经历
**ResumeLab  对话式材料工作台** · 2025.09
个人项目 · 产品设计与原型实现
- 负责产品设计与原型实现，拆解对话收集与导出流程。
- 连接聊天、预览与文档导出。

**CodeLab  代码 Agent** · 2026.05
训练营项目 · 负责 Agent 设计
- 组织代码索引与执行模块，相关改动通过上游 PR 合入。

**RouteFlow  旅行规划原型** · 2026.05 - 2026.07
黑客松项目 · 产品方案与原型实现
- 负责交互与原型落地，支持路线局部修改。
- 交通时间使用估算；未验证真实旅行效果。

## 产品与技术能力
**产品与 Agent：**需求拆解、交互设计、工具调用。
**开发实践：**Python、FastAPI、Git。

## 竞赛与活动
- 示例程序设计竞赛  算法组三等奖
- 示例训练营  结营证书

## 编辑记录（不进入 PDF 和 Word）
- 2026-10-01：候选人提供资料，不要求重复证明。
- 计划补齐联系方式。后台编辑记录并非项目经历。
"""


def documents(*items):
    return "\n\n".join(f"[文件: {name}]\n{body}" for name, body in items)


class CandidateMaterialDocumentsTest(unittest.TestCase):
    def test_both_formats_parse_independently_then_merge(self):
        result = parse_existing_resume(documents(("resume.pdf", PDF_TEXT), ("draft.md", MARKDOWN_TEXT)))
        self.assertEqual([p["name"] for p in result["projects"]], ["Mirror Skill", "RouteFlow", "ResumeLab", "CodeLab"])
        self.assertEqual(len(result["education"]), 1)
        self.assertEqual([d["project_count"] for d in result["imported_documents"]], [2, 3])
        self.assertEqual(result["basic_info"]["name"], "林同学")
        self.assertEqual(result["basic_info"]["objective"], "AI 产品实习")
        self.assertEqual(len(result["skills"]), 5)
        self.assertEqual(len(result["certificates"]), 2)

    def test_markdown_bold_title_without_pipe_is_a_resume(self):
        self.assertTrue(looks_like_existing_resume(MARKDOWN_TEXT))
        result = parse_existing_resume(MARKDOWN_TEXT)
        self.assertEqual([p["name"] for p in result["projects"]], ["ResumeLab", "CodeLab", "RouteFlow"])
        self.assertEqual(result["projects"][0]["start_date"], "2025.9")
        self.assertEqual(result["projects"][1]["role"], "负责 Agent 设计")
        self.assertEqual(result["projects"][2]["end_date"], "2026.7")

    def test_pdf_label_cannot_be_name_and_next_line_has_role_and_year(self):
        result = parse_existing_resume(PDF_TEXT)
        self.assertEqual(result["basic_info"]["name"], "林同学")
        project = result["projects"][0]
        self.assertEqual((project["role"], project["start_date"], project["end_date"]), ("独立开发者", "2025", "至今"))
        self.assertIn("体验割裂", project["description"])
        self.assertNotIn("个人定位", project["description"])

    def test_skill_boundary_and_editor_notes_cannot_pollute_project(self):
        result = parse_existing_resume(documents(("resume.pdf", PDF_TEXT), ("draft.md", MARKDOWN_TEXT)))
        descriptions = "\n".join(p["description"] for p in result["projects"])
        for excluded in ("产品能力", "AI 工具", "Google", "结营证书", "后台编辑记录", "不要求重复证明"):
            self.assertNotIn(excluded, descriptions)
        self.assertIn("AI 工具：Cursor / Google Stitch", result["skills"])
        self.assertIn("示例训练营  结营证书", result["certificates"])

    def test_conflicting_fields_keep_sources_and_no_silent_winner(self):
        result = parse_existing_resume(documents(("resume.pdf", PDF_TEXT), ("draft.md", MARKDOWN_TEXT)))
        route = next(p for p in result["projects"] if p["name"] == "RouteFlow")
        self.assertEqual(route["role"], "")
        self.assertEqual(route["start_date"], "2026.5")  # compatible year/month
        self.assertEqual(route["end_date"], "")
        conflicts = {c["field"]: c for c in result["field_conflicts"]}
        self.assertEqual(set(conflicts), {"role", "end_date"})
        self.assertEqual(conflicts["end_date"]["values"], [{"value": "至今", "source": "resume.pdf"}, {"value": "2026.7", "source": "draft.md"}])
        notes = "\n".join(result["verification_notes"])
        self.assertIn("resume.pdf：至今", notes)
        self.assertIn("draft.md：2026.7", notes)
        self.assertIn("未验证真实旅行效果", route["description"])

    def test_attachment_order_does_not_choose_conflict_winner(self):
        result = parse_existing_resume(documents(("draft.md", MARKDOWN_TEXT), ("resume.pdf", PDF_TEXT)))
        route = next(p for p in result["projects"] if p["name"] == "RouteFlow")
        self.assertEqual(route["role"], "")
        self.assertEqual(route["end_date"], "")
        self.assertEqual(route["start_date"], "2026.5")
        self.assertEqual(len(result["projects"]), 4)

    def test_identical_repeat_does_not_duplicate_records_or_conflicts(self):
        result = parse_existing_resume(documents(("one.md", MARKDOWN_TEXT), ("two.md", MARKDOWN_TEXT)))
        self.assertEqual(len(result["projects"]), 3)
        self.assertEqual(len(result["education"]), 1)
        self.assertEqual(len(result["skills"]), 2)
        self.assertFalse(result["field_conflicts"])
        project = result["projects"][0]
        self.assertEqual(project["description"].count("负责产品设计与原型实现"), 1)

    def test_uncertainty_is_section_specific_not_filename_specific(self):
        certain = parse_existing_resume(documents(("待核实初稿.md", MARKDOWN_TEXT)))
        self.assertEqual(len(certain["certificates"]), 2)
        uncertain = parse_existing_resume(MARKDOWN_TEXT.replace("## 产品与技术能力", "## 产品与技术能力（待本人核实）").replace("## 竞赛与活动", "## 竞赛与活动（待核实）"))
        self.assertFalse(uncertain["skills"])
        self.assertFalse(uncertain["certificates"])
        self.assertEqual(len(uncertain["projects"]), 3)

    def test_non_resume_attachment_never_extends_previous_project(self):
        source = documents(("resume.pdf", PDF_TEXT[:PDF_TEXT.index("技能与工具")]), ("notes.txt", "读岗位要求：精通 Rust，年薪百万。\n仅供参考，不是候选人经历。"))
        result = parse_existing_resume(source)
        self.assertNotIn("年薪百万", str(result))
        self.assertEqual(len(result["projects"]), 2)
        self.assertEqual(len(result["imported_documents"]), 1)

    def test_status_disagreement_retains_both_source_statements(self):
        old = MARKDOWN_TEXT.replace("连接聊天、预览与文档导出。", "项目尚未上线，仅有本地原型。")
        new = MARKDOWN_TEXT.replace("连接聊天、预览与文档导出。", "项目已上线，有公开演示地址。")
        result = parse_existing_resume(documents(("old.md", old), ("new.md", new)))
        conflict = next(c for c in result["field_conflicts"] if c["field"] == "release_status")
        self.assertEqual({v["value"] for v in conflict["values"]}, {"未上线", "已上线"})
        self.assertIn("上线状态", "\n".join(result["verification_notes"]))

    def test_cannot_invent_name_from_objective_label(self):
        result = parse_existing_resume(PDF_TEXT.replace("林同学\n", ""))
        self.assertNotIn("name", result["basic_info"])
        self.assertEqual(result["basic_info"]["objective"], "AI 产品实习")

    def test_explicit_title_role_and_empty_named_experience_are_retained(self):
        text = "示例同学｜产品实习\n项目经历\nDocTool | 文件工具 · 独立开发者 · 2025\nOtherTool | 另一项原型 · 2026\n技能与工具\nPython"
        result = parse_existing_resume(text)
        self.assertEqual(len(result["projects"]), 2)
        self.assertEqual(result["projects"][0]["role"], "独立开发者")

    def test_negated_prose_is_not_a_role_and_summary_remains_source_text(self):
        text = PDF_TEXT.replace("独立开发者 2025 - 至今", "本人没有负责界面设计，只参与需求讨论。")
        result = parse_existing_resume(text)
        self.assertEqual(result["projects"][0]["role"], "")
        self.assertIn("没有负责界面设计", result["projects"][0]["description"])
        self.assertIn("学生开发者，关注用户需求。", result["personal_summary"])


if __name__ == "__main__":
    unittest.main()
