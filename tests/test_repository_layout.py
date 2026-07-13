from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class RepositoryLayoutTests(unittest.TestCase):
    """Structural acceptance tests for the Phase 0 monorepo scaffold."""

    def test_AT_NFR_03_monorepo_scaffold_matches_system_spec(self) -> None:
        required_directories = {
            "apps/web/app",
            "apps/web/components",
            "apps/web/lib",
            "apps/web/tests",
            "services/worker/mandate_worker/pipeline",
            "services/worker/mandate_worker/agents",
            "services/worker/mandate_worker/providers",
            "services/worker/mandate_worker/gateway",
            "services/worker/mandate_worker/fetch",
            "services/worker/mandate_worker/render",
            "services/worker/mandate_worker/queue",
            "services/worker/tests",
            "packages/shared-schemas/schemas",
            "packages/shared-schemas/typescript",
            "packages/shared-schemas/python",
            "supabase/migrations",
            "supabase/seed",
            "fixtures/golden",
            "fixtures/demo",
            "infra/compose",
            "infra/caddy",
            "infra/scripts",
        }

        missing = sorted(
            path
            for path in required_directories
            if not (REPOSITORY_ROOT / path).is_dir()
        )
        self.assertEqual([], missing, f"Missing SYSTEM-SPEC directories: {missing}")

    def test_AT_INTAKE_04_scaffold_has_no_confidential_upload_surface(self) -> None:
        forbidden_scaffold_paths = {
            "uploads",
            "data-room",
            "confidential-documents",
            "apps/web/app/upload",
            "apps/web/app/data-room",
        }
        present = sorted(
            path
            for path in forbidden_scaffold_paths
            if (REPOSITORY_ROOT / path).exists()
        )
        self.assertEqual([], present, f"Forbidden MVP scaffold paths found: {present}")


if __name__ == "__main__":
    unittest.main()
