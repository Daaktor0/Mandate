create extension if not exists pgtap with schema extensions;

begin;

select plan(39);

select has_table('public', 'entities', 'ENTITY-05 entities exists');
select has_table('public', 'entity_candidates', 'ENTITY-02 entity_candidates exists');
select has_table('public', 'outbox', 'NFR-01 transactional outbox exists');

select is(
  (
    select relrowsecurity and relforcerowsecurity
      from pg_class
     where oid = 'public.entities'::regclass
  ),
  true,
  'NFR-02 entities forces RLS'
);
select is(
  (
    select relrowsecurity and relforcerowsecurity
      from pg_class
     where oid = 'public.entity_candidates'::regclass
  ),
  true,
  'NFR-02 entity_candidates forces RLS'
);
select is(
  (
    select relrowsecurity and relforcerowsecurity
      from pg_class
     where oid = 'public.outbox'::regclass
  ),
  true,
  'NFR-02 outbox forces RLS'
);

select ok(
  has_table_privilege('authenticated', 'public.entities', 'select'),
  'ENTITY-02 authenticated users can reach shared entities through RLS'
);
select ok(
  has_table_privilege('authenticated', 'public.entity_candidates', 'select'),
  'ENTITY-02 authenticated users can reach own candidates through RLS'
);
select ok(
  not has_table_privilege('authenticated', 'public.entity_candidates', 'insert'),
  'SEC-01 authenticated users cannot forge candidates'
);
select ok(
  not has_table_privilege('authenticated', 'public.outbox', 'select'),
  'SEC-01 authenticated users cannot inspect queue payloads'
);
select ok(
  not has_function_privilege(
    'authenticated',
    'private.complete_entity_resolution(uuid,uuid,jsonb,jsonb)',
    'execute'
  ),
  'SEC-01 authenticated users cannot complete worker transitions'
);
select ok(
  not has_function_privilege(
    'authenticated',
    'private.dispatch_next_outbox()',
    'execute'
  ),
  'SEC-01 authenticated users cannot dispatch outbox rows'
);
select ok(
  not has_function_privilege(
    'authenticated',
    'private.fail_entity_resolution(uuid,uuid,text)',
    'execute'
  ),
  'SEC-01 authenticated users cannot force terminal resolution failures'
);

insert into auth.users (
  id,
  instance_id,
  aud,
  role,
  email,
  created_at,
  updated_at
)
values
  (
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    '00000000-0000-0000-0000-000000000000',
    'authenticated',
    'authenticated',
    'resolution-a@example.invalid',
    now(),
    now()
  ),
  (
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    '00000000-0000-0000-0000-000000000000',
    'authenticated',
    'authenticated',
    'resolution-b@example.invalid',
    now(),
    now()
  );

insert into public.users_profile (
  user_id,
  full_name,
  country,
  professional_role
)
values
  (
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'Resolution Lawyer A',
    'IN',
    'associate'
  ),
  (
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'Resolution Lawyer B',
    'IN',
    'partner'
  );

insert into public.report_requests (
  id,
  user_id,
  input_kind,
  input_legal_name,
  input_cin,
  confidential_ack_at
)
values
  (
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'legal_name',
    'Mandate Demo Company Private Limited',
    'U62099MH2024PTC123456',
    now()
  ),
  (
    'ffffffff-ffff-4fff-8fff-ffffffffffff',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'legal_name',
    'Terminal Failure Fixture Private Limited',
    null,
    now()
  );

set local role authenticated;
set local "request.jwt.claim.sub" = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

select is(
  public.enqueue_entity_resolution(
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    'resolve-entity-001',
    'trace-resolution-db-001'
  ) ->> 'state',
  'resolving_entity',
  'ENTITY-03 enqueue returns the asynchronous resolving state'
);

reset role;

