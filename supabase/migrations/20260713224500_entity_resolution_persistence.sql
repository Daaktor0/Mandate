begin;

create extension if not exists pgmq;

create type public.company_type as enum (
  'private',
  'public_unlisted',
  'listed'
);

create type public.listed_status as enum (
  'listed',
  'unlisted'
);

create type public.entity_confidence_label as enum (
  'strong_match',
  'probable_match',
  'ambiguous',
  'insufficient_evidence'
);

create table public.entities (
  id uuid primary key default gen_random_uuid(),
  identity_key text not null unique
    check (char_length(identity_key) between 5 and 500),
  legal_name text not null
    check (char_length(legal_name) between 1 and 300),
  former_names text[] not null default '{}'::text[]
    check (cardinality(former_names) <= 20),
  cin text null unique
    check (
      cin is null
      or cin ~ '^[UL][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$'
    ),
  company_type public.company_type not null,
  listed_status public.listed_status null,
  status text null
    check (status is null or char_length(status) between 1 and 100),
  registered_office_state text null
    check (
      registered_office_state is null
      or char_length(registered_office_state) between 1 and 100
    ),
  registered_office_summary text null
    check (
      registered_office_summary is null
      or char_length(registered_office_summary) between 1 and 500
    ),
  jurisdiction text not null default 'IN'
    check (jurisdiction ~ '^[A-Z]{2}$'),
  incorporation_date date null,
  primary_domain text null
    check (
      primary_domain is null
      or (
        char_length(primary_domain) between 1 and 253
        and primary_domain ~* '^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$'
      )
    ),
  brand_names text[] not null default '{}'::text[]
    check (cardinality(brand_names) <= 20),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.entities is
  'Shared public-company reference data. User identity and matter data are structurally absent.';
comment on column public.entities.identity_key is
  'Worker-derived dedupe key: exact CIN when available, otherwise normalised legal name and state.';

create table public.entity_candidates (
  id uuid primary key,
  report_request_id uuid not null
    references public.report_requests (id) on delete cascade,
  entity_id uuid not null
    references public.entities (id) on delete restrict,
  candidate_payload jsonb not null
    check (jsonb_typeof(candidate_payload) = 'object'),
  confidence_score smallint not null
    check (confidence_score between 0 and 100),
  confidence_label public.entity_confidence_label not null,
  evidence_ids uuid[] not null
    check (cardinality(evidence_ids) between 1 and 20),
  conflicts jsonb not null
    check (jsonb_typeof(conflicts) = 'array'),
  score_audit jsonb not null
    check (jsonb_typeof(score_audit) = 'object'),
  is_selected boolean not null default false,
  rank smallint not null
    check (rank between 1 and 20),
  created_at timestamptz not null default now(),
  constraint entity_candidates_payload_identity check (
    candidate_payload ->> 'schemaVersion' = '1'
    and candidate_payload ->> 'candidateId' = id::text
    and candidate_payload ->> 'entityId' = entity_id::text
  ),
  constraint entity_candidates_payload_score check (
    (candidate_payload ->> 'confidenceScore')::smallint = confidence_score
    and candidate_payload ->> 'confidenceLabel' = confidence_label::text
    and candidate_payload -> 'conflicts' = conflicts
  ),
  constraint entity_candidates_audit_alignment check (
    score_audit ->> 'candidateId' = id::text
    and score_audit ->> 'scoringVersion' = 'entity-confidence-v1'
    and (score_audit ->> 'finalScore')::smallint = confidence_score
    and jsonb_typeof(score_audit -> 'decisions') = 'array'
  ),
  unique (report_request_id, rank)
);

create unique index entity_candidates_one_selected_idx
  on public.entity_candidates (report_request_id)
  where is_selected;

create index entity_candidates_request_idx
  on public.entity_candidates (report_request_id, rank);

comment on table public.entity_candidates is
  'Ranked, request-scoped EntityCandidate contracts. Selection is always an explicit later user action.';
comment on column public.entity_candidates.score_audit is
  'Structured factor decisions and concise rationale codes; never hidden chain-of-thought.';

alter table public.report_requests
  add constraint report_requests_confirmed_entity_fk
  foreign key (confirmed_entity_id)
  references public.entities (id)
  on delete restrict;

create table public.outbox (
  id uuid primary key,
  topic text not null
    check (topic = 'mandate_light_tasks'),
  payload jsonb not null,
  idempotency_key text not null unique
    check (char_length(idempotency_key) between 1 and 512),
  created_at timestamptz not null default now(),
  dispatched_at timestamptz null,
  dispatch_attempts integer not null default 0
    check (dispatch_attempts >= 0),
  last_error_code text null
    check (
      last_error_code is null
      or last_error_code ~ '^[a-z0-9_:-]{1,100}$'
    )
);

comment on table public.outbox is
  'Transactional identifier-only queue messages; no profile, billing, letterhead or narrative fields.';

create index outbox_pending_idx
  on public.outbox (created_at, id)
  where dispatched_at is null;

create or replace function private.light_task_payload_is_valid(p_payload jsonb)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select
    jsonb_typeof(p_payload) = 'object'
    and p_payload ?& array[
      'schemaVersion',
      'taskId',
      'taskType',
      'reportRequestId',
      'userId',
      'attempt',
      'traceId'
    ]
    and p_payload - array[
      'schemaVersion',
      'taskId',
      'taskType',
      'reportRequestId',
      'userId',
      'attempt',
      'traceId'
    ] = '{}'::jsonb
    and p_payload ->> 'schemaVersion' = '1'
    and p_payload ->> 'taskType' in (
      'resolve_entity',
      'preliminary_research',
      'render_pdf'
    )
    and p_payload ->> 'taskId'
      ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    and p_payload ->> 'reportRequestId'
      ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    and p_payload ->> 'userId'
      ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    and (p_payload ->> 'attempt')::integer between 1 and 100
    and p_payload ->> 'traceId' ~ '^[A-Za-z0-9._:-]{8,128}$';
$$;

revoke all on function private.light_task_payload_is_valid(jsonb)
  from public, anon, authenticated;
grant execute on function private.light_task_payload_is_valid(jsonb)
  to service_role;

alter table public.outbox
  add constraint outbox_light_task_payload_valid check (
    private.light_task_payload_is_valid(payload)
    and payload ->> 'taskId' = id::text
  );

create or replace function private.is_legal_request_state_transition(
  p_from public.request_state,
  p_to public.request_state
)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select (p_from, p_to) in (
    ('draft'::public.request_state, 'resolving_entity'::public.request_state),
    ('resolving_entity'::public.request_state, 'awaiting_entity_confirmation'::public.request_state),
    ('resolving_entity'::public.request_state, 'failed_no_charge'::public.request_state),
    ('awaiting_entity_confirmation'::public.request_state, 'draft'::public.request_state),
    ('awaiting_entity_confirmation'::public.request_state, 'preliminary_research'::public.request_state),
    ('preliminary_research'::public.request_state, 'awaiting_clarification'::public.request_state),
    ('preliminary_research'::public.request_state, 'failed_no_charge'::public.request_state),
    ('awaiting_clarification'::public.request_state, 'queued'::public.request_state),
    ('queued'::public.request_state, 'researching'::public.request_state),
    ('queued'::public.request_state, 'cancelled_restored'::public.request_state),
    ('researching'::public.request_state, 'verifying'::public.request_state),
    ('researching'::public.request_state, 'retry_wait'::public.request_state),
    ('researching'::public.request_state, 'failed_restored'::public.request_state),
    ('researching'::public.request_state, 'cancelled_restored'::public.request_state),
    ('verifying'::public.request_state, 'composing'::public.request_state),
    ('verifying'::public.request_state, 'retry_wait'::public.request_state),
    ('verifying'::public.request_state, 'failed_restored'::public.request_state),
    ('verifying'::public.request_state, 'cancelled_restored'::public.request_state),
    ('composing'::public.request_state, 'rendering'::public.request_state),
    ('composing'::public.request_state, 'retry_wait'::public.request_state),
    ('composing'::public.request_state, 'failed_restored'::public.request_state),
    ('composing'::public.request_state, 'cancelled_restored'::public.request_state),
    ('rendering'::public.request_state, 'completed'::public.request_state),
    ('rendering'::public.request_state, 'retry_wait'::public.request_state),
    ('rendering'::public.request_state, 'failed_restored'::public.request_state),
    ('rendering'::public.request_state, 'cancelled_restored'::public.request_state),
    ('retry_wait'::public.request_state, 'queued'::public.request_state)
  );
$$;

revoke all on function private.is_legal_request_state_transition(
  public.request_state,
  public.request_state
) from public, anon, authenticated;

create or replace function private.enforce_request_state_transition()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.state is distinct from old.state
    and not private.is_legal_request_state_transition(old.state, new.state)
  then
    raise exception 'ILLEGAL_REQUEST_STATE_TRANSITION'
      using errcode = '23514';
  end if;
  return new;
end;
$$;

revoke all on function private.enforce_request_state_transition()
  from public, anon, authenticated;

create trigger report_requests_enforce_state_transition
before update of state on public.report_requests
for each row execute function private.enforce_request_state_transition();

create or replace function public.enqueue_entity_resolution(
  p_report_request_id uuid,
  p_idempotency_key text,
  p_trace_id text
)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_user_id uuid := (select auth.uid());
  v_request public.report_requests;
  v_task_id uuid;
  v_internal_key text;
  v_existing public.outbox;
begin
  if v_user_id is null then
    raise exception 'UNAUTHENTICATED' using errcode = '42501';
  end if;
  if p_idempotency_key is not null
    and p_idempotency_key !~ '^[!-~]{1,128}$'
  then
    raise exception 'INVALID_IDEMPOTENCY_KEY' using errcode = '22023';
  end if;
  if p_trace_id is null
    or p_trace_id !~ '^[A-Za-z0-9._:-]{8,128}$'
  then
    raise exception 'INVALID_TRACE_ID' using errcode = '22023';
  end if;

  perform pg_advisory_xact_lock(hashtextextended(v_user_id::text, 1));
  v_internal_key := 'resolve:' || v_user_id::text || ':'
    || p_report_request_id::text || ':'
    || coalesce(p_idempotency_key, gen_random_uuid()::text);

  if p_idempotency_key is not null then
    select item.*
      into v_existing
      from public.outbox as item
     where item.idempotency_key = v_internal_key;
    if found then
      return jsonb_build_object('state', 'resolving_entity');
    end if;
  end if;

  select request.*
    into v_request
    from public.report_requests as request
   where request.id = p_report_request_id
     and request.user_id = v_user_id
   for update;

  if not found then
    raise exception 'REPORT_REQUEST_NOT_FOUND' using errcode = 'P0002';
  end if;
  if v_request.state <> 'draft'::public.request_state then
    raise exception 'RESOLUTION_STATE_CONFLICT' using errcode = 'P0001';
  end if;
  if (
    select count(*)
      from public.outbox as item
     where item.topic = 'mandate_light_tasks'
       and item.payload ->> 'taskType' = 'resolve_entity'
       and item.payload ->> 'userId' = v_user_id::text
       and item.created_at >= now() - interval '1 hour'
  ) >= 10 then
    raise exception 'RESOLUTION_RATE_LIMITED' using errcode = 'P0001';
  end if;

  delete from public.entity_candidates
   where report_request_id = p_report_request_id;

  v_task_id := gen_random_uuid();
  insert into public.outbox (id, topic, payload, idempotency_key)
  values (
    v_task_id,
    'mandate_light_tasks',
    jsonb_build_object(
      'schemaVersion', 1,
      'taskId', v_task_id,
      'taskType', 'resolve_entity',
      'reportRequestId', p_report_request_id,
      'userId', v_user_id,
      'attempt', 1,
      'traceId', p_trace_id
    ),
    v_internal_key
  );

  update public.report_requests
     set state = 'resolving_entity'
   where id = p_report_request_id;

  return jsonb_build_object('state', 'resolving_entity');
end;
$$;

revoke all on function public.enqueue_entity_resolution(uuid, text, text)
  from public, anon;
grant execute on function public.enqueue_entity_resolution(uuid, text, text)
  to authenticated;

create or replace function private.complete_entity_resolution(
  p_task_id uuid,
  p_report_request_id uuid,
  p_candidates jsonb,
  p_score_audits jsonb
)
returns public.request_state
language plpgsql
volatile
set search_path = ''
as $$
declare
  v_request public.report_requests;
  v_candidate jsonb;
  v_audit jsonb;
  v_entity_id uuid;
  v_candidate_id uuid;
  v_identity_key text;
  v_rank integer;
  v_evidence_ids uuid[];
begin
  if not exists (
    select 1
      from public.outbox as item
     where item.id = p_task_id
       and item.topic = 'mandate_light_tasks'
       and item.payload ->> 'taskType' = 'resolve_entity'
       and item.payload ->> 'reportRequestId' = p_report_request_id::text
  ) then
    raise exception 'RESOLUTION_TASK_NOT_FOUND' using errcode = 'P0002';
  end if;
  if jsonb_typeof(p_candidates) <> 'array'
    or jsonb_typeof(p_score_audits) <> 'array'
    or jsonb_array_length(p_candidates) > 20
    or jsonb_array_length(p_candidates) <> jsonb_array_length(p_score_audits)
  then
    raise exception 'INVALID_RESOLUTION_RESULT' using errcode = '22023';
  end if;

  select request.*
    into v_request
    from public.report_requests as request
   where request.id = p_report_request_id
   for update;
  if not found then
    raise exception 'REPORT_REQUEST_NOT_FOUND' using errcode = 'P0002';
  end if;
  if v_request.state = 'awaiting_entity_confirmation'::public.request_state
    or v_request.state = 'failed_no_charge'::public.request_state
  then
    return v_request.state;
  end if;
  if v_request.state <> 'resolving_entity'::public.request_state then
    raise exception 'RESOLUTION_STATE_CONFLICT' using errcode = 'P0001';
  end if;

  delete from public.entity_candidates
   where report_request_id = p_report_request_id;

  if jsonb_array_length(p_candidates) = 0 then
    update public.report_requests
       set state = 'failed_no_charge'
     where id = p_report_request_id;
    return 'failed_no_charge'::public.request_state;
  end if;

  for v_candidate, v_rank in
    select item.value, item.ordinality::integer
      from jsonb_array_elements(p_candidates) with ordinality as item(value, ordinality)
  loop
    v_audit := p_score_audits -> (v_rank - 1);
    if jsonb_typeof(v_candidate) <> 'object'
      or v_candidate ->> 'schemaVersion' <> '1'
      or jsonb_typeof(v_candidate -> 'evidenceSnippets') <> 'array'
      or jsonb_array_length(v_candidate -> 'evidenceSnippets') not between 1 and 20
      or jsonb_typeof(v_candidate -> 'conflicts') <> 'array'
      or jsonb_typeof(v_audit) <> 'object'
      or v_audit ->> 'candidateId' <> v_candidate ->> 'candidateId'
    then
      raise exception 'INVALID_RESOLUTION_RESULT' using errcode = '22023';
    end if;

    v_candidate_id := (v_candidate ->> 'candidateId')::uuid;
    v_identity_key := case
      when nullif(v_candidate ->> 'cin', '') is not null
        then 'cin:' || upper(v_candidate ->> 'cin')
      else 'name:' || lower(v_candidate ->> 'legalName') || '|state:'
        || lower(coalesce(v_candidate ->> 'registeredOfficeState', ''))
    end;

    insert into public.entities (
      identity_key,
      legal_name,
      former_names,
      cin,
      company_type,
      listed_status,
      status,
      registered_office_state,
      registered_office_summary,
      primary_domain,
      brand_names
    )
    values (
      v_identity_key,
      v_candidate ->> 'legalName',
      coalesce(
        array(
          select jsonb_array_elements_text(
            coalesce(v_candidate -> 'formerNames', '[]'::jsonb)
          )
        ),
        '{}'::text[]
      ),
      nullif(v_candidate ->> 'cin', ''),
      (v_candidate ->> 'companyType')::public.company_type,
      case
        when nullif(v_candidate ->> 'listedStatus', '') is null then null
        else (v_candidate ->> 'listedStatus')::public.listed_status
      end,
      nullif(v_candidate ->> 'status', ''),
      nullif(v_candidate ->> 'registeredOfficeState', ''),
      nullif(v_candidate ->> 'registeredOfficeSummary', ''),
      nullif(v_candidate ->> 'primaryDomain', ''),
      coalesce(
        array(
          select jsonb_array_elements_text(
            coalesce(v_candidate -> 'brandNames', '[]'::jsonb)
          )
        ),
        '{}'::text[]
      )
    )
    on conflict (identity_key) do update
      set legal_name = excluded.legal_name,
          former_names = excluded.former_names,
          cin = excluded.cin,
          company_type = excluded.company_type,
          listed_status = excluded.listed_status,
          status = excluded.status,
          registered_office_state = excluded.registered_office_state,
          registered_office_summary = excluded.registered_office_summary,
          primary_domain = excluded.primary_domain,
          brand_names = excluded.brand_names
    returning id into v_entity_id;

    v_candidate := jsonb_set(
      v_candidate,
      '{entityId}',
      to_jsonb(v_entity_id::text),
      true
    );
    select array_agg((evidence.value ->> 'evidenceId')::uuid order by evidence.ordinality)
      into v_evidence_ids
      from jsonb_array_elements(v_candidate -> 'evidenceSnippets')
        with ordinality as evidence(value, ordinality);

    insert into public.entity_candidates (
      id,
      report_request_id,
      entity_id,
      candidate_payload,
      confidence_score,
      confidence_label,
      evidence_ids,
      conflicts,
      score_audit,
      rank
    )
    values (
      v_candidate_id,
      p_report_request_id,
      v_entity_id,
      v_candidate,
      (v_candidate ->> 'confidenceScore')::smallint,
      (v_candidate ->> 'confidenceLabel')::public.entity_confidence_label,
      v_evidence_ids,
      v_candidate -> 'conflicts',
      v_audit,
      v_rank
    );
  end loop;

  update public.report_requests
     set state = 'awaiting_entity_confirmation'
   where id = p_report_request_id;
  return 'awaiting_entity_confirmation'::public.request_state;
end;
$$;

revoke all on function private.complete_entity_resolution(uuid, uuid, jsonb, jsonb)
  from public, anon, authenticated;
grant execute on function private.complete_entity_resolution(uuid, uuid, jsonb, jsonb)
  to service_role;

create or replace function private.fail_entity_resolution(
  p_task_id uuid,
  p_report_request_id uuid,
  p_error_code text
)
returns public.request_state
language plpgsql
volatile
set search_path = ''
as $$
declare
  v_state public.request_state;
begin
  if p_error_code is null or p_error_code !~ '^[a-z0-9_:-]{1,100}$' then
    raise exception 'INVALID_RESOLUTION_ERROR_CODE' using errcode = '22023';
  end if;
  if not exists (
    select 1
      from public.outbox as item
     where item.id = p_task_id
       and item.payload ->> 'taskType' = 'resolve_entity'
       and item.payload ->> 'reportRequestId' = p_report_request_id::text
  ) then
    raise exception 'RESOLUTION_TASK_NOT_FOUND' using errcode = 'P0002';
  end if;

  select request.state
    into v_state
    from public.report_requests as request
   where request.id = p_report_request_id
   for update;
  if not found then
    raise exception 'REPORT_REQUEST_NOT_FOUND' using errcode = 'P0002';
  end if;
  if v_state = 'resolving_entity'::public.request_state then
    update public.report_requests
       set state = 'failed_no_charge'
     where id = p_report_request_id;
    update public.outbox
       set last_error_code = p_error_code
     where id = p_task_id;
    return 'failed_no_charge'::public.request_state;
  end if;
  if v_state in (
    'failed_no_charge'::public.request_state,
    'awaiting_entity_confirmation'::public.request_state
  ) then
    return v_state;
  end if;
  raise exception 'RESOLUTION_STATE_CONFLICT' using errcode = 'P0001';
end;
$$;

revoke all on function private.fail_entity_resolution(uuid, uuid, text)
  from public, anon, authenticated;
grant execute on function private.fail_entity_resolution(uuid, uuid, text)
  to service_role;

select pgmq.create('mandate_light_tasks');

create or replace function private.dispatch_next_outbox()
returns table (
  outbox_id uuid,
  queue_message_id bigint,
  dispatched boolean
)
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_outbox public.outbox;
  v_message_id bigint;
begin
  select item.*
    into v_outbox
    from public.outbox as item
   where item.dispatched_at is null
   order by item.created_at, item.id
   for update skip locked
   limit 1;
  if not found then
    return;
  end if;

  begin
    select sent.msg_id
      into v_message_id
      from pgmq.send(v_outbox.topic, v_outbox.payload, 0) as sent(msg_id);
    update public.outbox
       set dispatched_at = now(),
           dispatch_attempts = dispatch_attempts + 1,
           last_error_code = null
     where id = v_outbox.id;
    return query select v_outbox.id, v_message_id, true;
  exception when others then
    update public.outbox
       set dispatch_attempts = dispatch_attempts + 1,
           last_error_code = 'queue_dispatch_failed'
     where id = v_outbox.id;
    return query select v_outbox.id, null::bigint, false;
  end;
end;
$$;

revoke all on function private.dispatch_next_outbox()
  from public, anon, authenticated;
grant execute on function private.dispatch_next_outbox()
  to service_role;

create trigger entities_set_updated_at
before update on public.entities
for each row execute function private.set_updated_at();

alter table public.entities enable row level security;
alter table public.entities force row level security;
alter table public.entity_candidates enable row level security;
alter table public.entity_candidates force row level security;
alter table public.outbox enable row level security;
alter table public.outbox force row level security;

revoke all on table public.entities from public, anon, authenticated;
revoke all on table public.entity_candidates from public, anon, authenticated;
revoke all on table public.outbox from public, anon, authenticated;

grant select on table public.entities to authenticated;
grant select on table public.entity_candidates to authenticated;

grant select, insert, update, delete on table public.entities to service_role;
grant select, insert, update, delete on table public.entity_candidates to service_role;
grant select, insert, update, delete on table public.outbox to service_role;

grant usage on type public.company_type to authenticated, service_role;
grant usage on type public.listed_status to authenticated, service_role;
grant usage on type public.entity_confidence_label to authenticated, service_role;

create policy entities_select_authenticated
on public.entities
for select
to authenticated
using (true);

create policy entity_candidates_select_own
on public.entity_candidates
for select
to authenticated
using (
  exists (
    select 1
      from public.report_requests as request
     where request.id = entity_candidates.report_request_id
       and request.user_id = (select auth.uid())
  )
);

commit;
