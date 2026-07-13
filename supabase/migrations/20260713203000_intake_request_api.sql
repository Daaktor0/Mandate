begin;

alter table public.report_requests
  add column idempotency_key text null
  check (
    idempotency_key is null
    or idempotency_key ~ '^[!-~]{1,128}$'
  );

create unique index report_requests_user_idempotency_idx
  on public.report_requests (user_id, idempotency_key)
  where idempotency_key is not null;

create policy report_requests_select_own
on public.report_requests
for select
to authenticated
using (user_id = (select auth.uid()));

create or replace function public.create_report_request(
  p_input_kind public.input_kind,
  p_input_url text,
  p_input_legal_name text,
  p_input_cin text,
  p_confidential_ack boolean,
  p_idempotency_key text
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
begin
  if v_user_id is null then
    raise exception 'UNAUTHENTICATED' using errcode = '42501';
  end if;

  if p_confidential_ack is distinct from true then
    raise exception 'CONFIDENTIAL_ACK_REQUIRED' using errcode = '22023';
  end if;

  if p_idempotency_key is not null
    and p_idempotency_key !~ '^[!-~]{1,128}$'
  then
    raise exception 'INVALID_IDEMPOTENCY_KEY' using errcode = '22023';
  end if;

  -- Serialise successful creates per user so the 10/hour cap cannot be raced.
  perform pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0));

  if p_idempotency_key is not null then
    select request.*
      into v_request
      from public.report_requests as request
     where request.user_id = v_user_id
       and request.idempotency_key = p_idempotency_key;

    if found then
      return jsonb_build_object(
        'reportRequest',
        jsonb_build_object(
          'id', v_request.id,
          'inputKind', v_request.input_kind,
          'url', v_request.input_url,
          'legalName', v_request.input_legal_name,
          'cin', v_request.input_cin,
          'confidentialAckAt', v_request.confidential_ack_at,
          'state', v_request.state,
          'createdAt', v_request.created_at,
          'updatedAt', v_request.updated_at
        )
      );
    end if;
  end if;

  if (
    select count(*)
      from public.report_requests as request
     where request.user_id = v_user_id
       and request.created_at >= now() - interval '1 hour'
  ) >= 10 then
    raise exception 'INTAKE_RATE_LIMITED' using errcode = 'P0001';
  end if;

  insert into public.report_requests (
    user_id,
    input_kind,
    input_url,
    input_legal_name,
    input_cin,
    confidential_ack_at,
    idempotency_key
  )
  values (
    v_user_id,
    p_input_kind,
    p_input_url,
    p_input_legal_name,
    p_input_cin,
    transaction_timestamp(),
    p_idempotency_key
  )
  returning * into v_request;

  return jsonb_build_object(
    'reportRequest',
    jsonb_build_object(
      'id', v_request.id,
      'inputKind', v_request.input_kind,
      'url', v_request.input_url,
      'legalName', v_request.input_legal_name,
      'cin', v_request.input_cin,
      'confidentialAckAt', v_request.confidential_ack_at,
      'state', v_request.state,
      'createdAt', v_request.created_at,
      'updatedAt', v_request.updated_at
    )
  );
end;
$$;

revoke all on function public.create_report_request(
  public.input_kind,
  text,
  text,
  text,
  boolean,
  text
) from public, anon;

grant execute on function public.create_report_request(
  public.input_kind,
  text,
  text,
  text,
  boolean,
  text
) to authenticated;

commit;
