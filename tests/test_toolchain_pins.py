from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class ToolchainPinTests(unittest.TestCase):
    def test_NFR_03_runtime_and_package_manager_lines_are_pinned(self) -> None:
        package_json = json.loads((REPOSITORY_ROOT / "package.json").read_text())
        pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())

        self.assertEqual("pnpm@10.13.1", package_json["packageManager"])
        self.assertEqual("22.16.x", package_json["engines"]["node"])
        self.assertEqual(">=3.12,<3.13", pyproject["project"]["requires-python"])


if __name__ == "__main__":
    unittest.main()
