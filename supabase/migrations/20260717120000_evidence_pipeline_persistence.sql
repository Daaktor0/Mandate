begin;

create type public.job_status as enum (
  'queued',
  'leased',
  'running',
  'retry_wait',
  'succeeded',
  'failed_terminal',
  'cancelled'
);

create type public.evidence_extraction_method as enum (
  'static_html',
  'rendered',
  'api',
  'fixture'
);

create type public.evidence_retention_class as enum (
  'with_report',
  'raw_30d'
);

create type public.claim_type as enum (
  'verified_fact',
  'company_claim',
  'third_party_report',
  'inference',
  'conflicted',
  'not_publicly_available'
);

create type public.claim_confidence as enum (
  'high',
  'medium',
  'low'
);

create type public.claim_freshness as enum (
  'current',
  'recent',
  'dated',
  'stale'
);

create type public.claim_verifier_status as enum (
  'pending',
  'approved',
  'rejected',
  'conflicted'
);

create type public.agent_run_result as enum (
  'ok',
  'schema_retry_ok',
  'error',
  'refused'
);

create table public.report_jobs (
  id uuid primary key default gen_random_uuid(),
  report_request_id uuid not null
    references public.report_requests (id) on delete restrict,
  user_id uuid not null
    references public.users_profile (user_id) on delete restrict,
  confirmed_entity_id uuid not null
    references public.entities (id) on delete restrict,
  attempt smallint not null default 1
    check (attempt between 1 and 100),
  queue_msg_id bigint null
    check (queue_msg_id is null or queue_msg_id > 0),
  trace_id text not null
    check (trace_id ~ '^[A-Za-z0-9._:-]{8,128}$'),
  budget_profile text not null default 'mvp-standard'
    check (budget_profile ~ '^[A-Za-z0-9._:-]{1,100}$'),
  prompt_bundle_version text not null
    check (prompt_bundle_version ~ '^[A-Za-z0-9.-]{1,64}$'),
  status public.job_status not null default 'queued',
  current_stage text null
    check (current_stage is null or current_stage ~ '^[a-z][a-z0-9_]{2,63}$'),
  leased_until timestamptz null,
  started_at timestamptz null,
  finished_at timestamptz null,
  failure_code text null
    check (failure_code is null or failure_code ~ '^[a-z0-9_:-]{1,100}$'),
  failure_detail text null
    check (failure_detail is null or char_length(failure_detail) <= 500),
  cost_total_inr numeric(10, 4) not null default 0
    check (cost_total_inr >= 0),
  quality_gate_result jsonb null
    check (quality_gate_result is null or jsonb_typeof(quality_gate_result) = 'object'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint report_jobs_finished_after_start check (
    finished_at is null or started_at is not null
  )
);

comment on table public.report_jobs is
  'Identifier-only generation attempts. Prompts, evidence text and user matter narrative are not stored here.';
comment on column public.report_jobs.failure_detail is
  'Bounded, redacted diagnostic detail for service-side reconciliation; never raw provider output.';

create index report_jobs_request_idx
  on public.report_jobs (report_request_id, created_at desc);

create unique index report_jobs_one_active_request_idx
  on public.report_jobs (report_request_id)
  where status in ('queued', 'leased', 'running', 'retry_wait');

alter table public.report_requests
  add constraint report_requests_active_job_fk
  foreign key (active_job_id)
  references public.report_jobs (id)
  on delete set null;

create or replace function private.set_report_job_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

revoke all on function private.set_report_job_updated_at() from public, anon, authenticated;

create trigger report_jobs_set_updated_at
before update on public.report_jobs
for each row execute function private.set_report_job_updated_at();

create table public.job_checkpoints (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null
    references public.report_jobs (id) on delete cascade,
  stage text not null
    check (stage ~ '^[a-z][a-z0-9_]{2,63}$'),
  attempt smallint not null
    check (attempt between 1 and 100),
  payload jsonb not null
    check (jsonb_typeof(payload) in ('object', 'array')),
  payload_hash text not null
    check (payload_hash ~ '^[a-f0-9]{64}$'),
  completed_at timestamptz not null default now(),
  unique (job_id, stage, attempt)
);

comment on table public.job_checkpoints is
  'Validated stage outputs and SHA-256 integrity records used to resume jobs after redelivery.';

create index job_checkpoints_job_stage_idx
  on public.job_checkpoints (job_id, completed_at desc);

create or replace function private.evidence_entity_identifiers_is_valid(p_value jsonb)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select
    jsonb_typeof(p_value) = 'object'
    and p_value ?& array['legalNames', 'cins', 'addresses']
    and p_value - array['legalNames', 'cins', 'addresses'] = '{}'::jsonb
    and case
      when jsonb_typeof(p_value -> 'legalNames') = 'array'
      then jsonb_array_length(p_value -> 'legalNames') <= 50
      else false
    end
    and case
      when jsonb_typeof(p_value -> 'cins') = 'array'
      then jsonb_array_length(p_value -> 'cins') <= 20
      else false
    end
    and case
      when jsonb_typeof(p_value -> 'addresses') = 'array'
      then jsonb_array_length(p_value -> 'addresses') <= 20
      else false
    end
    and case
      when jsonb_typeof(p_value -> 'legalNames') = 'array'
      then not exists (
        select 1
        from jsonb_array_elements_text(p_value -> 'legalNames') as item(value)
        where char_length(item.value) not between 1 and 300
      )
      else false
    end
    and case
      when jsonb_typeof(p_value -> 'cins') = 'array'
      then not exists (
        select 1
        from jsonb_array_elements_text(p_value -> 'cins') as item(value)
        where item.value !~ '^[UL][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$'
      )
      else false
    end
    and case
      when jsonb_typeof(p_value -> 'addresses') = 'array'
      then not exists (
        select 1
        from jsonb_array_elements_text(p_value -> 'addresses') as item(value)
        where char_length(item.value) not between 1 and 500
      )
      else false
    end;
$$;

revoke all on function private.evidence_entity_identifiers_is_valid(jsonb)
  from public, anon, authenticated;
grant execute on function private.evidence_entity_identifiers_is_valid(jsonb) to service_role;

create table public.evidence (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null
    references public.report_jobs (id) on delete cascade,
  entity_id uuid null
    references public.entities (id) on delete restrict,
  url text not null
    check (char_length(url) between 1 and 2048 and url ~* '^https?://'),
  canonical_url text not null
    check (char_length(canonical_url) between 1 and 2048 and canonical_url ~* '^https?://'),
  title text not null
    check (char_length(title) between 1 and 500),
  publisher text not null
    check (char_length(publisher) between 1 and 300),
  source_tier smallint not null
    check (source_tier between 1 and 5),
  publication_date date null,
  accessed_at timestamptz not null,
  excerpt text not null
    check (char_length(excerpt) between 1 and 4000),
  content_hash text not null
    check (content_hash ~ '^[a-f0-9]{64}$'),
  entity_identifiers jsonb not null
    check (private.evidence_entity_identifiers_is_valid(entity_identifiers)),
  jurisdiction_relevance text null
    check (jurisdiction_relevance is null or char_length(jurisdiction_relevance) <= 500),
  company_controlled boolean not null,
  extraction_method public.evidence_extraction_method not null,
  prompt_injection_suspected boolean not null default false,
  licence_notes text null
    check (licence_notes is null or char_length(licence_notes) <= 500),
  raw_body_storage_key text null
    check (raw_body_storage_key is null or char_length(raw_body_storage_key) <= 500),
  retention_class public.evidence_retention_class not null,
  created_at timestamptz not null default now()
);

comment on table public.evidence is
  'Bounded, source-tiered evidence objects stored separately from report prose; only the later admission step may insert them.';
comment on column public.evidence.excerpt is
  'Short licensed excerpt only; raw page bodies remain storage references subject to retention policy.';

create index evidence_job_idx
  on public.evidence (job_id, accessed_at desc);
create index evidence_entity_idx
  on public.evidence (entity_id, accessed_at desc);

create table public.claims (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null
    references public.report_jobs (id) on delete cascade,
  entity_id uuid not null
    references public.entities (id) on delete restrict,
  subject text not null
    check (char_length(subject) between 1 and 500),
  predicate text not null
    check (char_length(predicate) between 1 and 200),
  object text not null
    check (char_length(object) between 1 and 2000),
  display_text text not null
    check (char_length(display_text) between 1 and 3000),
  claim_type public.claim_type not null,
  evidence_ids uuid[] not null default '{}'::uuid[],
  period text null
    check (period is null or char_length(period) <= 200),
  confidence public.claim_confidence not null,
  freshness public.claim_freshness not null,
  contradiction_group uuid null,
  verifier_status public.claim_verifier_status not null default 'pending',
  report_sections text[] not null default '{}'::text[]
    check (cardinality(report_sections) <= 20 and array_position(report_sections, '') is null),
  model_prompt_version text not null
    check (model_prompt_version ~ '^[A-Za-z0-9.-]{1,100}$'),
  is_material boolean not null,
  created_at timestamptz not null default now(),
  constraint claims_material_evidence_check check (
    is_material = false or cardinality(evidence_ids) > 0
  ),
  constraint claims_evidence_ids_unique check (private.uuid_array_is_unique(evidence_ids))
);

comment on table public.claims is
  'Normalised claim triples with provenance and verifier metadata; material claims cannot exist without evidence IDs.';

create index claims_job_idx
  on public.claims (job_id, created_at);
create index claims_entity_idx
  on public.claims (entity_id, verifier_status);

create or replace function private.validate_claim_evidence_refs()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if exists (
    select 1
    from unnest(new.evidence_ids) as requested(evidence_id)
    where not exists (
      select 1
      from public.evidence as evidence_row
      where evidence_row.id = requested.evidence_id
        and evidence_row.job_id = new.job_id
    )
  ) then
    raise exception 'CLAIM_EVIDENCE_REFERENCE_INVALID' using errcode = '23514';
  end if;
  return new;
end;
$$;

revoke all on function private.validate_claim_evidence_refs() from public, anon, authenticated;

create trigger claims_validate_evidence_refs
before insert or update on public.claims
for each row execute function private.validate_claim_evidence_refs();

create table public.agent_runs (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null
    references public.report_jobs (id) on delete cascade,
  agent_type text not null
    check (agent_type ~ '^[a-z][a-z0-9_]{2,63}$'),
  model_id text not null
    check (char_length(model_id) between 1 and 128),
  provider text not null
    check (char_length(provider) between 1 and 50),
  prompt_version text not null
    check (prompt_version ~ '^[A-Za-z0-9.-]{1,64}$'),
  routing_version text not null
    check (char_length(routing_version) between 1 and 64),
  input_tokens integer not null
    check (input_tokens >= 0),
  output_tokens integer not null
    check (output_tokens >= 0),
  cost_inr numeric(10, 6) not null default 0
    check (cost_inr >= 0),
  latency_ms integer not null
    check (latency_ms >= 0),
  zdr_enforced boolean not null
    check (zdr_enforced),
  result public.agent_run_result not null,
  error_detail text null
    check (error_detail is null or char_length(error_detail) <= 200),
  created_at timestamptz not null default now()
);

comment on table public.agent_runs is
  'Sanitised model-call audit records. ZDR proof is structurally required; payloads and prompts are never stored.';

create index agent_runs_job_idx
  on public.agent_runs (job_id, created_at);

create table public.provider_cost_events (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null
    references public.report_jobs (id) on delete cascade,
  provider text not null
    check (char_length(provider) between 1 and 50),
  unit text not null
    check (unit ~ '^[a-z][a-z0-9_.:-]{0,63}$'),
  quantity numeric(14, 6) not null
    check (quantity >= 0),
  cost_inr numeric(10, 6) not null
    check (cost_inr >= 0),
  created_at timestamptz not null default now()
);

comment on table public.provider_cost_events is
  'Per-call external cost ledger; every event is attributable to one generation job.';

create index provider_cost_events_job_idx
  on public.provider_cost_events (job_id, created_at);

alter table public.report_jobs enable row level security;
alter table public.report_jobs force row level security;
alter table public.job_checkpoints enable row level security;
alter table public.job_checkpoints force row level security;
alter table public.evidence enable row level security;
alter table public.evidence force row level security;
alter table public.claims enable row level security;
alter table public.claims force row level security;
alter table public.agent_runs enable row level security;
alter table public.agent_runs force row level security;
alter table public.provider_cost_events enable row level security;
alter table public.provider_cost_events force row level security;

revoke all on table public.report_jobs from public, anon, authenticated;
revoke all on table public.job_checkpoints from public, anon, authenticated;
revoke all on table public.evidence from public, anon, authenticated;
revoke all on table public.claims from public, anon, authenticated;
revoke all on table public.agent_runs from public, anon, authenticated;
revoke all on table public.provider_cost_events from public, anon, authenticated;

grant select, insert, update, delete on table public.report_jobs to service_role;
grant select, insert, update, delete on table public.job_checkpoints to service_role;
grant select, insert, update, delete on table public.evidence to service_role;
grant select, insert, update, delete on table public.claims to service_role;
grant select, insert, update, delete on table public.agent_runs to service_role;
grant select, insert, update, delete on table public.provider_cost_events to service_role;

grant usage on type public.job_status to service_role;
grant usage on type public.evidence_extraction_method to service_role;
grant usage on type public.evidence_retention_class to service_role;
grant usage on type public.claim_type to service_role;
grant usage on type public.claim_confidence to service_role;
grant usage on type public.claim_freshness to service_role;
grant usage on type public.claim_verifier_status to service_role;
grant usage on type public.agent_run_result to service_role;

commit;