select is(
  (
    select state::text
      from public.report_requests
     where id = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
  ),
  'resolving_entity',
  'ENTITY-03 enqueue transitions draft to resolving_entity atomically'
);
select is(
  (
    select count(*)::integer
      from public.outbox
     where payload ->> 'reportRequestId' = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
  ),
  1,
  'NFR-01 enqueue creates exactly one outbox task'
);
select is(
  (
    select array_agg(key order by key)
      from public.outbox,
      lateral jsonb_object_keys(payload) as keys(key)
     where payload ->> 'reportRequestId' = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
  ),
  array[
    'attempt',
    'reportRequestId',
    'schemaVersion',
    'taskId',
    'taskType',
    'traceId',
    'userId'
  ]::text[],
  'ENTITY-03 queue payload is an exact identifier-only allowlist'
);
select ok(
  not exists (
    select 1
      from public.outbox as item,
      lateral jsonb_object_keys(item.payload) as keys(key)
     where lower(keys.key) in (
       'email',
       'fullname',
       'firm',
       'billing',
       'letterhead',
       'description',
       'legalname',
       'url'
     )
  ),
  'INTAKE-04 queue payload excludes identity, provider input and narrative fields'
);
select is(
  to_regclass('public.entitlement_ledger'),
  null,
  'INTAKE-06 resolution has no entitlement surface'
);

set local role authenticated;
set local "request.jwt.claim.sub" = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
select public.enqueue_entity_resolution(
  'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
  'resolve-entity-001',
  'trace-resolution-db-001'
);
reset role;

select is(
  (
    select count(*)::integer
      from public.outbox
     where payload ->> 'reportRequestId' = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
  ),
  1,
  'NFR-01 idempotency replay does not duplicate the light task'
);

set local role authenticated;
set local "request.jwt.claim.sub" = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
select throws_ok(
  $$
    select public.enqueue_entity_resolution(
      'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
      'resolve-entity-002',
      'trace-resolution-db-002'
    )
  $$,
  'P0001',
  'RESOLUTION_STATE_CONFLICT',
  'ENTITY-03 a different enqueue cannot bypass the state machine'
);

set local "request.jwt.claim.sub" = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
select throws_ok(
  $$
    select public.enqueue_entity_resolution(
      'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
      'cross-tenant-resolution',
      'trace-resolution-db-003'
    )
  $$,
  'P0002',
  'REPORT_REQUEST_NOT_FOUND',
  'SEC-01 another tenant cannot enqueue the request'
);
reset role;

set local role service_role;
create temporary table dispatched_resolution_task as
select * from private.dispatch_next_outbox();
reset role;

select is(
  (select dispatched from dispatched_resolution_task),
  true,
  'NFR-01 worker relay dispatches one committed outbox row'
);
select ok(
  (
    select dispatched_at is not null and dispatch_attempts = 1
      from public.outbox
     where payload ->> 'reportRequestId' = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
  ),
  'NFR-01 successful dispatch is recorded atomically'
);
select is(
  (
    select message ->> 'taskType'
      from pgmq.read('mandate_light_tasks', 120, 1)
  ),
  'resolve_entity',
  'NFR-01 the light queue receives the validated resolution task'
);

set local role service_role;
select is(
  private.complete_entity_resolution(
    (
      select id
        from public.outbox
       where payload ->> 'reportRequestId' = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
    ),
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    jsonb_build_array(
      jsonb_build_object(
        'schemaVersion', 1,
        'candidateId', 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
        'legalName', 'MANDATE DEMO COMPANY PRIVATE LIMITED',
        'formerNames', jsonb_build_array(),
        'cin', 'U62099MH2024PTC123456',
        'companyType', 'private',
        'listedStatus', 'unlisted',
        'status', 'Active',
        'registeredOfficeState', 'Maharashtra',
        'registeredOfficeSummary', '12 Synthetic Avenue, Mumbai, Maharashtra 400001',
        'primaryDomain', null,
        'brandNames', jsonb_build_array(),
        'confidenceScore', 85,
        'confidenceLabel', 'strong_match',
        'evidenceSnippets', jsonb_build_array(
          jsonb_build_object(
            'evidenceId', 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
            'snippet', 'Synthetic public company-data fixture.',
            'sourceUrl', 'https://fixtures.mandate.local/company-data/smoke',
            'companyControlled', false
          )
        ),
        'conflicts', jsonb_build_array()
      )
    ),
    jsonb_build_array(
      jsonb_build_object(
        'candidateId', 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
        'scoringVersion', 'entity-confidence-v1',
        'positiveTotal', 85,
        'negativeTotal', 0,
        'finalScore', 85,
        'decisions', jsonb_build_array()
      )
    )
  )::text,
  'awaiting_entity_confirmation',
  'ENTITY-02 worker atomically persists a candidate and completes resolution'
);
reset role;

