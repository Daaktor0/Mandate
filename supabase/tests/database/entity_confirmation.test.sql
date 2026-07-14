create extension if not exists pgtap with schema extensions;

begin;

select plan(24);

select has_function(
  'public',
  'confirm_report_request_entity',
  array['uuid', 'text', 'uuid', 'uuid[]', 'text', 'text', 'text', 'text', 'text'],
  'ENTITY-03 confirmation decision RPC exists'
);
select ok(
  has_function_privilege(
    'authenticated',
    'public.confirm_report_request_entity(uuid,text,uuid,uuid[],text,text,text,text,text)',
    'execute'
  ),
  'ENTITY-03 authenticated users can execute the guarded confirmation RPC'
);
select ok(
  not has_table_privilege(
    'authenticated',
    'private.entity_confirmation_commands',
    'select'
  ),
  'SEC-01 replay records are not exposed to authenticated users'
);
select ok(
  not has_table_privilege(
    'authenticated',
    'public.entity_candidates',
    'update'
  ),
  'SEC-01 authenticated users cannot select candidates outside the guarded RPC'
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
    'confirmation-a@example.invalid',
    now(),
    now()
  ),
  (
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    '00000000-0000-0000-0000-000000000000',
    'authenticated',
    'authenticated',
    'confirmation-b@example.invalid',
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
    'Confirmation Lawyer A',
    'IN',
    'associate'
  ),
  (
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'Confirmation Lawyer B',
    'IN',
    'partner'
  );

insert into public.entities (
  id,
  identity_key,
  legal_name,
  cin,
  company_type,
  listed_status,
  status,
  registered_office_state
)
values
  (
    '11111111-1111-4111-8111-111111111111',
    'cin:U62099MH2024PTC111111',
    'Primary Example Private Limited',
    'U62099MH2024PTC111111',
    'private',
    'unlisted',
    'Active',
    'Maharashtra'
  ),
  (
    '22222222-2222-4222-8222-222222222222',
    'cin:U62099MH2024PTC222222',
    'Related IP Private Limited',
    'U62099MH2024PTC222222',
    'private',
    'unlisted',
    'Active',
    'Maharashtra'
  ),
  (
    '33333333-3333-4333-8333-333333333333',
    'cin:U62099MH2024PTC333333',
    'Unproposed Affiliate Private Limited',
    'U62099MH2024PTC333333',
    'private',
    'unlisted',
    'Active',
    'Maharashtra'
  );

