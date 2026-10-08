"""Synthetic, offline checks of the text sent to model adapters."""

import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agents.career_prompt import career_messages  # noqa: E402
from app.agents.decoder_chain import run_decoder_chain  # noqa: E402
from app.agents.editor_chain import EditorOutput, run_editor  # noqa: E402
from app.agents.public_reply import stream_public_reply  # noqa: E402
from app.services.model_privacy import (  # noqa: E402
    CONTACT_PRIVACY_NOTICE,
    ContactRedactor,
    ContactTokenStream,
    redact_model_messages,
)


class ModelPrivacyTest(unittest.IsolatedAsyncioTestCase):
    def test_common_contacts_mask_and_restore_exact_format(self):
        source = (
            "邮箱test.person+resume@example.invalid；备用邮箱second@example.invalid\n"
            "手机：13800138000；海外格式 +86 139 0013 8000\n"
            "电话：0755-12345678；Phone: +1 (415) 555-1234；重复13800138000"
        )
        privacy = ContactRedactor()
        safe = privacy.redact(source)
        for literal in ("test.person+resume@example.invalid", "second@example.invalid", "13800138000", "+86 139 0013 8000", "0755-12345678", "+1 (415) 555-1234"):
            self.assertNotIn(literal, safe)
        self.assertEqual(privacy.restore(safe), source)
        self.assertTrue(privacy.has_contacts)
        self.assertEqual(safe.split("手机：")[1].split("；")[0], safe.split("重复")[1])

    def test_numbers_dates_and_identifiers_are_not_phone_numbers(self):
        source = (
            "2026-10-04；版本1.2；处理13800138000条记录；收入13900138000元；"
            "订单号：13700138000；学号13800138000；order_id=13900138000；"
            "ID：13600138000；13800138000.5；编号ABC13800138000；"
            "耗时1234567ms，电话尚未提供，邮箱没有，10页"
        )
        privacy = ContactRedactor()
        self.assertEqual(privacy.redact(source), source)
        self.assertFalse(privacy.has_contacts)

    def test_explicit_label_wins_and_json_fields_include_landline(self):
        source = {"phone": "0755-12345678", "facts": [{"field": "phone", "value": "+1 (415) 555-1234"}], "date": "2026-10-04"}
        before = copy.deepcopy(source)
        privacy = ContactRedactor()
        safe = privacy.redact(source)
        self.assertNotIn("0755", json.dumps(safe))
        self.assertNotIn("415", json.dumps(safe))
        self.assertEqual(source, before)
        self.assertEqual(privacy.restore(safe), source)
        self.assertIn("⟦电话:", privacy.redact("手机号13800138000，可处理100条"))

    def test_only_current_mapping_restores_tokens(self):
        first, second = ContactRedactor(), ContactRedactor()
        safe = first.redact("邮箱test@example.invalid，手机13800138000")
        self.assertEqual(second.restore(safe), safe)
        self.assertEqual(first.restore("⟦电话:unknown:A⟧"), "⟦电话:unknown:A⟧")
        self.assertNotEqual(safe, second.redact("邮箱test@example.invalid，手机13800138000"))

    def test_career_data_and_dynamic_contract_both_masked(self):
        privacy = ContactRedactor()
        messages = career_messages(None, "我的邮箱test@example.invalid", "目前手机号：13800138000", privacy=privacy)
        self.assertNotIn("13800138000", messages[0].content)
        self.assertNotIn("test@example.invalid", messages[1].content)
        self.assertIn(CONTACT_PRIVACY_NOTICE, messages[0].content)
        self.assertIn("已提供", messages[0].content)
        self.assertEqual(privacy.restore(messages[1].content), "我的邮箱test@example.invalid")

    def test_messages_copied_tool_args_masked_images_explicitly_opaque(self):
        image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,13800138000"}}
        messages = [
            SystemMessage(content="已有电话13800138000"),
            HumanMessage(content=[{"type": "text", "text": "test@example.invalid"}, image], id="history-id"),
            AIMessage(content="", tool_calls=[{"name": "extract", "args": {"email": "test@example.invalid"}, "id": "call-id", "type": "tool_call"}]),
        ]
        before = copy.deepcopy(messages)
        privacy = ContactRedactor()
        safe = redact_model_messages(messages, privacy)
        self.assertEqual(messages, before)
        self.assertNotIn("13800138000", safe[0].content)
        self.assertNotIn("test@example.invalid", str(safe[1].content[0]))
        self.assertNotIn("test@example.invalid", str(safe[2].tool_calls))
        self.assertEqual(safe[1].content[1], image)
        self.assertEqual(safe[1].id, "history-id")
        self.assertEqual(safe[2].tool_calls[0]["id"], "call-id")

    def test_dictionary_messages_keep_roles_and_hide_contacts(self):
        messages = [{"role": "system", "content": "分析用户内容"}, {"role": "user", "content": "电话13800138000"}]
        before = copy.deepcopy(messages)
        safe = redact_model_messages(messages)
        self.assertEqual(messages, before)
        self.assertEqual(safe[1]["role"], "user")
        self.assertNotIn("13800138000", safe[1]["content"])
        self.assertIn(CONTACT_PRIVACY_NOTICE, safe[0]["content"])

    async def test_public_fallback_masks_full_history_without_mutating_it(self):
        messages = [SystemMessage(content="联系方式邮箱test@example.invalid"), HumanMessage(content="电话13800138000")]
        before = copy.deepcopy(messages)
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content="请补充项目分工")))
        reply = await stream_public_reply(model, messages)
        outbound = str(model.ainvoke.call_args.args[0])
        self.assertNotIn("test@example.invalid", outbound)
        self.assertNotIn("13800138000", outbound)
        self.assertEqual(messages, before)
        self.assertEqual(reply.content, "请补充项目分工")

    async def test_public_stream_masks_full_history(self):
        captured = []

        async def stream(messages):
            captured.extend(messages)
            yield AIMessageChunk(content="联系方式已提供")

        reply = await stream_public_reply(SimpleNamespace(astream=stream), [HumanMessage(content="test@example.invalid")])
        self.assertNotIn("test@example.invalid", str(captured))
        self.assertIn(CONTACT_PRIVACY_NOTICE, captured[0].content)
        self.assertEqual(reply.content, "联系方式已提供")

    async def test_public_echo_token_across_chunks_is_readable_and_still_streams(self):
        events = []
        messages = career_messages(None, "test@example.invalid")
        token = messages[1].content

        async def stream(_messages):
            yield AIMessageChunk(content="已记录")
            self.assertEqual(events[0]["content"], "已记录")
            for part in (token[:1], token[1:4], token[4:-1], token[-1:]):
                yield AIMessageChunk(content=part)
            yield AIMessageChunk(content="，继续补充项目。")

        with (
            patch("app.agents.public_reply.get_stream_writer", return_value=events.append),
            patch("app.agents.public_reply.get_config", return_value={}),
        ):
            reply = await stream_public_reply(SimpleNamespace(astream=stream), messages)
        self.assertEqual(reply.content, "已记录（邮箱已提供），继续补充项目。")
        self.assertEqual("".join(event["content"] for event in events), reply.content)
        self.assertNotIn("⟦", reply.content)
        self.assertNotIn("test@example.invalid", reply.content)

    def test_contact_token_stream_preserves_normal_brackets_and_finishes_partial(self):
        stream = ContactTokenStream()
        self.assertEqual(stream.feed("普通文本⟦其他注释⟧"), "普通文本⟦其他注释⟧")
        self.assertEqual(stream.feed("继续⟦电话:abc"), "继续")
        self.assertEqual(stream.finish(), "（电话已提供）")
        self.assertEqual(stream.feed("⟦电话:unknown:A⟧"), "⟦电话:unknown:A⟧")

    async def test_editor_restores_exact_bullets_before_source_check(self):
        source = {"basic_info": {"email": "test@example.invalid"}, "skills": [], "projects": [{"name": "通讯记录", "description": "配置收件邮箱test@example.invalid。"}]}
        before = copy.deepcopy(source)

        async def answer(messages):
            self.assertNotIn("test@example.invalid", str(messages))
            data = json.loads(messages[1].content.split("\n", 1)[1])
            return EditorOutput(project_polishes=[{"name": "通讯记录", "polished_bullets": [data["projects"][0]["description"]]}])

        model = SimpleNamespace(ainvoke=AsyncMock(side_effect=answer))
        with patch("app.agents.editor_chain.with_structured_output", return_value=model):
            result = await run_editor(source, object())
        self.assertEqual(source, before)
        self.assertEqual(result["projects"][0]["polished_bullets"], [source["projects"][0]["description"]])
        self.assertEqual(result["basic_info"], source["basic_info"])

    async def test_decoder_restores_quotes_before_source_validation(self):
        source = "请发简历至test@example.invalid"

        async def answer(messages):
            self.assertNotIn("test@example.invalid", str(messages))
            quote = messages[1].content.split("<jd>\n", 1)[1].split("\n</jd>", 1)[0]
            return AIMessage(content=json.dumps({"requirement_evidence": [{"text": "简历投递", "category": "unspecified", "source_quote": quote}]}, ensure_ascii=False) + "\n---\n投递方式已提供")

        with patch("app.config.get_settings", return_value=SimpleNamespace(ENABLE_RAG=False)):
            result = await run_decoder_chain(source, SimpleNamespace(ainvoke=AsyncMock(side_effect=answer)))
        self.assertEqual(result["jd_info"]["requirement_evidence"][0]["source_quote"], source)


if __name__ == "__main__":
    unittest.main()
