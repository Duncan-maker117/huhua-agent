from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from persona_support import checks, report, golden_run


class PersonaReportTests(unittest.TestCase):
    def test_one_run_lists_every_stable_assertion(self):
        run = golden_run()
        markdown = report.render_report([run])
        for row in checks.evaluate_run(run):
            self.assertIn(row["id"], markdown)
        self.assertNotIn("| FAIL |", markdown)
        self.assertIn("PASS", markdown)
        self.assertIn("first", report.render_report([golden_run(run_id="first")]))

    def test_two_runs_show_improvements_regressions_missing_and_escaped_proof(self):
        old = golden_run(("tech", "ops"), run_id="before")
        new = golden_run(("tech", "service"), run_id="after")
        old["personas"]["tech"]["turns"][1]["resume_data"]["education"][0]["major"] = "请把实习经历润色得更"
        new["personas"]["tech"]["turns"][2]["resume_data"]["work_experience"][0]["bullets"][2] = "420ms → 170ms"
        new["personas"]["tech"]["turns"][2]["reply"] = "需要你补充A|B\n需要你补充C"
        markdown = report.render_report([old, new])
        self.assertIn("改善", markdown)
        self.assertIn("退化", markdown)
        self.assertIn("新增", markdown)
        self.assertIn("缺失", markdown)
        self.assertIn("MISSING", markdown)
        self.assertIn(r"A\|B<br>", markdown)

    def test_multiple_runs_warn_if_fixture_or_recovery_policies_differ(self):
        first, second = golden_run(), golden_run(with_recovery=True)
        second["fixture_sha256"] = "other"
        text = report.render_report([first, second, deepcopy(first)])
        self.assertIn("不是同脚本", text)
        self.assertEqual(text.count("| tech.correction_190 |"), 1)

    def test_cached_checks_cannot_mask_error_or_data_regression(self):
        run = golden_run(("service",))
        run["personas"]["service"]["error"] = "HTTP 503"
        run["personas"]["service"]["checks"] = [{"id": "service.common.rounds_complete", "status": "pass"}]
        index = report.result_index(run)
        self.assertEqual(index["service.common.rounds_complete"]["status"], "fail")

    def test_loading_directory_and_file_validation_and_cli_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = golden_run(("tech",))
            (root / "run.json").write_text(json.dumps(run), encoding="utf-8")
            self.assertEqual(report.load_run(root), run)
            self.assertEqual(report.load_run(root / "run.json"), run)
            with patch.object(report, "HERE", root):
                output = root / "reports" / "report.md"
                self.assertEqual(report.main([str(root), "--output", str(output)]), 0)
                self.assertIn("tech.correction_190", output.read_text())
                stream = io.StringIO()
                with redirect_stdout(stream):
                    self.assertEqual(report.main([str(root)]), 0)
                self.assertTrue(stream.getvalue().startswith("# 五人物"))
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    report.main([str(root), "--output", str(root.parent / "outside.md")])
            (root / "run.json").write_text("{}")
            with self.assertRaises(ValueError):
                report.load_run(root)
        with self.assertRaises(ValueError):
            report.render_report([])
