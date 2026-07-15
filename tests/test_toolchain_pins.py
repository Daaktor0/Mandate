from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path
from typing import Any, cast

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class ToolchainPinTests(unittest.TestCase):
    def test_NFR_03_runtime_and_package_manager_lines_are_pinned(self) -> None:
        package_json = json.loads((REPOSITORY_ROOT / "package.json").read_text())
        pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())

        self.assertEqual("pnpm@11.13.0", package_json["packageManager"])
        self.assertEqual("22.16.x", package_json["engines"]["node"])
        self.assertEqual("0.28.1", package_json["optionalDependencies"]["@esbuild/linux-x64"])
        self.assertNotIn("pnpm", package_json)
        self.assertEqual(">=3.12,<3.13", pyproject["project"]["requires-python"])

    def test_SEC_12_web_runtime_uses_security_patched_release_lines(self) -> None:
        package_json = json.loads((REPOSITORY_ROOT / "apps" / "web" / "package.json").read_text())

        self.assertEqual("15.5.18", package_json["dependencies"]["next"])
        self.assertEqual("19.1.5", package_json["dependencies"]["react"])
        self.assertEqual("19.1.5", package_json["dependencies"]["react-dom"])
        self.assertEqual("15.5.18", package_json["devDependencies"]["eslint-config-next"])

    def test_SEC_12_dependency_build_scripts_are_explicitly_allowlisted(self) -> None:
        workspace = cast(
            dict[str, Any],
            yaml.safe_load((REPOSITORY_ROOT / "pnpm-workspace.yaml").read_text()),
        )

        self.assertEqual({"postcss": "8.5.10"}, workspace["overrides"])
        self.assertEqual(
            {"esbuild": True, "sharp": False, "unrs-resolver": False},
            workspace["allowBuilds"],
        )
        self.assertNotIn("onlyBuiltDependencies", workspace)
        self.assertNotIn("ignoredBuiltDependencies", workspace)
        self.assertEqual(["current", "linux"], workspace["supportedArchitectures"]["os"])
        self.assertEqual(["current", "x64"], workspace["supportedArchitectures"]["cpu"])
        self.assertNotIn("dangerouslyAllowAllBuilds", workspace)


if __name__ == "__main__":
    unittest.main()
