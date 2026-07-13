from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any, cast

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPOSITORY_ROOT / "services" / "worker" / "Dockerfile"
COMPOSE_FILE = REPOSITORY_ROOT / "infra" / "compose" / "local.yml"


class ContainerFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dockerfile = DOCKERFILE.read_text()
        self.compose = cast(dict[str, Any], yaml.safe_load(COMPOSE_FILE.read_text()))

    def service(self, name: str) -> dict[str, Any]:
        services = cast(dict[str, Any], self.compose["services"])
        return cast(dict[str, Any], services[name])

    def test_AT_NFR_03_worker_and_renderer_images_are_reproducibly_pinned(self) -> None:
        expected_fragments = (
            "ARG PYTHON_IMAGE=python:3.12.13-slim-bookworm",
            "ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.7.19",
            "ARG FONTCONFIG_VERSION=2.14.1-4",
            "ARG FONTS_LIBERATION_VERSION=2.1.5-1",
            "ARG FONTS_NOTO_VERSION=20201225-1",
            "uv sync --locked --no-dev --no-install-project",
            "playwright install --with-deps chromium",
            "FROM runtime AS worker",
            "FROM runtime AS renderer",
            "USER 10001:10001",
        )
        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.dockerfile)

        lockfile = (REPOSITORY_ROOT / "uv.lock").read_text()
        self.assertRegex(lockfile, r'name = "playwright"\nversion = "1\.59\.0"')
        self.assertRegex(lockfile, r'name = "weasyprint"\nversion = "65\.1"')
        self.assertRegex(lockfile, r'name = "uvicorn"\nversion = "0\.46\.0"')

    def test_AT_NFR_03_compose_is_host_independent_and_bounded(self) -> None:
        worker = self.service("worker")

        self.assertEqual("mandate-worker:local", worker["image"])
        self.assertEqual("worker", worker["build"]["target"])
        self.assertEqual("10001:10001", worker["user"])
        self.assertTrue(worker["read_only"])
        self.assertEqual(["ALL"], worker["cap_drop"])
        self.assertIn("no-new-privileges:true", worker["security_opt"])
        self.assertEqual("3g", worker["mem_limit"])
        self.assertEqual("1.5", worker["cpus"])
        self.assertEqual(256, worker["pids_limit"])
        self.assertEqual("1g", worker["shm_size"])
        self.assertEqual(["127.0.0.1:8081:8081"], worker["ports"])
        self.assertEqual("1", worker["environment"]["DEMO_MODE"])
        self.assertEqual("memory", worker["environment"]["QUEUE_BACKEND"])

    def test_SEC_05_renderer_has_no_network_or_privileged_write_surface(self) -> None:
        renderer = self.service("renderer")

        self.assertEqual("renderer", renderer["build"]["target"])
        self.assertEqual("none", renderer["network_mode"])
        self.assertNotIn("ports", renderer)
        self.assertNotIn("networks", renderer)
        self.assertTrue(renderer["read_only"])
        self.assertEqual("10001:10001", renderer["user"])
        self.assertEqual(["ALL"], renderer["cap_drop"])
        self.assertIn("no-new-privileges:true", renderer["security_opt"])
        self.assertEqual("1g", renderer["mem_limit"])
        self.assertEqual("0.5", renderer["cpus"])
        self.assertEqual(128, renderer["pids_limit"])
        self.assertTrue(all("noexec" in mount for mount in renderer["tmpfs"]))
        self.assertEqual({"DEMO_MODE": "1"}, renderer["environment"])

    def test_SEC_05_build_context_excludes_credentials(self) -> None:
        dockerignore = (REPOSITORY_ROOT / ".dockerignore").read_text().splitlines()
        required_patterns = {".env", ".env.*", "**/.env", "**/.env.*", "*.pem", "*.key"}

        self.assertTrue(required_patterns.issubset(dockerignore))
        self.assertNotRegex(
            COMPOSE_FILE.read_text(),
            re.compile(r"(API_KEY|SERVICE_ROLE|PASSWORD|SECRET)\s*:", re.IGNORECASE),
        )


if __name__ == "__main__":
    unittest.main()
