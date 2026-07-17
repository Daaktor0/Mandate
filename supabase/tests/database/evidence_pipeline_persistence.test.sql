create extension if not exists pgtap with schema extensions;

begin;

select plan(18);

select has_table('public', 'report_jobs', 'RUN-01 report_jobs exists');
select has_table('public', 'job_checkpoints', 'RUN-02 job_checkpoints exists');
select has_table('public', 'evidence', 'RUN-04 evidence exists');
select has_table('public', 'claims', 'REPORT-06 claims exists');
select has_table('public', 'agent_runs', 'NFR-09 agent_runs exists');
select has_table('public', 'provider_cost_events', 'NFR-05 provider_cost_events exists');

select ok(
  (
    select relrowsecurity and relforcerowsecurity
    from pg_class
    where oid = 'public.report_jobs'::regclass
  ),
  'NFR-02 report_jobs has forced RLS'
);
select ok(
  (
    select bool_and(relrowsecurity and relforcerowsecurity)
    from pg_class
    where oid in (
      'public.job_checkpoints'::regclass,
      'public.evidence'::regclass,
      'public.claims'::regclass,
      'public.agent_runs'::regclass,
      'public.provider_cost_events'::regclass
    )
  ),
  'NFR-02 every evidence-pipeline table has forced RLS'
);
select ok(
  not has_table_privilege('anon', 'public.evidence', 'select')
    and not has_table_privilege('authenticated', 'public.evidence', 'select')
    and has_table_privilege('service_role', 'public.evidence', 'select'),
  'NFR-02 evidence is default-deny outside the service role'
);
select ok(
  not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name in (
        'report_jobs',
        'job_checkpoints',
        'evidence',
        'claims',
        'agent_runs',
        'provider_cost_events'
      )
      and column_name in (
        'email',
        'firm',
        'full_name',
        'billing_email',
        'letterhead_url',
        'matter_narrative',
        'prompt',
        'raw_body'
      )
  ),
  'SEC-11 persistence tables have no identity, billing, prompt or raw-body columns'
);

insert into auth.users (id, instance_id, aud, role, email, created_at, updated_at)
values
  (
    '11111111-1111-4111-8111-111111111111',
    '00000000-0000-0000-0000-000000000000',
    'authenticated',
    'authenticated',
    'admin@example.invalid',
    now(),
    now()
  ),
  (
    '22222222-2222-4222-8222-222222222222',
    '00000000-0000-0000-0000-000000000000',
    'authenticated',
    'authenticated',
    'lawyer@example.invalid',
    now(),
    now()
  );

insert into public.users_profile (user_id, full_name, country, professional_role)
values
  ('11111111-1111-4111-8111-111111111111', 'Admin User', 'IN', 'partner'),
  ('22222222-2222-4222-8222-222222222222', 'Test Lawyer', 'IN', 'associate');

insert into public.entities (
  id,
  identity_key,
  legal_name,
  company_type
)
values (
  '33333333-3333-4333-8333-333333333333',
  'cin:U62099MH2024PTC999999',
  'Evidence Example Private Limited',
  'private'
);

insert into public.report_requests (
  id,
  user_id,
  input_kind,
  input_legal_name,
  confidential_ack_at
)
values (
  '44444444-4444-4444-8444-444444444444',
  '22222222-2222-4222-8222-222222222222',
  'legal_name',
  'Evidence Example Private Limited',
  now()
);

insert into public.report_jobs (
  id,
  report_request_id,
  user_id,
  confirmed_entity_id,
  trace_id,
  prompt_bundle_version
)
values (
  '55555555-5555-4555-8555-555555555555',
  '44444444-4444-4444-8444-444444444444',
  '22222222-2222-4222-8222-222222222222',
  '33333333-3333-4333-8333-333333333333',
  'trace-evidence-001',
  'prompt-v1'
);

select is(
  (
    select active_job_id
    from public.report_requests
    where id = '44444444-4444-4444-8444-444444444444'
  ),
  null::uuid,
  'RUN-01 active job remains null until the enqueue transaction claims it'
);

select throws_ok(
  $$
    insert into public.report_jobs (
      report_request_id,
      user_id,
      confirmed_entity_id,
      trace_id,
      prompt_bundle_version
    )
    values (
      '44444444-4444-4444-8444-444444444444',
      '22222222-2222-4222-8222-222222222222',
      '33333333-3333-4333-8333-333333333333',
      'bad trace',
      'prompt-v1'
    )
  $$,
  '23514',
  null,
  'NFR-04 report jobs reject unbounded trace identifiers'
);

insert into public.job_checkpoints (
  job_id,
  stage,
  attempt,
  payload,
  payload_hash
)
values (
  '55555555-5555-4555-8555-555555555555',
  'research_business',
  1,
  '{"schemaVersion":1,"findings":[]}'::jsonb,
  repeat('a', 64)
);

select throws_ok(
  $$
    insert into public.job_checkpoints (
      job_id, stage, attempt, payload, payload_hash
    )
    values (
      '55555555-5555-4555-8555-555555555555',
      'research_business',
      1,
      '{}'::jsonb,
      repeat('b', 64)
    )
  $$,
  '23505',
  null,
  'NFR-01 checkpoint completion is idempotent by job, stage and attempt'
);

