from __future__ import annotations

import re
import unittest
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"


class CiPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = WORKFLOW_PATH.read_text()
        workflow = cast(dict[str, Any], yaml.safe_load(self.source))
        self.jobs = cast(dict[str, Any], workflow["jobs"])

    def job(self, name: str) -> dict[str, Any]:
        return cast(dict[str, Any], self.jobs[name])

    def step_source(self, job_name: str) -> str:
        steps = cast(list[dict[str, Any]], self.job(job_name)["steps"])
        return "\n".join(str(step.get("run", "")) for step in steps)

    def test_NFR_03_TEST_PLAN_11_stages_one_to_five_are_ordered(self) -> None:
        expected = [
            "stage_1_quality",
            "stage_2_security",
            "stage_3_contracts",
            "stage_4_unit",
            "stage_5_integration",
        ]
        self.assertEqual(expected, list(self.jobs))
        for previous, current in pairwise(expected):
            with self.subTest(stage=current):
                self.assertEqual(previous, self.job(current)["needs"])

    def test_SEC_10_secret_scan_covers_history_and_redacts_output(self) -> None:
        security = self.job("stage_2_security")
        steps = cast(list[dict[str, Any]], security["steps"])
        checkout = steps[0]
        commands = self.step_source("stage_2_security")

        self.assertEqual(0, checkout["with"]["fetch-depth"])
        self.assertIn('gitleaks git --log-opts="--all"', commands)
        self.assertIn("--redact", commands)
        self.assertRegex(commands, re.compile(r"GITLEAKS_SHA256.*sha256sum", re.DOTALL))

    def test_SEC_12_dependency_and_container_scans_are_blocking_and_pinned(self) -> None:
        commands = self.step_source("stage_2_security")

        self.assertIn("pnpm audit --audit-level=high", commands)
        self.assertIn("pip-audit --requirement", commands)
        self.assertIn("TRIVY_SHA256", commands)
        self.assertEqual(2, commands.count("trivy image --exit-code 1"))
        self.assertEqual(2, commands.count("--severity HIGH,CRITICAL"))
        self.assertNotIn("continue-on-error", self.source)
        self.assertNotRegex(self.source, re.compile(r"uses: [^\n]+@(main|master|v\d+)\s*$"))

    def test_NFR_02_stage_five_runs_real_database_and_container_integration(self) -> None:
        commands = self.step_source("stage_5_integration")

        expected = (
            "supabase db start",
            "supabase db reset",
            "supabase test db --local",
            "supabase db lint --local",
            "docker compose --file infra/compose/local.yml up --build",
            "scripts/verify_container_runtime.py",
        )
        for fragment in expected:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, commands)


if __name__ == "__main__":
    unittest.main()
