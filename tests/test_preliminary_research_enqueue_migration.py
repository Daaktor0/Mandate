from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "supabase" / "migrations"
MIGRATION = MIGRATIONS / "20260719100000_preliminary_research_enqueue.sql"


def _sql() -> str:
    assert MIGRATION.exists()
    return MIGRATION.read_text(encoding="utf-8").lower()


def _preliminary_enqueue(sql: str) -> str:
    return sql.split("v_outbox_key := 'preliminary:'", maxsplit=1)[1].split(
        "v_response := jsonb_build_object",
        maxsplit=1,
    )[0]


def test_ENTITY_08_preliminary_research_enqueue_shape_is_identifier_only() -> None:
    sql = _sql()
    enqueue = _preliminary_enqueue(sql)
    payload = enqueue.split("jsonb_build_object(", maxsplit=1)[1].split(
        "),\n      v_outbox_key",
        maxsplit=1,
    )[0]

    assert "'preliminary:' || v_user_id::text" in sql
    assert "'mandate_light_tasks'" in enqueue
    assert "'tasktype', 'preliminary_research'" in payload
    assert "entityid" not in enqueue
    assert re.findall(r"'([^']+)'", payload) == [
        "schemaversion",
        "taskid",
        "tasktype",
        "preliminary_research",
        "reportrequestid",
        "userid",
        "attempt",
        "traceid",
    ]


def test_ENTITY_08_preliminary_research_enqueue_preserves_rpc_security_shape() -> None:
    sql = _sql()
    function = sql.split(
        "create or replace function public.confirm_report_request_entity",
        maxsplit=1,
    )[1]

    assert sql.startswith("begin;")
    assert sql.rstrip().endswith("commit;")
    assert "security definer" in function
    assert "set search_path = ''" in function
    assert "revoke all on function public.confirm_report_request_entity" in sql
    assert ") from public, anon;" in sql
    assert ") to authenticated;" in sql