insert into public.report_requests (
  id,
  user_id,
  input_kind,
  input_url,
  input_legal_name,
  confidential_ack_at,
  state
)
values
  (
    'c1111111-1111-4111-8111-111111111111',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'legal_name',
    null,
    'Primary Example Private Limited',
    now(),
    'awaiting_entity_confirmation'
  ),
  (
    'c2222222-2222-4222-8222-222222222222',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'legal_name',
    null,
    'No Match Example Private Limited',
    now(),
    'awaiting_entity_confirmation'
  ),
  (
    'c3333333-3333-4333-8333-333333333333',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'website',
    'https://example.invalid',
    null,
    now(),
    'awaiting_entity_confirmation'
  ),
  (
    'c4444444-4444-4444-8444-444444444444',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'legal_name',
    null,
    'Ambiguous Example Private Limited',
    now(),
    'awaiting_entity_confirmation'
  );

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
values
  (
    '41111111-1111-4111-8111-111111111111',
    'c1111111-1111-4111-8111-111111111111',
    '11111111-1111-4111-8111-111111111111',
    jsonb_build_object(
      'schemaVersion', 1,
      'candidateId', '41111111-1111-4111-8111-111111111111',
      'entityId', '11111111-1111-4111-8111-111111111111',
      'legalName', 'Primary Example Private Limited',
      'companyType', 'private',
      'confidenceScore', 85,
      'confidenceLabel', 'strong_match',
      'evidenceSnippets', jsonb_build_array(
        jsonb_build_object(
          'evidenceId', 'e1111111-1111-4111-8111-111111111111',
          'snippet', 'Primary public identity evidence.',
          'sourceUrl', 'https://fixtures.mandate.local/primary',
          'companyControlled', false
        )
      ),
      'conflicts', jsonb_build_array()
    ),
    85,
    'strong_match',
    array['e1111111-1111-4111-8111-111111111111']::uuid[],
    '[]'::jsonb,
    jsonb_build_object(
      'candidateId', '41111111-1111-4111-8111-111111111111',
      'scoringVersion', 'entity-confidence-v1',
      'finalScore', 85,
      'decisions', jsonb_build_array()
    ),
    1
  ),
  (
    '42222222-2222-4222-8222-222222222222',
    'c1111111-1111-4111-8111-111111111111',
    '22222222-2222-4222-8222-222222222222',
    jsonb_build_object(
      'schemaVersion', 1,
      'candidateId', '42222222-2222-4222-8222-222222222222',
      'entityId', '22222222-2222-4222-8222-222222222222',
      'legalName', 'Related IP Private Limited',
      'companyType', 'private',
      'confidenceScore', 60,
      'confidenceLabel', 'probable_match',
      'evidenceSnippets', jsonb_build_array(
        jsonb_build_object(
          'evidenceId', 'e2222222-2222-4222-8222-222222222222',
          'snippet', 'The entity owns material intellectual property.',
          'sourceUrl', 'https://fixtures.mandate.local/related',
          'companyControlled', false
        )
      ),
      'conflicts', jsonb_build_array(),
      'relatedEntityReason', 'Owns material intellectual property used by the business.'
    ),
    60,
    'probable_match',
    array['e2222222-2222-4222-8222-222222222222']::uuid[],
    '[]'::jsonb,
    jsonb_build_object(
      'candidateId', '42222222-2222-4222-8222-222222222222',
      'scoringVersion', 'entity-confidence-v1',
      'finalScore', 60,
      'decisions', jsonb_build_array()
    ),
    2
  ),
  (
    '43333333-3333-4333-8333-333333333333',
    'c1111111-1111-4111-8111-111111111111',
    '33333333-3333-4333-8333-333333333333',
    jsonb_build_object(
      'schemaVersion', 1,
      'candidateId', '43333333-3333-4333-8333-333333333333',
      'entityId', '33333333-3333-4333-8333-333333333333',
      'legalName', 'Unproposed Affiliate Private Limited',
      'companyType', 'private',
      'confidenceScore', 35,
      'confidenceLabel', 'ambiguous',
      'evidenceSnippets', jsonb_build_array(
        jsonb_build_object(
          'evidenceId', 'e3333333-3333-4333-8333-333333333333',
          'snippet', 'A name-only public match.',
          'sourceUrl', 'https://fixtures.mandate.local/unproposed',
          'companyControlled', false
        )
      ),
      'conflicts', jsonb_build_array()
    ),
    35,
    'ambiguous',
    array['e3333333-3333-4333-8333-333333333333']::uuid[],
    '[]'::jsonb,
    jsonb_build_object(
      'candidateId', '43333333-3333-4333-8333-333333333333',
      'scoringVersion', 'entity-confidence-v1',
      'finalScore', 35,
      'decisions', jsonb_build_array()
    ),
    3
  ),
  (
    '44444444-1111-4111-8111-111111111111',
    'c2222222-2222-4222-8222-222222222222',
    '11111111-1111-4111-8111-111111111111',
    jsonb_build_object(
      'schemaVersion', 1,
      'candidateId', '44444444-1111-4111-8111-111111111111',
      'entityId', '11111111-1111-4111-8111-111111111111',
      'legalName', 'Primary Example Private Limited',
      'companyType', 'private',
      'confidenceScore', 30,
      'confidenceLabel', 'ambiguous',
      'evidenceSnippets', jsonb_build_array(
        jsonb_build_object(
          'evidenceId', 'e4444444-1111-4111-8111-111111111111',
          'snippet', 'Ambiguous public match.',
          'sourceUrl', 'https://fixtures.mandate.local/none',
          'companyControlled', false
        )
      ),
      'conflicts', jsonb_build_array()
    ),
    30,
    'ambiguous',
    array['e4444444-1111-4111-8111-111111111111']::uuid[],
    '[]'::jsonb,
    jsonb_build_object(
      'candidateId', '44444444-1111-4111-8111-111111111111',
      'scoringVersion', 'entity-confidence-v1',
      'finalScore', 30,
      'decisions', jsonb_build_array()
    ),
    1
  ),
  (
    '45555555-1111-4111-8111-111111111111',
    'c4444444-4444-4444-8444-444444444444',
    '11111111-1111-4111-8111-111111111111',
    jsonb_build_object(
      'schemaVersion', 1,
      'candidateId', '45555555-1111-4111-8111-111111111111',
      'entityId', '11111111-1111-4111-8111-111111111111',
      'legalName', 'Primary Example Private Limited',
      'companyType', 'private',
      'confidenceScore', 55,
      'confidenceLabel', 'probable_match',
      'evidenceSnippets', jsonb_build_array(
        jsonb_build_object(
          'evidenceId', 'e5555555-1111-4111-8111-111111111111',
          'snippet', 'Potential primary entity.',
          'sourceUrl', 'https://fixtures.mandate.local/ambiguous',
          'companyControlled', false
        )
      ),
      'conflicts', jsonb_build_array()
    ),
    55,
    'probable_match',
    array['e5555555-1111-4111-8111-111111111111']::uuid[],
    '[]'::jsonb,
    jsonb_build_object(
      'candidateId', '45555555-1111-4111-8111-111111111111',
      'scoringVersion', 'entity-confidence-v1',
      'finalScore', 55,
      'decisions', jsonb_build_array()
    ),
    1
  ),
  (
    '46666666-1111-4111-8111-111111111111',
    'c4444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    jsonb_build_object(
      'schemaVersion', 1,
      'candidateId', '46666666-1111-4111-8111-111111111111',
      'entityId', '33333333-3333-4333-8333-333333333333',
      'legalName', 'Unproposed Affiliate Private Limited',
      'companyType', 'private',
      'confidenceScore', 40,
      'confidenceLabel', 'ambiguous',
      'evidenceSnippets', jsonb_build_array(
        jsonb_build_object(
          'evidenceId', 'e6666666-1111-4111-8111-111111111111',
          'snippet', 'Potential but unproposed affiliate.',
          'sourceUrl', 'https://fixtures.mandate.local/affiliate',
          'companyControlled', false
        )
      ),
      'conflicts', jsonb_build_array()
    ),
    40,
    'ambiguous',
    array['e6666666-1111-4111-8111-111111111111']::uuid[],
    '[]'::jsonb,
    jsonb_build_object(
      'candidateId', '46666666-1111-4111-8111-111111111111',
      'scoringVersion', 'entity-confidence-v1',
      'finalScore', 40,
      'decisions', jsonb_build_array()
    ),
    2
  );

