begin;
create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;
select plan(16);

set local role service_role;
set local request.jwt.claims = '{"sub":"00000000-0000-0000-0000-000000000000","role":"service_role"}';

create temp table worker_test_context(run_id uuid, rule_id uuid, delivery_id uuid) on commit drop;
insert into worker_test_context(run_id)
select (public.service_begin_automation_run('db-worker-schedule-slot', 'db-worker', now()) ->> 'id')::uuid;

select ok(
  not (public.service_begin_automation_run('db-worker-schedule-slot', 'other-worker', now()) ->> 'claimed')::boolean,
  'duplicate scheduler invocation is not claimed'
);

update worker_test_context set rule_id = public.service_upsert_system_notification_rule('db-test-chat', true);
select ok(rule_id is not null, 'service worker creates explicit system rule') from worker_test_context;

select ok(public.service_enqueue_telegram_delivery(
  run_id, rule_id, repeat('a', 64), repeat('b', 64),
  '{"pool_id":"pool-db-1","tier":"free"}'::jsonb, 'database test message', now(), 'signal'
), 'first logical delivery is inserted') from worker_test_context;
select ok(not public.service_enqueue_telegram_delivery(
  run_id, rule_id, repeat('a', 64), repeat('b', 64),
  '{"pool_id":"pool-db-1","tier":"free"}'::jsonb, 'database test message', now(), 'signal'
), 'duplicate logical delivery is rejected by database uniqueness') from worker_test_context;

update worker_test_context
set delivery_id = (public.service_claim_telegram_delivery('db-worker') ->> 'id')::uuid;
select is((select attempt_count from public.notification_deliveries d join worker_test_context c on c.delivery_id = d.id),
  1, 'first claim creates attempt one');
select is(public.service_finish_telegram_delivery(
  delivery_id, 'db-worker', false, null, 'telegram_http_503', true, false, now()
), 'retry', 'explicit server rejection is retryable') from worker_test_context;

select is((public.service_claim_telegram_delivery('db-worker') ->> 'attempt_count')::integer,
  2, 'retry claim creates attempt two');
select is(public.service_finish_telegram_delivery(
  delivery_id, 'db-worker', false, null, 'telegram_http_503', true, false, now()
), 'retry', 'second explicit rejection receives final backoff') from worker_test_context;

select is((public.service_claim_telegram_delivery('db-worker') ->> 'attempt_count')::integer,
  3, 'final retry claim creates attempt three');
select is(public.service_finish_telegram_delivery(
  delivery_id, 'db-worker', false, null, 'telegram_http_503', true, false, now()
), 'dead_letter', 'third failed attempt is terminal') from worker_test_context;
select is((select attempt_count from public.notification_deliveries d join worker_test_context c on c.delivery_id = d.id),
  3, 'attempt count is bounded at three');
select is((select count(*)::integer from public.notification_delivery_attempts a
  join worker_test_context c on c.delivery_id = a.delivery_id), 3, 'all three attempts are retained');

select ok(public.service_enqueue_telegram_delivery(
  run_id, rule_id, repeat('c', 64), repeat('d', 64),
  '{"pool_id":"pool-db-2","tier":"free"}'::jsonb, 'ambiguous database test', now(), 'signal'
), 'second logical delivery is inserted') from worker_test_context;
update worker_test_context
set delivery_id = (public.service_claim_telegram_delivery('crashed-worker') ->> 'id')::uuid;
update public.notification_deliveries d set claimed_at = now() - interval '10 minutes'
from worker_test_context c where d.id = c.delivery_id;
select is(public.service_recover_abandoned_deliveries(300), 1, 'one abandoned sending claim is recovered');
select is((select state from public.notification_deliveries d join worker_test_context c on c.delivery_id = d.id),
  'dead_letter', 'abandoned claim is never automatically resent');
select ok((select ambiguous_outcome from public.notification_deliveries d
  join worker_test_context c on c.delivery_id = d.id), 'abandoned claim records ambiguous outcome');

select * from finish();
rollback;
