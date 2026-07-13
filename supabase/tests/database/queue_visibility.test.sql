create extension if not exists pgtap with schema extensions;
create extension if not exists pgmq;

select plan(17);

select has_extension(
  'pgmq',
  'NFR-01 AS-02 pgmq is available in the supported Postgres stack'
);

select ok(
  (
    select extversion like '1.%'
    from pg_extension
    where extname = 'pgmq'
  ),
  'NFR-01 AS-02 the stack provides the specified pgmq 1.x line'
);

select lives_ok(
  $$select pgmq.create('as02_visibility_spike')$$,
  'NFR-01 AS-02 a durable test queue can be created'
);

create temporary table as02_message as
select sent.msg_id
from pgmq.send(
  'as02_visibility_spike',
  '{"schemaVersion":1,"traceId":"trace-as02-spike"}'::jsonb,
  0
) as sent(msg_id);

select cmp_ok(
  (select msg_id from as02_message),
  '>',
  0::bigint,
  'NFR-01 AS-02 send returns a durable message identifier'
);

create temporary table as02_first_lease as
select *
from pgmq.read('as02_visibility_spike', 3, 1);

select is(
  (select count(*)::integer from as02_first_lease),
  1,
  'NFR-01 AS-02 the first read leases one visible message'
);

select is(
  (select read_ct::integer from as02_first_lease),
  1,
  'NFR-01 AS-02 the initial lease has read count one'
);

select is(
  (
    select count(*)::integer
    from pgmq.read('as02_visibility_spike', 3, 1)
  ),
  0,
  'NFR-01 AS-02 a leased message is immediately invisible to another reader'
);

create temporary table as02_long_extension as
select *
from pgmq.set_vt(
  'as02_visibility_spike',
  (select msg_id from as02_message),
  1800
);

select cmp_ok(
  (select vt from as02_long_extension),
  '>=',
  clock_timestamp() + interval '29 minutes 55 seconds',
  'NFR-01 AS-02 pgmq accepts a thirty-minute visibility extension'
);

create temporary table as02_short_extension as
select *
from pgmq.set_vt(
  'as02_visibility_spike',
  (select msg_id from as02_message),
  3
);

do $$
begin
  perform pg_sleep(1);
end;
$$;

select is(
  (
    select count(*)::integer
    from pgmq.read('as02_visibility_spike', 3, 1)
  ),
  0,
  'NFR-01 AS-02 the message remains invisible before lease expiry'
);

create temporary table as02_renewed_extension as
select *
from pgmq.set_vt(
  'as02_visibility_spike',
  (select msg_id from as02_message),
  3
);

select cmp_ok(
  (select vt from as02_renewed_extension),
  '>',
  (select vt from as02_short_extension),
  'NFR-01 AS-02 renewing a lease moves visibility further into the future'
);

do $$
begin
  perform pg_sleep(1);
end;
$$;

select is(
  (
    select count(*)::integer
    from pgmq.read('as02_visibility_spike', 3, 1)
  ),
  0,
  'NFR-01 AS-02 the renewed lease remains exclusive'
);

do $$
begin
  perform pg_sleep(2.2);
end;
$$;

create temporary table as02_second_lease as
select *
from pgmq.read('as02_visibility_spike', 3, 1);

select is(
  (select count(*)::integer from as02_second_lease),
  1,
  'NFR-01 AS-02 the message becomes visible after the renewed lease expires'
);

select is(
  (select read_ct::integer from as02_second_lease),
  2,
  'NFR-01 AS-02 redelivery increments the authoritative read count'
);

select ok(
  pgmq.archive(
    'as02_visibility_spike',
    (select msg_id from as02_message)
  ),
  'NFR-01 AS-02 archive removes a completed message from the live queue'
);

select is(
  (
    select count(*)::integer
    from pgmq.a_as02_visibility_spike
    where msg_id = (select msg_id from as02_message)
  ),
  1,
  'NFR-01 AS-02 archive retains one replayable audit record'
);

select is(
  (
    select count(*)::integer
    from pgmq.read('as02_visibility_spike', 1, 1)
  ),
  0,
  'NFR-01 AS-02 an archived message cannot be leased again'
);

select lives_ok(
  $$select pgmq.drop_queue('as02_visibility_spike')$$,
  'NFR-01 AS-02 the isolated spike queue is removed cleanly'
);

select * from finish();
