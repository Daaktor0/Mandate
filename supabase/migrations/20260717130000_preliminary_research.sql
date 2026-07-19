begin;

alter table public.report_requests
  add column preliminary_evidence jsonb null
    check (
      preliminary_evidence is null
      or jsonb_typeof(preliminary_evidence) = 'array'
    );

comment on column public.report_requests.preliminary_evidence is
  'Bounded admitted public-source metadata captured before a paid report job exists; no identity, billing or matter narrative.';

create or replace function private.complete_preliminary_research(
  p_task_id uuid,
  p_report_request_id uuid,
  p_user_id uuid,
  p_clarification_set jsonb,
  p_preliminary_evidence jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_request public.report_requests%rowtype;
begin
  select *
    into v_request
    from public.report_requests
   where id = p_report_request_id
     and user_id = p_user_id
   for update;

  if not found or v_request.confirmed_entity_id is null then
    raise exception 'PRELIMINARY_REQUEST_NOT_FOUND' using errcode = 'P0002';
  end if;

  if v_request.state = 'awaiting_clarification' then
    return jsonb_build_object(
      'state', v_request.state,
      'questions', coalesce(v_request.clarifications, '[]'::jsonb)
    );
  end if;

  if v_request.state <> 'preliminary_research' then
    raise exception 'PRELIMINARY_STATE_CONFLICT' using errcode = 'P0001';
  end if;

  if jsonb_typeof(p_clarification_set) <> 'object'
     or jsonb_typeof(p_clarification_set -> 'questions') <> 'array'
     or jsonb_array_length(p_clarification_set -> 'questions') not between 1 and 8
     or p_clarification_set ->> 'reportRequestId' <> p_report_request_id::text
     or p_clarification_set ->> 'entityId' <> v_request.confirmed_entity_id::text
  then
    raise exception 'INVALID_CLARIFICATION_SET' using errcode = '22023';
  end if;

  if jsonb_typeof(p_preliminary_evidence) <> 'array'
     or jsonb_array_length(p_preliminary_evidence) > 20
  then
    raise exception 'INVALID_PRELIMINARY_EVIDENCE' using errcode = '22023';
  end if;

  update public.report_requests
     set clarifications = p_clarification_set -> 'questions',
         preliminary_evidence = p_preliminary_evidence,
         state = 'awaiting_clarification'
   where id = v_request.id;

  return jsonb_build_object(
    'state', 'awaiting_clarification',
    'questions', p_clarification_set -> 'questions'
  );
end;
$$;

create or replace function private.fail_preliminary_research(
  p_task_id uuid,
  p_report_request_id uuid,
  p_error_code text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_state public.request_state;
begin
  if p_error_code is null or p_error_code !~ '^[a-z0-9_:-]{1,100}$' then
    raise exception 'INVALID_PRELIMINARY_FAILURE_CODE' using errcode = '22023';
  end if;

  select state
    into v_state
    from public.report_requests
   where id = p_report_request_id
   for update;

  if not found then
    raise exception 'PRELIMINARY_REQUEST_NOT_FOUND' using errcode = 'P0002';
  end if;

  if v_state = 'failed_no_charge' then
    return jsonb_build_object('state', v_state);
  end if;
  if v_state <> 'preliminary_research' then
    raise exception 'PRELIMINARY_STATE_CONFLICT' using errcode = 'P0001';
  end if;

  update public.report_requests
     set state = 'failed_no_charge'
   where id = p_report_request_id;
  return jsonb_build_object('state', 'failed_no_charge');
end;
$$;

revoke all on function private.complete_preliminary_research(
  uuid, uuid, uuid, jsonb, jsonb
) from public, anon, authenticated;
grant execute on function private.complete_preliminary_research(
  uuid, uuid, uuid, jsonb, jsonb
) to service_role;

revoke all on function private.fail_preliminary_research(
  uuid, uuid, text
) from public, anon, authenticated;
grant execute on function private.fail_preliminary_research(
  uuid, uuid, text
) to service_role;

commit;
