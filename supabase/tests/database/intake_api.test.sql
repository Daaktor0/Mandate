create extension if not exists pgtap with schema extensions;

begin;

select plan(16);

select has_column(
  'public',
  'report_requests',
  'idempotency_key',
  'INTAKE-01 request idempotency is persisted'
);

select has_function(
  'public',
  'create_report_request',
  array['public.input_kind', 'text', 'text', 'text', 'boolean', 'text'],
  'INTAKE-01 authenticated intake RPC exists'
);

select ok(
  not has_table_privilege('authenticated', 'public.report_requests', 'insert'),
  'SEC-01 authenticated clients cannot bypass the intake RPC with direct inserts'
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
    'lawyer-a@example.invalid',
    now(),
    now()
  ),
  (
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    '00000000-0000-0000-0000-000000000000',
    'authenticated',
    'authenticated',
    'lawyer-b@example.invalid',
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
    'Lawyer A',
    'IN',
    'associate'
  ),
  (
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'Lawyer B',
    'IN',
    'partner'
  );

set local role authenticated;
set local "request.jwt.claim.sub" = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

select throws_ok(
  $$
    select public.create_report_request(
      'legal_name', null, 'Example Private Limited', null, false, 'ack-failure'
    )
  $$,
  '22023',
  'CONFIDENTIAL_ACK_REQUIRED',
  'INTAKE-04 confidential acknowledgement is mandatory in the database API'
);

select is(
  public.create_report_request(
    'website', 'https://example.com/', null, null, true, 'website-request-001'
  ) -> 'reportRequest' ->> 'state',
  'draft',
  'INTAKE-01 creates a draft request'
);

select ok(
  (
    select confidential_ack_at is not null
    from public.report_requests
    where idempotency_key = 'website-request-001'
  ),
  'INTAKE-04 stores the acknowledgement timestamp'
);

select is(
  public.create_report_request(
    'website', 'https://example.com/', null, null, true, 'website-request-001'
  ) -> 'reportRequest' ->> 'id',
  (
    select id::text
    from public.report_requests
    where idempotency_key = 'website-request-001'
  ),
  'INTAKE-01 an idempotency replay returns the original request'
);

select is(
  (
    select count(*)::integer
    from public.report_requests
    where idempotency_key = 'website-request-001'
  ),
  1,
  'INTAKE-01 an idempotency replay does not duplicate the request'
);

select is(
  (
    select input_cin
    from public.report_requests
    where idempotency_key = 'website-request-001'
  ),
  null,
  'INTAKE-05 CIN remains optional'
);

select is(
  public.create_report_request(
    'legal_name',
    null,
    'Example Private Limited',
    'U12345MH2020PTC123456',
    true,
    'legal-name-request-001'
  ) -> 'reportRequest' ->> 'cin',
  'U12345MH2020PTC123456',
  'INTAKE-05 exact CIN is stored when supplied'
);

set local "request.jwt.claim.sub" = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

select results_eq(
  $$select count(*) from public.report_requests$$,
  array[0::bigint],
  'SEC-01 another user cannot read intake requests'
);

select throws_ok(
  $$
    insert into public.report_requests (
      user_id,
      input_kind,
      input_legal_name,
      confidential_ack_at
    )
    values (
      'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      'legal_name',
      'Cross-tenant Limited',
      now()
    )
  $$,
  '42501',
  null,
  'SEC-01 another user cannot insert a request for the owner'
);

set local "request.jwt.claim.sub" = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

select public.create_report_request(
  'legal_name',
  null,
  'Rate Limit Company ' || sequence::text || ' Limited',
  null,
  true,
  'rate-limit-' || sequence::text
)
from generate_series(1, 8) as sequence;

select is(
  (select count(*)::integer from public.report_requests),
  10,
  'SEC-13 ten successful requests fit the hourly intake limit'
);

select throws_ok(
  $$
    select public.create_report_request(
      'legal_name', null, 'Eleventh Company Limited', null, true, 'rate-limit-11'
    )
  $$,
  'P0001',
  'INTAKE_RATE_LIMITED',
  'SEC-13 the eleventh request is rejected atomically'
);

select is(
  public.create_report_request(
    'website', 'https://example.com/', null, null, true, 'website-request-001'
  ) -> 'reportRequest' ->> 'id',
  (
    select id::text
    from public.report_requests
    where idempotency_key = 'website-request-001'
  ),
  'INTAKE-01 replay remains available after the hourly cap'
);

select is(
  to_regclass('public.entitlement_ledger'),
  null,
  'INTAKE-06 intake has no entitlement reservation surface'
);

select * from finish();

rollback;
