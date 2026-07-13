"""Verify the live Compose containers match the NFR-03/SEC-05 contract."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPOSITORY_ROOT / "infra" / "compose" / "local.yml"
COMPOSE = ["docker", "compose", "--file", str(COMPOSE_FILE)]


def command(*arguments: str) -> str:
    return subprocess.check_output([*COMPOSE, *arguments], text=True).strip()


def inspect_service(name: str) -> dict[str, Any]:
    container_id = command("ps", "--quiet", name)
    if not container_id:
        raise AssertionError(f"{name} container is not running")
    raw = subprocess.check_output(["docker", "inspect", container_id], text=True)
    return cast(dict[str, Any], json.loads(raw)[0])


def assert_common_sandbox(container: dict[str, Any]) -> None:
    config = cast(dict[str, Any], container["Config"])
    host = cast(dict[str, Any], container["HostConfig"])

    assert config["User"] == "10001:10001"
    assert host["ReadonlyRootfs"] is True
    assert host["CapDrop"] == ["ALL"]
    assert any(str(option).startswith("no-new-privileges") for option in host["SecurityOpt"])


def assert_demo_fixture_runtime() -> None:
    probe = (
        "from mandate_worker.fixtures import AdapterCapability; "
        "from mandate_worker.main import app; "
        "plan = app.state.runtime_adapter_plan; "
        "assert plan.zero_spend; "
        "assert plan.fixture_revision == '2026-07-13.2'; "
        "assert set(plan.bindings) == set(AdapterCapability)"
    )
    subprocess.check_call([*COMPOSE, "exec", "--no-TTY", "worker", "python", "-c", probe])


def main() -> None:
    worker = inspect_service("worker")
    renderer = inspect_service("renderer")
    worker_host = cast(dict[str, Any], worker["HostConfig"])
    renderer_host = cast(dict[str, Any], renderer["HostConfig"])

    assert_common_sandbox(worker)
    assert_common_sandbox(renderer)

    assert worker_host["Memory"] == 3 * 1024**3
    assert worker_host["NanoCpus"] == 1_500_000_000
    assert worker_host["PidsLimit"] == 256

    assert renderer_host["NetworkMode"] == "none"
    assert renderer_host["Memory"] == 1024**3
    assert renderer_host["NanoCpus"] == 500_000_000
    assert renderer_host["PidsLimit"] == 128
    assert set(renderer_host["Tmpfs"]) == {"/tmp", "/home/mandate/.cache"}

    for container in (worker, renderer):
        state = cast(dict[str, Any], container["State"])
        health = cast(dict[str, Any], state["Health"])
        assert health["Status"] == "healthy"

    assert_demo_fixture_runtime()


if __name__ == "__main__":
    main()
