"""Failure diagnostics preserve locations while excluding exception content."""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "evaluation/tailor-bench"
sys.path.insert(0, str(HERE))
SPEC = importlib.util.spec_from_file_location("bench_error_diagnostic_runner", HERE / "run_bench.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def execute_file(path, code):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code)
    namespace = {}
    exec(compile(code, str(path), "exec"), namespace)
    return namespace


class SafeExceptionDiagnosticTest(unittest.TestCase):
    def test_from_none_retains_inner_type_and_repo_location_without_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            namespace = execute_file(root / "backend/app/graph.py", '''
def inner():
    credential = "sk-PRIVATE_LOCAL_VALUE"
    raise ValueError("PRIVATE_MATERIAL and PRIVATE_ERROR_MESSAGE " + credential)

def wrapper():
    try:
        inner()
    except ValueError:
        raise RuntimeError("PRIVATE_WRAPPER_MESSAGE") from None
''')
            try:
                namespace["wrapper"]()
            except RuntimeError as error:
                with patch.object(runner, "ROOT", root):
                    result = runner.safe_exception_diagnostic(error)
            self.assertEqual([row["type"] for row in result["chain"]], ["RuntimeError", "ValueError"])
            self.assertTrue(result["chain"][0]["context_suppressed"])
            self.assertEqual(result["chain"][1]["relation"], "context")
            self.assertEqual(result["chain"][1]["repo_frames"][-1],
                             {"file": "backend/app/graph.py", "function": "inner", "lineno": 4})
            encoded = json.dumps(result)
            for secret in ("PRIVATE", "sk-", "credential", str(root), "raise ValueError"):
                self.assertNotIn(secret, encoded)

    def test_external_private_data_and_symlink_paths_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root, external = Path(directory), Path(outside) / "PRIVATE_USER_NAME.py"
            code = 'def fail():\n    raise ValueError("PRIVATE")\n'
            external_ns = execute_file(external, code)
            linked = root / "backend/app/external_link.py"
            linked.parent.mkdir(parents=True)
            linked.symlink_to(external)
            private_ns = execute_file(root / "backend/data/private-operations/PRIVATE_NAME.py", code)
            run_ns = execute_file(root / "evaluation/tailor-bench/runs-private/PRIVATE_CASE.py", code)
            linked_ns = {}
            exec(compile(code, str(linked), "exec"), linked_ns)
            for namespace in (external_ns, private_ns, run_ns, linked_ns):
                with self.subTest(namespace=tuple(namespace)):
                    try:
                        namespace["fail"]()
                    except ValueError as error:
                        with patch.object(runner, "ROOT", root):
                            result = runner.safe_exception_diagnostic(error)
                    self.assertEqual(result["chain"][0]["repo_frames"], [])
                    self.assertNotIn("PRIVATE", json.dumps(result))
                    self.assertNotIn(str(root), json.dumps(result))
                    self.assertNotIn(str(external), json.dumps(result))

    def test_chain_cycle_and_depth_are_bounded(self):
        first, second = RuntimeError("SECRET_ONE"), ValueError("SECRET_TWO")
        first.__context__, second.__context__ = second, first
        result = runner.safe_exception_diagnostic(first)
        self.assertEqual(len(result["chain"]), 2)
        self.assertTrue(result["chain_truncated"])
        current = ValueError("SECRET_0")
        for _ in range(20):
            newer = RuntimeError("SECRET_NEXT")
            newer.__cause__ = current
            current = newer
        result = runner.safe_exception_diagnostic(current)
        self.assertEqual(len(result["chain"]), 8)
        self.assertTrue(result["chain_truncated"])
        self.assertNotIn("SECRET", json.dumps(result))

    def test_explicit_cause_is_preferred_and_unsafe_type_name_is_sanitized(self):
        unusual = type("SECRET@email.example", (Exception,), {})
        current = unusual("PRIVATE")
        current.__cause__ = TypeError("PRIVATE_CAUSE")
        current.__context__ = ValueError("PRIVATE_CONTEXT")
        result = runner.safe_exception_diagnostic(current)
        self.assertEqual([row["type"] for row in result["chain"]], ["Exception", "TypeError"])
        self.assertEqual(result["chain"][1]["relation"], "cause")
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertNotIn("SECRET", json.dumps(result))

    def test_long_repo_stack_is_bounded_without_source_or_locals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            namespace = execute_file(root / "backend/app/deep.py", '''
def descend(depth):
    private_input = "PRIVATE_INPUT"
    if depth:
        return descend(depth - 1)
    raise ValueError(private_input)
''')
            try:
                namespace["descend"](150)
            except ValueError as error:
                with patch.object(runner, "ROOT", root):
                    result = runner.safe_exception_diagnostic(error)
            self.assertEqual(len(result["chain"][0]["repo_frames"]), 12)
            self.assertTrue(result["chain"][0]["frames_truncated"])
            self.assertNotIn("PRIVATE_INPUT", json.dumps(result))
            self.assertNotIn("private_input", json.dumps(result))

    def test_public_and_private_failed_turns_persist_only_safe_diagnostic(self):
        class Graph:
            async def aget_state_history(self, config):
                if False:
                    yield None

        async def stream(*args, **kwargs):
            if False:
                yield ""
            try:
                raise ValueError("PRIVATE_MODEL_OUTPUT sk-PRIVATE_KEY")
            except ValueError:
                raise RuntimeError("PRIVATE_WRAPPER") from None

        @asynccontextmanager
        async def lock(session_id):
            yield

        modules = {name: ModuleType(name) for name in (
            "app", "app.agents", "app.agents.resume_graph", "app.services",
            "app.services.conversation_store", "app.services.session_store")}
        modules["app.agents.resume_graph"].get_graph = lambda llm: Graph()
        modules["app.agents.resume_graph"].stream_agent = stream
        modules["app.services.conversation_store"].create_conversation = lambda name: {"session_id": "synthetic"}
        modules["app.services.session_store"].load_resume_session = lambda sid: None
        modules["app.services.session_store"].session_lock = lock
        import judge
        for private in (False, True):
            with self.subTest(private=private), tempfile.TemporaryDirectory() as directory:
                case = {"id": "diagnostic-fixture", "private": private, "truth_facts": [],
                        "jd_text": "", "opening_turns": ["PRIVATE_INPUT"], "edit_instructions": []}
                args = SimpleNamespace(turn_timeout=1, max_followups=0, selector_timeout=1, judge_timeout=1)
                with patch.dict(sys.modules, modules), patch.object(runner, "safe_output"), \
                        patch.object(judge, "judge_version", AsyncMock(return_value={"status": "no_draft"})), \
                        patch.object(runner, "measure_rendered_resume", return_value={"status": "unknown"}), \
                        patch.object(runner, "evaluate_real01", return_value={}), \
                        patch.object(runner, "evaluate_edit", return_value={}):
                    asyncio.run(runner.run_case(case, None, None, lambda: SimpleNamespace(calls=[]),
                                               ContextVar("diagnostic-test-counter"), args, Path(directory)))
                turn = json.loads((Path(directory) / case["id"] / "turns.json").read_text())[0]
                self.assertEqual(turn["status"], "error")
                self.assertEqual(turn["error_type"], "RuntimeError")
                diagnostic = turn["error_diagnostic"]
                self.assertEqual([row["type"] for row in diagnostic["chain"]], ["RuntimeError", "ValueError"])
                self.assertNotIn("PRIVATE", json.dumps(diagnostic))
                self.assertNotIn("sk-", json.dumps(diagnostic))
                self.assertNotIn(str(ROOT), json.dumps(diagnostic))


if __name__ == "__main__":
    unittest.main()