set local role authenticated;
set local "request.jwt.claim.sub" = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

create temporary table confirmed_response as
select public.confirm_report_request_entity(
  'c1111111-1111-4111-8111-111111111111',
  'confirm',
  '41111111-1111-4111-8111-111111111111',
  array['22222222-2222-4222-8222-222222222222']::uuid[],
  null,
  null,
  null,
  'confirm-primary-001',
  'trace-confirmation-db-001'
) as payload;

select is(
  (select payload ->> 'state' from confirmed_response),
  'preliminary_research',
  'ENTITY-03 explicit confirmation advances to preliminary research'
);
select is(
  (select confirmed_entity_id from public.report_requests where id = 'c1111111-1111-4111-8111-111111111111'),
  '11111111-1111-4111-8111-111111111111'::uuid,
  'ENTITY-03 the chosen candidate becomes the confirmed entity'
);
select is(
  (select related_entity_ids from public.report_requests where id = 'c1111111-1111-4111-8111-111111111111'),
  array['22222222-2222-4222-8222-222222222222']::uuid[],
  'ENTITY-07 the explicitly proposed related entity is stored'
);
select ok(
  (select is_selected from public.entity_candidates where id = '41111111-1111-4111-8111-111111111111'),
  'ENTITY-03 the primary candidate is marked selected'
);
select is(
  (
    select count(*)::integer
      from public.entity_candidates
     where report_request_id = 'c1111111-1111-4111-8111-111111111111'
       and is_selected
  ),
  1,
  'ENTITY-03 exactly one primary candidate can be selected'
);
select is(
  public.confirm_report_request_entity(
    'c1111111-1111-4111-8111-111111111111',
    'confirm',
    '41111111-1111-4111-8111-111111111111',
    array['22222222-2222-4222-8222-222222222222']::uuid[],
    null,
    null,
    null,
    'confirm-primary-001',
    'trace-confirmation-db-replay'
  ),
  (select payload from confirmed_response),
  'NFR-01 an exact idempotency replay returns the original result'
);

reset role;

select is(
  (
    select count(*)::integer
      from private.entity_confirmation_commands
     where report_request_id = 'c1111111-1111-4111-8111-111111111111'
  ),
  1,
  'NFR-01 confirmation replay is durably recorded once'
);

set local role authenticated;
set local "request.jwt.claim.sub" = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
select throws_ok(
  $$
    select public.confirm_report_request_entity(
      'c1111111-1111-4111-8111-111111111111',
      'none_of_these',
      null,
      '{}'::uuid[],
      null,
      null,
      null,
      'confirm-primary-001',
      'trace-confirmation-db-conflict'
    )
  $$,
  'P0001',
  'IDEMPOTENCY_CONFLICT',
  'NFR-01 one idempotency key cannot represent two decisions'
);

set local "request.jwt.claim.sub" = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
select throws_ok(
  $$
    select public.confirm_report_request_entity(
      'c4444444-4444-4444-8444-444444444444',
      'none_of_these',
      null,
      '{}'::uuid[],
      null,
      null,
      null,
      'cross-tenant-confirmation',
      'trace-confirmation-db-cross'
    )
  $$,
  'P0002',
  'REPORT_REQUEST_NOT_FOUND',
  'SEC-01 another tenant cannot decide the request'
);

