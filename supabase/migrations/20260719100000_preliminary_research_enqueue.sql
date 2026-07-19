begin;

create or replace function public.confirm_report_request_entity(
  p_report_request_id uuid,
  p_action text,
  p_candidate_id uuid,
  p_related_entity_ids uuid[],
  p_legal_name text,
  p_cin text,
  p_state text,
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
  v_candidate public.entity_candidates;
  v_related_entity_ids uuid[] := coalesce(p_related_entity_ids, '{}'::uuid[]);
  v_command jsonb;
  v_existing private.entity_confirmation_commands;
  v_response jsonb;
  v_task_id uuid;
  v_outbox_key text;
begin
  if v_user_id is null then
    raise exception 'UNAUTHENTICATED' using errcode = '42501';
  end if;
  if p_action not in ('confirm', 'none_of_these', 'refine') then
    raise exception 'INVALID_CONFIRMATION_ACTION' using errcode = '22023';
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
  if cardinality(v_related_entity_ids) > 2
    or not private.uuid_array_is_unique(v_related_entity_ids)
  then
    raise exception 'INVALID_RELATED_ENTITY_SCOPE' using errcode = '22023';
  end if;
  if p_legal_name is not null
    and (
      btrim(p_legal_name) = ''
      or char_length(btrim(p_legal_name)) > 300
    )
  then
    raise exception 'INVALID_LEGAL_NAME' using errcode = '22023';
  end if;
  if p_cin is not null
    and upper(btrim(p_cin)) !~ '^[UL][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$'
  then
    raise exception 'INVALID_CIN' using errcode = '22023';
  end if;
  if p_state is not null
    and (
      btrim(p_state) = ''
      or char_length(btrim(p_state)) > 100
    )
  then
    raise exception 'INVALID_STATE_HINT' using errcode = '22023';
  end if;

  if p_action = 'confirm' then
    if p_candidate_id is null
      or p_legal_name is not null
      or p_cin is not null
      or p_state is not null
    then
      raise exception 'INVALID_CONFIRMATION_PAYLOAD' using errcode = '22023';
    end if;
  elsif p_action = 'none_of_these' then
    if p_candidate_id is not null
      or cardinality(v_related_entity_ids) <> 0
      or p_legal_name is not null
      or p_cin is not null
      or p_state is not null
    then
      raise exception 'INVALID_CONFIRMATION_PAYLOAD' using errcode = '22023';
    end if;
  else
    if p_candidate_id is not null
      or cardinality(v_related_entity_ids) <> 0
      or (p_legal_name is null and p_cin is null)
    then
      raise exception 'INVALID_CONFIRMATION_PAYLOAD' using errcode = '22023';
    end if;
  end if;

  v_command := jsonb_strip_nulls(
    jsonb_build_object(
      'action', p_action,
      'candidateId', p_candidate_id,
      'relatedEntityIds', to_jsonb(v_related_entity_ids),
      'legalName', case when p_legal_name is null then null else btrim(p_legal_name) end,
      'cin', case when p_cin is null then null else upper(btrim(p_cin)) end,
      'state', case when p_state is null then null else btrim(p_state) end
    )
  );

  perform pg_advisory_xact_lock(
    hashtextextended(v_user_id::text || ':' || p_report_request_id::text, 2)
  );

  if p_idempotency_key is not null then
    select command.*
      into v_existing
      from private.entity_confirmation_commands as command
     where command.user_id = v_user_id
       and command.report_request_id = p_report_request_id
       and command.idempotency_key = p_idempotency_key;
    if found then
      if v_existing.request_payload <> v_command then
        raise exception 'IDEMPOTENCY_CONFLICT' using errcode = 'P0001';
      end if;
      return v_existing.response_payload;
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
  if p_action in ('confirm', 'none_of_these')
    and v_request.state <> 'awaiting_entity_confirmation'::public.request_state
  then
    raise exception 'CONFIRMATION_STATE_CONFLICT' using errcode = 'P0001';
  end if;
  if p_action = 'refine'
    and v_request.state not in (
      'draft'::public.request_state,
      'awaiting_entity_confirmation'::public.request_state,
      'failed_no_charge'::public.request_state
    )
  then
    raise exception 'CONFIRMATION_STATE_CONFLICT' using errcode = 'P0001';
  end if;

  if p_action = 'confirm' then
    select candidate.*
      into v_candidate
      from public.entity_candidates as candidate
     where candidate.id = p_candidate_id
       and candidate.report_request_id = p_report_request_id;
    if not found then
      raise exception 'ENTITY_CANDIDATE_NOT_FOUND' using errcode = 'P0002';
    end if;
    if v_candidate.entity_id = any(v_related_entity_ids) then
      raise exception 'INVALID_RELATED_ENTITY_SCOPE' using errcode = '22023';
    end if;
    if exists (
      select 1
        from unnest(v_related_entity_ids) as related(entity_id)
       where not exists (
         select 1
           from public.entity_candidates as candidate
          where candidate.report_request_id = p_report_request_id
            and candidate.entity_id = related.entity_id
            and nullif(candidate.candidate_payload ->> 'relatedEntityReason', '') is not null
       )
    ) then
      raise exception 'INVALID_RELATED_ENTITY_SCOPE' using errcode = '22023';
    end if;

    update public.entity_candidates
       set is_selected = (id = p_candidate_id)
     where report_request_id = p_report_request_id;

    update public.report_requests
       set confirmed_entity_id = v_candidate.entity_id,
           related_entity_ids = v_related_entity_ids,
           state = 'preliminary_research'
     where id = p_report_request_id;

    v_task_id := gen_random_uuid();
    v_outbox_key := 'preliminary:' || v_user_id::text || ':'
      || p_report_request_id::text || ':'
      || coalesce(p_idempotency_key, v_task_id::text);

    insert into public.outbox (id, topic, payload, idempotency_key)
    values (
      v_task_id,
      'mandate_light_tasks',
      jsonb_build_object(
        'schemaVersion', 1,
        'taskId', v_task_id,
        'taskType', 'preliminary_research',
        'reportRequestId', p_report_request_id,
        'userId', v_user_id,
        'attempt', 1,
        'traceId', p_trace_id
      ),
      v_outbox_key
    );

    v_response := jsonb_build_object(
      'state', 'preliminary_research',
      'confirmedEntityId', v_candidate.entity_id,
      'relatedEntityIds', to_jsonb(v_related_entity_ids),
      'guidance', null
    );
  elsif p_action = 'none_of_these' then
    delete from public.entity_candidates
     where report_request_id = p_report_request_id;

    update public.report_requests
       set resolution_legal_name_hint = null,
           resolution_cin_hint = null,
           resolution_state_hint = null,
           confirmed_entity_id = null,
           related_entity_ids = '{}'::uuid[],
           state = 'draft'
     where id = p_report_request_id;

    v_response := jsonb_build_object(
      'state', 'draft',
      'confirmedEntityId', null,
      'relatedEntityIds', jsonb_build_array(),
      'guidance', 'Enter the registered legal name or add the CIN to distinguish the company.'
    );
  else
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

    update public.report_requests
       set resolution_legal_name_hint = case
             when p_legal_name is null then null
             else btrim(p_legal_name)
           end,
           resolution_cin_hint = case
             when p_cin is null then null
             else upper(btrim(p_cin))
           end,
           resolution_state_hint = case
             when p_state is null then null
             else btrim(p_state)
           end,
           confirmed_entity_id = null,
           related_entity_ids = '{}'::uuid[],
           state = 'draft'
     where id = p_report_request_id;

    v_task_id := gen_random_uuid();
    v_outbox_key := 'refine:' || v_user_id::text || ':'
      || p_report_request_id::text || ':'
      || coalesce(p_idempotency_key, v_task_id::text);

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
      v_outbox_key
    );

    update public.report_requests
       set state = 'resolving_entity'
     where id = p_report_request_id;

    v_response := jsonb_build_object(
      'state', 'resolving_entity',
      'confirmedEntityId', null,
      'relatedEntityIds', jsonb_build_array(),
      'guidance', 'Entity resolution restarted with the refined public identifiers.'
    );
  end if;

  if p_idempotency_key is not null then
    insert into private.entity_confirmation_commands (
      user_id,
      report_request_id,
      idempotency_key,
      request_payload,
      response_payload
    )
    values (
      v_user_id,
      p_report_request_id,
      p_idempotency_key,
      v_command,
      v_response
    );
  end if;

  return v_response;
end;
$$;

revoke all on function public.confirm_report_request_entity(
  uuid,
  text,
  uuid,
  uuid[],
  text,
  text,
  text,
  text,
  text
) from public, anon;

grant execute on function public.confirm_report_request_entity(
  uuid,
  text,
  uuid,
  uuid[],
  text,
  text,
  text,
  text,
  text
) to authenticated;

commit;
