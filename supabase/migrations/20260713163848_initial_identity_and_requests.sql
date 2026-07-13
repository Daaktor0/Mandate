begin;

create schema if not exists private;
revoke all on schema private from public, anon;

create type public.trial_status as enum (
  'ineligible',
  'eligible',
  'claimed',
  'blocked'
);

create type public.input_kind as enum (
  'website',
  'legal_name'
);

create type public.request_state as enum (
  'draft',
  'resolving_entity',
  'awaiting_entity_confirmation',
  'preliminary_research',
  'awaiting_clarification',
  'queued',
  'researching',
  'verifying',
  'composing',
  'rendering',
  'completed',
  'failed_no_charge',
  'retry_wait',
  'failed_restored',
  'cancelled_restored'
);

create type public.client_role as enum (
  'company_promoter',
  'investor_acquirer',
  'seller_transferor',
  'other'
);

create type public.cross_border_answer as enum (
  'yes',
  'no',
  'unknown'
);

create table public.users_profile (
  user_id uuid primary key references auth.users (id) on delete restrict,
  full_name text not null
    check (char_length(full_name) between 1 and 200),
  country text not null
    check (country ~ '^[A-Z]{2}$'),
  professional_role text not null
    check (professional_role in ('partner', 'associate', 'other')),
  phone_e164 text null
    check (phone_e164 is null or phone_e164 ~ '^\\+[1-9][0-9]{7,14}$'),
  phone_verified_at timestamptz null,
  trial_status public.trial_status not null default 'ineligible',
  trial_risk_flags jsonb not null default '{}'::jsonb
    check (jsonb_typeof(trial_risk_flags) = 'object'),
  is_admin boolean not null default false,
  terms_accepted_at timestamptz null,
  privacy_accepted_at timestamptz null,
  deleted_at timestamptz null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint users_profile_phone_verification_consistent check (
    phone_verified_at is null or phone_e164 is not null
  )
);

comment on table public.users_profile is
  'Individual Mandate user profile. Identity, billing and firm data must never enter provider payloads.';
comment on column public.users_profile.is_admin is
  'Server-authoritative admin flag. Never derive authorisation from user-editable JWT metadata.';

create or replace function private.is_admin()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(
    (
      select profile.is_admin
      from public.users_profile as profile
      where profile.user_id = (select auth.uid())
        and profile.deleted_at is null
    ),
    false
  );
$$;

revoke all on function private.is_admin() from public, anon;
grant usage on schema private to authenticated, service_role;
grant execute on function private.is_admin() to authenticated, service_role;

create table public.report_requests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users_profile (user_id) on delete restrict,
  input_kind public.input_kind not null,
  input_url text null,
  input_legal_name text null,
  input_cin text null
    check (
      input_cin is null
      or input_cin ~ '^[UL][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$'
    ),
  confidential_ack_at timestamptz not null,
  confirmed_entity_id uuid null,
  related_entity_ids uuid[] not null default '{}'::uuid[],
  client_role public.client_role null,
  transaction_category text null
    check (
      transaction_category is null
      or char_length(transaction_category) between 1 and 100
    ),
  cross_border public.cross_border_answer null,
  clarifications jsonb null
    check (clarifications is null or jsonb_typeof(clarifications) = 'array'),
  clarification_answers jsonb null
    check (clarification_answers is null or jsonb_typeof(clarification_answers) = 'object'),
  sparse_data_disclosed_at timestamptz null,
  state public.request_state not null default 'draft',
  active_job_id uuid null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint report_requests_exactly_one_input check (
    (
      input_kind = 'website'
      and input_url is not null
      and input_legal_name is null
    )
    or
    (
      input_kind = 'legal_name'
      and input_url is null
      and input_legal_name is not null
    )
  ),
  constraint report_requests_input_url_bounded check (
    input_url is null or char_length(input_url) between 1 and 2048
  ),
  constraint report_requests_input_legal_name_bounded check (
    input_legal_name is null
    or char_length(input_legal_name) between 1 and 300
  )
);

comment on table public.report_requests is
  'One user intent to prepare one Mandate Brief; no confidential narrative or upload fields are permitted.';
comment on column public.report_requests.confirmed_entity_id is
  'Foreign key is added with the entities table in Phase 1; paid generation remains unreachable before confirmation.';
comment on column public.report_requests.active_job_id is
  'Foreign key is added with report_jobs; null throughout the pre-generation foundation.';
comment on column public.report_requests.related_entity_ids is
  'The product cap is intentionally deferred pending founder confirmation B13.';

create index report_requests_user_created_idx
  on public.report_requests (user_id, created_at desc);

create or replace function private.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

revoke all on function private.set_updated_at() from public, anon, authenticated;

create trigger users_profile_set_updated_at
before update on public.users_profile
for each row execute function private.set_updated_at();

create trigger report_requests_set_updated_at
before update on public.report_requests
for each row execute function private.set_updated_at();

alter table public.users_profile enable row level security;
alter table public.users_profile force row level security;
alter table public.report_requests enable row level security;
alter table public.report_requests force row level security;

revoke all on table public.users_profile from public, anon, authenticated;
revoke all on table public.report_requests from public, anon, authenticated;

-- The authenticated role can reach SELECT through the Data API, but RLS has no
-- user policy in this foundation migration. That deliberate absence is the
-- default-deny baseline; phase-specific migrations add the minimum policies
-- alongside the API operations that require them.
grant select on table public.users_profile to authenticated;
grant select on table public.report_requests to authenticated;

grant select, insert, update, delete on table public.users_profile to service_role;
grant select, insert, update, delete on table public.report_requests to service_role;
grant usage on type public.trial_status to service_role;
grant usage on type public.input_kind to service_role;
grant usage on type public.request_state to service_role;
grant usage on type public.client_role to service_role;
grant usage on type public.cross_border_answer to service_role;

commit;
