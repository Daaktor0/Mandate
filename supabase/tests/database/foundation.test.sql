create extension if not exists pgtap with schema extensions;

begin;

select plan(16);

select has_table(
  'public',
  'users_profile',
  'NFR-02 users_profile exists'
);

select has_table(
  'public',
  'report_requests',
  'NFR-02 report_requests exists'
);

select has_function(
  'private',
  'is_admin',
  array[]::text[],
  'NFR-02 private is_admin helper exists'
);

select is(
  (
    select relrowsecurity and relforcerowsecurity
    from pg_class
    where oid = 'public.users_profile'::regclass
  ),
  true,
  'NFR-02 users_profile forces RLS'
);

select is(
  (
    select relrowsecurity and relforcerowsecurity
    from pg_class
    where oid = 'public.report_requests'::regclass
  ),
  true,
  'NFR-02 report_requests forces RLS'
);

select is(
  (
    select count(*)::integer
    from pg_policies
    where schemaname = 'public'
      and tablename in ('users_profile', 'report_requests')
  ),
  0,
  'NFR-02 the first migration is default deny'
);

select ok(
  not has_table_privilege('anon', 'public.users_profile', 'select'),
  'NFR-02 anon cannot select users_profile'
);

select ok(
  not has_table_privilege('anon', 'public.report_requests', 'select'),
  'NFR-02 anon cannot select report_requests'
);

select ok(
  has_table_privilege('authenticated', 'public.users_profile', 'select'),
  'NFR-02 authenticated reaches users_profile only through RLS'
);

select ok(
  has_table_privilege('authenticated', 'public.report_requests', 'select'),
  'NFR-02 authenticated reaches report_requests only through RLS'
);

select ok(
  not has_function_privilege('anon', 'private.is_admin()', 'execute'),
  'NFR-02 anon cannot execute the admin helper'
);

select ok(
  has_function_privilege('authenticated', 'private.is_admin()', 'execute'),
  'NFR-02 authenticated can check only its own admin flag'
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

insert into public.users_profile (
  user_id,
  full_name,
  country,
  professional_role,
  is_admin
)
values
  (
    '11111111-1111-4111-8111-111111111111',
    'Admin User',
    'IN',
    'other',
    true
  ),
  (
    '22222222-2222-4222-8222-222222222222',
    'Test Lawyer',
    'IN',
    'associate',
    false
  );

insert into public.report_requests (
  id,
  user_id,
  input_kind,
  input_legal_name,
  confidential_ack_at
)
values (
  '33333333-3333-4333-8333-333333333333',
  '22222222-2222-4222-8222-222222222222',
  'legal_name',
  'Example Private Limited',
  now()
);

set local role authenticated;
set local "request.jwt.claim.sub" = '11111111-1111-4111-8111-111111111111';

select is(
  private.is_admin(),
  true,
  'NFR-02 is_admin returns the server-owned flag for auth.uid'
);

select results_eq(
  $$select count(*) from public.users_profile$$,
  array[0::bigint],
  'NFR-02 authenticated users see no profile rows before an explicit policy'
);

set local "request.jwt.claim.sub" = '22222222-2222-4222-8222-222222222222';

select results_eq(
  $$select count(*) from public.report_requests$$,
  array[0::bigint],
  'NFR-02 authenticated users see no request rows before an explicit policy'
);

reset role;

select throws_ok(
  $$
    insert into public.report_requests (
      user_id,
      input_kind,
      input_url,
      input_legal_name,
      confidential_ack_at
    )
    values (
      '22222222-2222-4222-8222-222222222222',
      'website',
      'https://example.invalid',
      'Example Private Limited',
      now()
    )
  $$,
  '23514',
  'NFR-02 request input kinds cannot be combined'
);

select * from finish();

rollback;