set local "request.jwt.claim.sub" = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
select throws_ok(
  $$
    select public.confirm_report_request_entity(
      'c4444444-4444-4444-8444-444444444444',
      'confirm',
      '45555555-1111-4111-8111-111111111111',
      array['33333333-3333-4333-8333-333333333333']::uuid[],
      null,
      null,
      null,
      'unproposed-related',
      'trace-confirmation-db-related'
    )
  $$,
  '22023',
  'INVALID_RELATED_ENTITY_SCOPE',
  'ENTITY-07 a related entity must have an explicit materiality proposal'
);
select throws_ok(
  $$
    select public.confirm_report_request_entity(
      'c4444444-4444-4444-8444-444444444444',
      'confirm',
      '45555555-1111-4111-8111-111111111111',
      array[
        '33333333-3333-4333-8333-333333333333',
        '33333333-3333-4333-8333-333333333333'
      ]::uuid[],
      null,
      null,
      null,
      'duplicate-related',
      'trace-confirmation-db-duplicate'
    )
  $$,
  '22023',
  'INVALID_RELATED_ENTITY_SCOPE',
  'ENTITY-07 duplicate related entities fail closed'
);
select throws_ok(
  $$
    select public.confirm_report_request_entity(
      'c4444444-4444-4444-8444-444444444444',
      'confirm',
      '45555555-1111-4111-8111-111111111111',
      array['11111111-1111-4111-8111-111111111111']::uuid[],
      null,
      null,
      null,
      'primary-as-related',
      'trace-confirmation-db-primary-related'
    )
  $$,
  '22023',
  'INVALID_RELATED_ENTITY_SCOPE',
  'ENTITY-07 the primary entity cannot also be related scope'
);

create temporary table none_response as
select public.confirm_report_request_entity(
  'c2222222-2222-4222-8222-222222222222',
  'none_of_these',
  null,
  '{}'::uuid[],
  null,
  null,
  null,
  'none-of-these-001',
  'trace-confirmation-db-none'
) as payload;

select is(
  (select state::text from public.report_requests where id = 'c2222222-2222-4222-8222-222222222222'),
  'draft',
  'ENTITY-04 none-of-these returns the request to draft'
);
select is(
  (
    select count(*)::integer
      from public.entity_candidates
     where report_request_id = 'c2222222-2222-4222-8222-222222222222'
  ),
  0,
  'ENTITY-04 stale candidates are removed after none-of-these'
);
select ok(
  (select payload ->> 'guidance' from none_response) like '%legal name%'
    and (select payload ->> 'guidance' from none_response) like '%CIN%',
  'ENTITY-04 none-of-these returns public-identity refinement guidance'
);

create temporary table refine_response as
select public.confirm_report_request_entity(
  'c3333333-3333-4333-8333-333333333333',
  'refine',
  null,
  '{}'::uuid[],
  'Refined Website Operator Private Limited',
  'U62099MH2024PTC999999',
  'Maharashtra',
  'refine-entity-001',
  'trace-confirmation-db-refine'
) as payload;

select is(
  (select payload ->> 'state' from refine_response),
  'resolving_entity',
  'ENTITY-04 refine restarts asynchronous entity resolution'
);
select ok(
  (
    select input_url = 'https://example.invalid'
      and input_legal_name is null
      and input_cin is null
      and resolution_legal_name_hint = 'Refined Website Operator Private Limited'
      and resolution_cin_hint = 'U62099MH2024PTC999999'
      and resolution_state_hint = 'Maharashtra'
      and state = 'resolving_entity'
      from public.report_requests
     where id = 'c3333333-3333-4333-8333-333333333333'
  ),
  'ENTITY-04 refinement preserves original intake and stores separate public identity hints'
);

reset role;

select is(
  (
    select count(*)::integer
      from public.outbox
     where payload ->> 'reportRequestId' = 'c3333333-3333-4333-8333-333333333333'
       and payload ->> 'taskType' = 'resolve_entity'
  ),
  1,
  'ENTITY-04 refine enqueues exactly one unpaid resolution task'
);
select is(
  (
    select array_agg(key order by key)
      from public.outbox,
      lateral jsonb_object_keys(payload) as keys(key)
     where payload ->> 'reportRequestId' = 'c3333333-3333-4333-8333-333333333333'
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
  'INTAKE-04 refine queue payload remains identifier-only'
);
select is(
  to_regclass('public.entitlement_ledger'),
  null,
  'INTAKE-06 entity confirmation has no entitlement operation'
);

select * from finish();
rollback;