select is(
  (
    select state::text
      from public.report_requests
     where id = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
  ),
  'awaiting_entity_confirmation',
  'ENTITY-03 successful resolution awaits mandatory user confirmation'
);
select is(
  (
    select count(*)::integer
      from public.entity_candidates
     where report_request_id = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
  ),
  1,
  'ENTITY-02 one ranked candidate is persisted'
);
select is(
  (
    select cin
      from public.entities
     where identity_key = 'cin:U62099MH2024PTC123456'
  ),
  'U62099MH2024PTC123456',
  'ENTITY-05 exact CIN is the shared entity identity key'
);
select ok(
  (
    select candidate_payload ->> 'entityId' = entity_id::text
      from public.entity_candidates
     where id = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
  ),
  'ENTITY-02 persisted payload links to its normalised entity'
);

set local role authenticated;
set local "request.jwt.claim.sub" = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
select is(
  public.enqueue_entity_resolution(
    'ffffffff-ffff-4fff-8fff-ffffffffffff',
    'resolve-terminal-failure',
    'trace-resolution-db-004'
  ) ->> 'state',
  'resolving_entity',
  'NFR-01 a second unpaid resolution task can be enqueued independently'
);
reset role;

set local role service_role;
select is(
  private.fail_entity_resolution(
    (
      select id
        from public.outbox
       where payload ->> 'reportRequestId' = 'ffffffff-ffff-4fff-8fff-ffffffffffff'
    ),
    'ffffffff-ffff-4fff-8fff-ffffffffffff',
    'max_light_task_deliveries_exceeded'
  )::text,
  'failed_no_charge',
  'NFR-01 exhausted resolution transitions to failed_no_charge'
);
reset role;

select is(
  (
    select state::text
      from public.report_requests
     where id = 'ffffffff-ffff-4fff-8fff-ffffffffffff'
  ),
  'failed_no_charge',
  'INTAKE-06 terminal pre-confirmation failure remains uncharged'
);
select is(
  (
    select last_error_code
      from public.outbox
     where payload ->> 'reportRequestId' = 'ffffffff-ffff-4fff-8fff-ffffffffffff'
  ),
  'max_light_task_deliveries_exceeded',
  'NFR-04 terminal failure stores only a stable audit code'
);

set local role service_role;
select is(
  private.complete_entity_resolution(
    (
      select id
        from public.outbox
       where payload ->> 'reportRequestId' = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
    ),
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    '[]'::jsonb,
    '[]'::jsonb
  )::text,
  'awaiting_entity_confirmation',
  'NFR-01 completion replay is idempotent after commit'
);
reset role;

set local role authenticated;
set local "request.jwt.claim.sub" = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
select results_eq(
  $$select count(*) from public.entity_candidates$$,
  array[1::bigint],
  'SEC-01 owner sees the request candidate'
);

set local "request.jwt.claim.sub" = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
select results_eq(
  $$select count(*) from public.entity_candidates$$,
  array[0::bigint],
  'SEC-01 another tenant cannot see the request candidate'
);
select results_eq(
  $$select count(*) from public.entities$$,
  array[1::bigint],
  'ENTITY-02 authenticated users can read shared public-company reference data'
);
reset role;

select throws_ok(
  $$
    update public.report_requests
       set state = 'completed'
     where id = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
  $$,
  '23514',
  'ILLEGAL_REQUEST_STATE_TRANSITION',
  'ENTITY-03 illegal direct state transitions fail closed'
);

select * from finish();

rollback;
