from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "supabase" / "migrations"
CONFIG = ROOT / "supabase" / "config.toml"


def _foundation_sql() -> str:
    matches = sorted(MIGRATIONS.glob("*_initial_identity_and_requests.sql"))
    assert len(matches) == 1
    return matches[0].read_text(encoding="utf-8").lower()


def test_NFR_02_supabase_local_stack_targets_postgres_15_without_model_access() -> None:
    config = CONFIG.read_text(encoding="utf-8")

    assert 'project_id = "mandate"' in config
    assert "major_version = 15" in config
    seed_config = (
        "[db.seed]\n"
        "# If enabled, seeds the database after migrations during a db reset.\n"
        "enabled = false"
    )
    assert seed_config in config
    assert 'openai_api_key = ""' in config
    assert "env(OPENAI_API_KEY)" not in config


def test_SEC_01_local_auth_disables_email_password_signups() -> None:
    config = CONFIG.read_text(encoding="utf-8")
    email_auth = config.split("[auth.email]", maxsplit=1)[1].split("[auth.sms]", maxsplit=1)[0]

    assert "enable_signup = false" in email_auth


def test_NFR_02_first_user_tables_are_force_rls_default_deny() -> None:
    sql = _foundation_sql()

    for table in ("users_profile", "report_requests"):
        assert f"alter table public.{table} enable row level security;" in sql
        assert f"alter table public.{table} force row level security;" in sql
        assert f"revoke all on table public.{table} from public, anon, authenticated;" in sql

    assert "create policy" not in sql
    assert "grant select on table public.users_profile to authenticated;" in sql
    assert "grant select on table public.report_requests to authenticated;" in sql


def test_NFR_02_admin_lookup_is_private_and_fail_closed() -> None:
    sql = _foundation_sql()

    assert "create or replace function private.is_admin()" in sql
    assert "security definer" in sql
    assert "set search_path = ''" in sql
    assert "profile.user_id = (select auth.uid())" in sql
    assert "and profile.deleted_at is null" in sql
    assert "revoke all on function private.is_admin() from public, anon;" in sql
    assert "grant execute on function private.is_admin() to authenticated, service_role;" in sql
    assert "function public.is_admin" not in sql


def test_INTAKE_04_report_requests_has_no_confidential_input_surface() -> None:
    sql = _foundation_sql()
    table_sql = sql.split("create table public.report_requests", maxsplit=1)[1].split(
        "comment on table public.report_requests", maxsplit=1
    )[0]

    forbidden_columns = (
        "description",
        "free_text",
        "document",
        "upload",
        "email",
        "full_name",
        "firm",
        "billing",
        "letterhead",
    )
    for column in forbidden_columns:
        assert re.search(rf"^\s*{column}\s+", table_sql, flags=re.MULTILINE) is None

    assert "confidential_ack_at timestamptz not null" in table_sql
    assert "report_requests_exactly_one_input" in table_sql
