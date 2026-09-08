begin;
create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;
select plan(17);

insert into auth.users(id, aud, role, email, email_confirmed_at, raw_app_meta_data, raw_user_meta_data)
values
  ('33333333-3333-4333-8333-333333333333', 'authenticated', 'authenticated', 'notify-a@example.invalid', now(), '{}', '{}'),
  ('44444444-4444-4444-8444-444444444444', 'authenticated', 'authenticated', 'notify-b@example.invalid', now(), '{}', '{}');

set local role service_role;
set local request.jwt.claims = '{"sub":"00000000-0000-0000-0000-000000000000","role":"service_role"}';
select public.service_set_user_telegram_connection('33333333-3333-4333-8333-333333333333', 'chat-a', true);
select public.service_set_user_telegram_connection('44444444-4444-4444-8444-444444444444', 'chat-b', true);

set local role authenticated;
set local request.jwt.claims = '{"sub":"33333333-3333-4333-8333-333333333333","role":"authenticated"}';
select public.create_my_pool_alert('pool-a', 60, 'all', 'immediate', null, null, 'UTC', 1440, 'request-a-123');

set local request.jwt.claims = '{"sub":"44444444-4444-4444-8444-444444444444","role":"authenticated"}';
select public.create_my_pool_alert('pool-b', 60, 'all', 'immediate', null, null, 'UTC', 1440, 'request-b-123');

reset role;
set local role service_role;
set local request.jwt.claims = '{"sub":"00000000-0000-0000-0000-000000000000","role":"service_role"}';
insert into public.automation_runs(id, invocation_key, worker_instance, scheduled_for, finished_at, scan_outcome)
values('cccccccc-cccc-4ccc-8ccc-cccccccccccc', 'rls-automation-test', 'pgtap', now(), now(), 'succeeded');
insert into public.signal_snapshots(id, run_id, signal_fingerprint, payload)
values('dddddddd-dddd-4ddd-8ddd-dddddddddddd', 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', repeat('a', 64), '{"tier":"free"}');
insert into public.notification_deliveries(id, run_id, rule_id, signal_snapshot_id,
  logical_delivery_key, message_text, state, attempt_count, delivered_at)
select 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
  r.id, 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', repeat('b', 64), 'market-only message a', 'delivered', 1, now()
from public.notification_rules r where r.user_id = '33333333-3333-4333-8333-333333333333';
insert into public.notification_deliveries(id, run_id, rule_id, signal_snapshot_id,
  logical_delivery_key, message_text, state, attempt_count, delivered_at)
select 'ffffffff-ffff-4fff-8fff-ffffffffffff', 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
  r.id, 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', repeat('c', 64), 'market-only message b', 'delivered', 1, now()
from public.notification_rules r where r.user_id = '44444444-4444-4444-8444-444444444444';
insert into public.notification_delivery_attempts(delivery_id, attempt_number, worker_instance, finished_at, outcome)
values
  ('eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', 1, 'pgtap', now(), 'delivered'),
  ('ffffffff-ffff-4fff-8fff-ffffffffffff', 1, 'pgtap', now(), 'delivered');
select lives_ok(
  $$select public.service_record_notification_rule_evaluations(
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    array[(select id from public.notification_rules where user_id = '33333333-3333-4333-8333-333333333333')],
    array[(select id from public.notification_rules where user_id = '33333333-3333-4333-8333-333333333333')]
  )$$,
  'worker records durable per-rule evaluation and trigger status'
);
select ok(
  (select last_evaluated_at is not null and last_triggered_at is not null
   from public.notification_rules where user_id = '33333333-3333-4333-8333-333333333333'),
  'recorded monitoring status is visible on the alert row'
);

set local role authenticated;
set local request.jwt.claims = '{"sub":"33333333-3333-4333-8333-333333333333","role":"authenticated"}';
select is((select count(*)::integer from public.notification_rules), 1, 'user sees only own notification rule');
select is((select telegram_chat_id from public.notification_rules), null, 'raw Telegram routing is absent from user rule');
select is((select count(*)::integer from public.notification_deliveries), 1, 'user sees only own delivery');
select is((select count(*)::integer from public.notification_delivery_attempts), 1, 'user sees only own attempts');
select is((select count(*)::integer from public.notification_delivery_history), 1, 'history view preserves RLS');
select ok(not has_table_privilege('authenticated', 'public.notification_rules', 'INSERT'), 'direct rule fabrication denied');
select ok(not has_table_privilege('authenticated', 'public.notification_rules', 'UPDATE'), 'direct rule mutation denied');
select ok(not has_table_privilege('authenticated', 'public.notification_deliveries', 'INSERT'), 'delivery fabrication denied');
select ok(not has_table_privilege('authenticated', 'public.telegram_connections', 'SELECT'), 'raw routing table denied');
select ok(has_function_privilege('authenticated', 'public.request_notification_test(uuid)', 'EXECUTE'), 'scoped test RPC allowed');
select ok(not has_function_privilege('authenticated', 'public.service_claim_telegram_delivery(text)', 'EXECUTE'), 'worker claim denied');
select ok((public.get_my_telegram_status() ->> 'available')::boolean, 'safe linked status is visible');
select ok(public.get_my_telegram_status()::text not like '%chat-a%', 'safe status omits raw destination');
select lives_ok(
  $$select public.request_notification_test((select id from public.notification_rules limit 1))$$,
  'user can request a test for own enabled alert'
);
select throws_ok(
  $$select public.request_notification_test((select id from public.notification_rules where user_id = '44444444-4444-4444-8444-444444444444'))$$,
  'enabled alert with verified Telegram connection required',
  'user cannot request a test for another account alert'
);

select * from finish();
rollback;