insert into public.evidence (
  id,
  job_id,
  entity_id,
  url,
  canonical_url,
  title,
  publisher,
  source_tier,
  accessed_at,
  excerpt,
  content_hash,
  entity_identifiers,
  company_controlled,
  extraction_method,
  retention_class
)
values (
  '66666666-6666-4666-8666-666666666666',
  '55555555-5555-4555-8555-555555555555',
  '33333333-3333-4333-8333-333333333333',
  'https://example.invalid/privacy',
  'https://example.invalid/privacy',
  'Privacy Policy',
  'Evidence Example',
  2,
  now(),
  'The public page identifies the legal entity.',
  repeat('c', 64),
  '{"legalNames":["Evidence Example Private Limited"],"cins":["U62099MH2024PTC999999"],"addresses":[]}'::jsonb,
  true,
  'fixture',
  'with_report'
);

select throws_ok(
  $$
    insert into public.evidence (
      job_id, url, canonical_url, title, publisher, source_tier,
      accessed_at, excerpt, content_hash, entity_identifiers,
      company_controlled, extraction_method, retention_class
    )
    values (
      '55555555-5555-4555-8555-555555555555',
      'https://example.invalid/source',
      'https://example.invalid/source',
      'Source',
      'Publisher',
      2,
      now(),
      'bounded excerpt',
      repeat('d', 64),
      '{"legalNames":[],"cins":[],"addresses":[],"unexpected":"reject"}'::jsonb,
      false,
      'fixture',
      'raw_30d'
    )
  $$,
  '23514',
  null,
  'RUN-06 evidence identifiers reject unknown fields'
);

select throws_ok(
  $$
    insert into public.claims (
      job_id, entity_id, subject, predicate, object, display_text,
      claim_type, confidence, freshness, model_prompt_version, is_material
    )
    values (
      '55555555-5555-4555-8555-555555555555',
      '33333333-3333-4333-8333-333333333333',
      'Evidence Example Private Limited',
      'status',
      'active',
      'The company is active.',
      'verified_fact',
      'high',
      'current',
      'prompt-v1',
      true
    )
  $$,
  '23514',
  null,
  'RUN-04 material claims require evidence IDs'
);

insert into public.claims (
  job_id,
  entity_id,
  subject,
  predicate,
  object,
  display_text,
  claim_type,
  evidence_ids,
  confidence,
  freshness,
  verifier_status,
  report_sections,
  model_prompt_version,
  is_material
)
values (
  '55555555-5555-4555-8555-555555555555',
  '33333333-3333-4333-8333-333333333333',
  'Evidence Example Private Limited',
  'status',
  'active',
  'The company is active.',
  'verified_fact',
  array['66666666-6666-4666-8666-666666666666']::uuid[],
  'high',
  'current',
  'approved',
  array['corporate'],
  'prompt-v1',
  true
);

select throws_ok(
  $$
    insert into public.claims (
      job_id, entity_id, subject, predicate, object, display_text,
      claim_type, evidence_ids, confidence, freshness, model_prompt_version, is_material
    )
    values (
      '55555555-5555-4555-8555-555555555555',
      '33333333-3333-4333-8333-333333333333',
      'Evidence Example Private Limited',
      'status',
      'unknown',
      'The status is unknown.',
      'inference',
      array['77777777-7777-4777-8777-777777777777']::uuid[],
      'low',
      'dated',
      'prompt-v1',
      false
    )
  $$,
  '23514',
  'CLAIM_EVIDENCE_REFERENCE_INVALID',
  'RUN-04 claims can reference only evidence from the same job'
);

insert into public.agent_runs (
  job_id,
  agent_type,
  model_id,
  provider,
  prompt_version,
  routing_version,
  input_tokens,
  output_tokens,
  cost_inr,
  latency_ms,
  zdr_enforced,
  result
)
values (
  '55555555-5555-4555-8555-555555555555',
  'evidence_synthesis',
  'vendor/example-mid-v1',
  'openrouter',
  'prompt-v1',
  'routing-v1',
  100,
  50,
  1.25,
  250,
  true,
  'ok'
);

select throws_ok(
  $$
    insert into public.agent_runs (
      job_id, agent_type, model_id, provider, prompt_version,
      routing_version, input_tokens, output_tokens, cost_inr,
      latency_ms, zdr_enforced, result
    )
    values (
      '55555555-5555-4555-8555-555555555555',
      'evidence_synthesis',
      'vendor/example-mid-v1',
      'openrouter',
      'prompt-v1',
      'routing-v1',
      0,
      0,
      0,
      0,
      false,
      'refused'
    )
  $$,
  '23514',
  null,
  'SEC-11 agent run audit rejects missing ZDR proof'
);

insert into public.provider_cost_events (
  job_id,
  provider,
  unit,
  quantity,
  cost_inr
)
values (
  '55555555-5555-4555-8555-555555555555',
  'openrouter',
  'model_tokens',
  150,
  1.25
);

select throws_ok(
  $$
    insert into public.provider_cost_events (
      job_id, provider, unit, quantity, cost_inr
    )
    values (
      '55555555-5555-4555-8555-555555555555',
      'openrouter',
      'model_tokens',
      150,
      -1
    )
  $$,
  '23514',
  null,
  'NFR-05 provider cost events reject negative costs'
);

select * from finish();

rollback;
