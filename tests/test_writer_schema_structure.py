"""Safe field hierarchy feedback; local parser/model doubles, no provider."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents import resume_writer as writer  # noqa: E402
from app.schemas.writer import MatchPlan, OnePassOutput  # noqa: E402


SOURCE_TEXT = "PRIVATE_CANDIDATE_TEXT_NOT_FOR_RETRY_FEEDBACK"
VALID = {"match_plan": {}, "writer": {"items": [{
    "item_id": "provided-item", "section": "projects",
    "bullets": [{"text": SOURCE_TEXT, "fact_ids": ["provided-fact"]}]}]}}


class Model:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, messages):
        self.calls.append(deepcopy(messages))
        return self.responses.pop(0)


def invoke(model, schema=OnePassOutput, state=None):
    return asyncio.run(writer._call(model, schema, {"evidence": SOURCE_TEXT},
                                   "Only supplied facts", "other",
                                   retry_state=state if state is not None else {"schema_retry_count": 0}))


def correction(model):
    return json.loads(model.calls[1][-1].content.split("安全结构提示：", 1)[1])


class WriterSchemaStructureTest(unittest.TestCase):
    def test_nested_extra_feedback_shows_actual_field_hierarchy_without_failed_values(self):
        bad = deepcopy(VALID)
        bad["writer"]["items"][0]["summary"] = "PRIVATE_MISPLACED_SUMMARY"
        bad["writer"]["items"][0]["bullets"][0]["PRIVATE_EXTRA_KEY"] = "PRIVATE_EXTRA_VALUE"
        state = {"schema_retry_count": 0}
        model = Model(bad, VALID)
        result = invoke(model, state=state)
        self.assertEqual(result.writer.items[0].bullets[0].text, SOURCE_TEXT)
        self.assertEqual(len(model.calls), 2)
        feedback = correction(model)
        structure = feedback["schema_structure"]
        self.assertEqual(structure["root_type"], "OnePassOutput")
        objects = structure["objects"]
        self.assertEqual(objects["OnePassOutput"]["allowed_fields"],
                         {"match_plan": "MatchPlan", "writer": "WriterDraft"})
        draft = objects["WriterDraft"]["allowed_fields"]
        self.assertEqual(draft["items"], {"array_of": "WrittenItem"})
        self.assertEqual(draft["summary"], "string")
        self.assertEqual(draft["skill_groups"], {"string_keys_with_values": {"array_of": "string"}})
        item = objects["WrittenItem"]["allowed_fields"]
        self.assertNotIn("summary", item)
        self.assertEqual(item["bullets"], {"array_of": "WrittenBullet"})
        self.assertEqual(item["section"], {"one_of": ["projects", "work_experience"]})
        self.assertEqual(set(objects["WrittenBullet"]["allowed_fields"]),
                         {"text", "fact_ids", "req_ids", "flags", "needs_metric", "metric_question"})
        self.assertEqual(objects["WrittenBullet"]["required_fields"], ["text"])
        self.assertIn({"loc": ["writer", "items", 0, "bullets", 0, "<extra>"],
                       "type": "extra_forbidden"}, feedback["validation_errors"])
        self.assertEqual(model.calls[0], model.calls[1][:-1])
        retry_message = model.calls[1][-1].content
        for secret in (SOURCE_TEXT, "PRIVATE_EXTRA_KEY", "PRIVATE_EXTRA_VALUE", "PRIVATE_MISPLACED_SUMMARY"):
            self.assertNotIn(secret, retry_message)
        self.assertNotIn("schema_structure", state)
        self.assertNotIn("defaults", json.dumps(structure))

    def test_plan_retry_uses_only_its_actual_schema_types(self):
        model = Model({"requirements": "WRONG_PRIVATE_VALUE"}, {})
        invoke(model, schema=MatchPlan)
        structure = correction(model)["schema_structure"]
        self.assertEqual(structure["root_type"], "MatchPlan")
        self.assertNotIn("WriterDraft", structure["objects"])
        self.assertNotIn("WrittenItem", structure["objects"])
        self.assertNotIn("summary/summary_fact_ids", model.calls[1][-1].content)
        self.assertNotIn("WRONG_PRIVATE_VALUE", model.calls[1][-1].content)

    def test_repeated_extra_still_fails_after_one_retry_without_relaxing_schema(self):
        bad = deepcopy(VALID)
        bad["writer"]["items"][0]["bullets"][0]["PRIVATE_EXTRA_KEY"] = "PRIVATE_EXTRA_VALUE"
        model = Model(bad, bad, VALID)
        state = {"schema_retry_count": 0}
        with self.assertRaises(writer.ValidationError):
            invoke(model, state=state)
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(len(model.responses), 1)
        self.assertEqual(state["schema_retry_count"], 1)
        self.assertEqual(OnePassOutput.model_config["extra"], "forbid")
        self.assertNotIn("PRIVATE_EXTRA_KEY", json.dumps(state))
        self.assertNotIn("PRIVATE_EXTRA_VALUE", json.dumps(state))


if __name__ == "__main__":
    unittest.main()
