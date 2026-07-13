from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "supabase" / "migrations"


def _sql() -> str:
    matches = sorted(MIGRATIONS.glob("*_entity_resolution_persistence.sql"))
    assert len(matches) == 1
    return matches[0].read_text(encoding="utf-8").lower()


def test_NFR_02_entity_tables_and_outbox_are_force_rls_default_deny() -> None:
    sql = _sql()

    for table in ("entities", "entity_candidates", "outbox"):
        assert f"alter table public.{table} enable row level security;" in sql
        assert f"alter table public.{table} force row level security;" in sql
        assert f"revoke all on table public.{table} from public, anon, authenticated;" in sql
    assert "grant select on table public.entities to authenticated;" in sql
    assert "grant select on table public.entity_candidates to authenticated;" in sql
    assert "grant select on table public.outbox to authenticated" not in sql
    assert (
        "grant execute on function private.light_task_payload_is_valid(jsonb)\n  to service_role;"
        in sql
    )


def test_ENTITY_03_resolution_state_changes_are_database_guarded() -> None:
    sql = _sql()

    assert "create trigger report_requests_enforce_state_transition" in sql
    assert "private.is_legal_request_state_transition(old.state, new.state)" in sql
    assert "'draft'::public.request_state, 'resolving_entity'" in sql
    assert "'resolving_entity'::public.request_state, 'awaiting_entity_confirmation'" in sql
    assert "raise exception 'illegal_request_state_transition'" in sql


def test_ENTITY_02_worker_completion_is_atomic_auditable_and_service_only() -> None:
    sql = _sql()

    completion = sql.split(
        "create or replace function private.complete_entity_resolution", maxsplit=1
    )[1].split("create or replace function private.fail_entity_resolution", maxsplit=1)[0]
    assert "insert into public.entities" in completion
    assert "insert into public.entity_candidates" in completion
    assert "score_audit" in completion
    assert "set state = 'awaiting_entity_confirmation'" in completion
    assert "grant execute on function private.complete_entity_resolution" in completion
    assert "to service_role" in completion
    assert "to authenticated" not in completion


def test_INTAKE_06_entity_resolution_has_no_entitlement_operation() -> None:
    sql = _sql()

    assert "entitlement_ledger" not in sql
    assert "reserve:" not in sql
    assert "consume" not in sql


def test_NFR_01_outbox_payload_is_identifier_only_and_replay_safe() -> None:
    sql = _sql()

    validator = sql.split(
        "create or replace function private.light_task_payload_is_valid", maxsplit=1
    )[1].split("create or replace function private.is_legal_request_state_transition", maxsplit=1)[
        0
    ]
    for key in (
        "schemaversion",
        "taskid",
        "tasktype",
        "reportrequestid",
        "userid",
        "attempt",
        "traceid",
    ):
        assert f"'{key}'" in validator
    for forbidden in (
        "email",
        "full_name",
        "firm",
        "billing",
        "letterhead",
        "description",
    ):
        assert f"'{forbidden}'" not in validator
    assert "idempotency_key text not null unique" in sql
    assert "private.dispatch_next_outbox()" in sql
    assert "for update skip locked" in sql


def test_NFR_01_terminal_light_task_failure_is_no_charge_and_audited() -> None:
    sql = _sql()

    failure = sql.split("create or replace function private.fail_entity_resolution", maxsplit=1)[
        1
    ].split("select pgmq.create", maxsplit=1)[0]
    assert "set state = 'failed_no_charge'" in failure
    assert "set last_error_code = p_error_code" in failure
    assert "grant execute on function private.fail_entity_resolution" in failure
    assert "to service_role" in failure
    assert "to authenticated" not in failure
