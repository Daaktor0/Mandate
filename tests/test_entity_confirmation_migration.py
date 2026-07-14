from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "supabase" / "migrations"


def _sql() -> str:
    matches = sorted(MIGRATIONS.glob("*_entity_confirmation.sql"))
    assert len(matches) == 1
    return matches[0].read_text(encoding="utf-8").lower()


def test_ENTITY_03_confirmation_is_tenant_scoped_and_database_guarded() -> None:
    sql = _sql()

    function = sql.split(
        "create or replace function public.confirm_report_request_entity", maxsplit=1
    )[1]
    assert "security definer" in function
    assert "set search_path = ''" in function
    assert "v_user_id uuid := (select auth.uid())" in function
    assert "request.user_id = v_user_id" in function
    assert "for update" in function
    assert "confirmation_state_conflict" in function
    assert "entity_candidate_not_found" in function
    assert "set confirmed_entity_id = v_candidate.entity_id" in function
    assert "set is_selected = (id = p_candidate_id)" in function


def test_ENTITY_04_none_and_refine_cannot_accept_narrative() -> None:
    sql = _sql()

    assert "p_legal_name text" in sql
    assert "p_cin text" in sql
    assert "p_state text" in sql
    for forbidden in (
        "p_description",
        "p_transaction",
        "p_mandate",
        "p_document",
        "p_upload",
    ):
        assert forbidden not in sql
    assert "state = 'draft'" in sql
    assert "state = 'resolving_entity'" in sql
    assert "delete from public.entity_candidates" in sql
    assert "resolution_legal_name_hint" in sql
    assert "resolution_cin_hint" in sql
    assert "resolution_state_hint" in sql
    assert "drop constraint report_requests_exactly_one_input" not in sql


def test_ENTITY_07_related_scope_is_bounded_unique_and_explicitly_proposed() -> None:
    sql = _sql()

    assert "cardinality(related_entity_ids) <= 2" in sql
    assert "private.uuid_array_is_unique(related_entity_ids)" in sql
    assert "not confirmed_entity_id = any(related_entity_ids)" in sql
    assert "nullif(candidate.candidate_payload ->> 'relatedentityreason', '') is not null" in sql
    assert "invalid_related_entity_scope" in sql


def test_NFR_01_confirmation_replay_and_refine_queue_are_fail_closed() -> None:
    sql = _sql()

    assert "create table private.entity_confirmation_commands" in sql
    assert "primary key (user_id, report_request_id, idempotency_key)" in sql
    assert "idempotency_conflict" in sql
    refine = sql.split("else\n    if (", maxsplit=1)[1]
    for key in (
        "schemaversion",
        "taskid",
        "tasktype",
        "reportrequestid",
        "userid",
        "attempt",
        "traceid",
    ):
        assert f"'{key}'" in refine
    for forbidden in (
        "email",
        "full_name",
        "firm",
        "billing",
        "letterhead",
        "description",
    ):
        assert f"'{forbidden}'" not in refine


def test_INTAKE_06_confirmation_has_no_entitlement_surface() -> None:
    sql = _sql()

    assert "entitlement_ledger" not in sql
    assert "reserve:" not in sql
    assert "consume" not in sql
