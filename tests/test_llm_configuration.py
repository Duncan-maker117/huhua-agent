"""Offline checks for compatible model configuration at the real entry points."""

import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from dotenv import dotenv_values
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.api import chat, resume  # noqa: E402
from app.agents import resume_graph  # noqa: E402


class LLMConfigurationTests(unittest.TestCase):
    def settings(self, **updates):
        # Never read local configuration or inherit provider/database settings.
        with patch.dict(os.environ, {}, clear=True):
            return Settings(_env_file=None, **updates)

    def test_legacy_temperature_alias_and_new_key_precedence(self):
        legacy = self.settings(LLM_TEMPERATURE=0.23)
        self.assertEqual(legacy.LLM_CHAT_TEMPERATURE, 0.23)
        self.assertEqual(legacy.LLM_TEMPERATURE, 0.23)
        both = self.settings(LLM_TEMPERATURE=0.23, LLM_CHAT_TEMPERATURE=0.41)
        self.assertEqual(both.LLM_CHAT_TEMPERATURE, 0.41)
        self.assertEqual(both.LLM_TEMPERATURE, 0.41)
        with patch.dict(os.environ, {"LLM_TEMPERATURE": "0.19"}, clear=True):
            self.assertEqual(Settings(_env_file=None).LLM_CHAT_TEMPERATURE, 0.19)
        with patch.dict(os.environ, {"LLM_TEMPERATURE": "0.19", "LLM_CHAT_TEMPERATURE": "0.31"}, clear=True):
            self.assertEqual(Settings(_env_file=None).LLM_CHAT_TEMPERATURE, 0.31)

    def test_max_tokens_is_opt_in_and_rejects_nonpositive_limits(self):
        self.assertIsNone(self.settings().LLM_MAX_TOKENS)
        self.assertEqual(self.settings(LLM_MAX_TOKENS=1234).LLM_MAX_TOKENS, 1234)
        for value in (0, -1):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.settings(LLM_MAX_TOKENS=value)

    def test_chat_and_resume_entry_points_use_the_same_configuration(self):
        for cap in (None, 1234):
            settings = self.settings(LLM_API_KEY="offline-key", LLM_CHAT_TEMPERATURE=0.23, LLM_MAX_TOKENS=cap)
            for module, factory in ((chat, chat._get_llm), (resume, resume._llm_for_graph)):
                with self.subTest(cap=cap, module=module.__name__):
                    with patch.object(module, "get_settings", return_value=settings), patch.object(module, "ChatOpenAI") as model:
                        factory()
                    self.assertEqual(model.call_args.kwargs["temperature"], 0.23)
                    self.assertEqual(model.call_args.kwargs["max_tokens"], cap)
                    self.assertTrue(model.call_args.kwargs["streaming"])

    def test_internal_model_preserves_inherited_and_explicit_temperatures(self):
        llm = SimpleNamespace(model_name="main-model", openai_api_key="offline-key",
                              openai_api_base="https://example.invalid/v1", temperature=0.23)
        for cap in (None, 2345):
            for temperature in (None, 0):
                settings = self.settings(LLM_STRUCTURED_MODEL="structured-model", LLM_MAX_TOKENS=cap)
                with self.subTest(cap=cap, temperature=temperature):
                    with patch("app.config.get_settings", return_value=settings), patch.object(resume_graph, "ChatOpenAI") as model:
                        resume_graph._make_non_streaming_llm(llm, temperature=temperature)
                    self.assertEqual(model.call_args.kwargs["temperature"], 0.23 if temperature is None else 0)
                    self.assertEqual(model.call_args.kwargs["max_tokens"], cap)
                    self.assertEqual(model.call_args.kwargs["model"], "structured-model")
                    self.assertFalse(model.call_args.kwargs["streaming"])

    def test_example_matches_model_defaults_without_forcing_a_provider(self):
        settings = self.settings()
        example = dotenv_values(ROOT / ".env.example")
        self.assertEqual(example["LLM_MODEL"], settings.LLM_MODEL)
        self.assertEqual(example["LLM_STRUCTURED_MODEL"], settings.LLM_STRUCTURED_MODEL)
        self.assertEqual(example.get("LLM_BASE_URL"), settings.LLM_BASE_URL)
        self.assertEqual(float(example["LLM_CHAT_TEMPERATURE"]), settings.LLM_CHAT_TEMPERATURE)
        self.assertEqual(float(example["LLM_WRITER_TEMPERATURE"]), settings.LLM_WRITER_TEMPERATURE)
        self.assertNotIn("LLM_MAX_TOKENS", example)


if __name__ == "__main__":
    unittest.main()
