begin;
create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;
select plan(23);

insert into auth.users(id, aud, role, email, email_confirmed_at, raw_app_meta_data, raw_user_meta_data)
values
  ('55555555-5555-4555-8555-555555555555', 'authenticated', 'authenticated', 'alerts-a@example.invalid', now(), '{}', '{}'),
  ('66666666-6666-4666-8666-666666666666', 'authenticated', 'authenticated', 'alerts-b@example.invalid', now(), '{}', '{}'),
  ('77777777-7777-4777-8777-777777777777', 'authenticated', 'authenticated', 'alerts-free@example.invalid', now(), '{}', '{}'),
  ('88888888-8888-4888-8888-888888888888', 'authenticated', 'authenticated', 'alerts-pro@example.invalid', now(), '{}', '{}'),
  ('99999999-9999-4999-8999-999999999999', 'authenticated', 'authenticated', 'alerts-demo@example.invalid', now(), '{}', '{}'),
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'authenticated', 'authenticated', 'alerts-admin@example.invalid', now(), '{}', '{}');

set local role service_role;
set local request.jwt.claims = '{"sub":"00000000-0000-0000-0000-000000000000","role":"service_role"}';
select ok(public.service_set_user_telegram_connection(
  '55555555-5555-4555-8555-555555555555', 'linked-chat-a', true
) is not null, 'trusted service links verified Telegram destination');
select public.service_set_user_telegram_connection('77777777-7777-4777-8777-777777777777', 'linked-chat-free', true);
select public.service_set_user_telegram_connection('88888888-8888-4888-8888-888888888888', 'linked-chat-pro', true);
select public.service_set_user_telegram_connection('99999999-9999-4999-8999-999999999999', 'linked-chat-demo', true);
select public.service_set_user_telegram_connection('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'linked-chat-admin', true);
update public.entitlements set pro_active = true where user_id = '88888888-8888-4888-8888-888888888888';
update public.entitlements set demo_expires_at = now() + interval '1 hour', demo_environment = 'staging'
  where user_id = '99999999-9999-4999-8999-999999999999';
update public.entitlements set is_admin = true where user_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

set local role authenticated;
set local request.jwt.claims = '{"sub":"55555555-5555-4555-8555-555555555555","role":"authenticated"}';
select lives_ok(
  $$select public.create_my_pool_alert('canonical-pool-a', 65, 'free', 'immediate', '22:00', '07:00', 'UTC', 1440, 'alert-request-a')$$,
  'user creates own canonical pool alert'
);
select is(jsonb_array_length(public.list_my_pool_alerts()), 1, 'created alert is listed for owner');
select is(public.list_my_pool_alerts() -> 0 ->> 'target_pool_id', 'canonical-pool-a', 'stable pool ID is retained');
select lives_ok(
  $$select public.update_my_pool_alert(
    (select id from public.notification_rules where user_id = auth.uid()),
    70, 'free', 'digest', null, null, 'UTC', 10080
  )$$,
  'owner edits alert semantics'
);
select is((select minimum_strength from public.notification_rules where user_id = auth.uid()), 70, 'edit persisted');
select ok(public.set_my_pool_alert_enabled(
  (select id from public.notification_rules where user_id = auth.uid()), false
), 'owner pauses alert');
select ok(not (select enabled from public.notification_rules where user_id = auth.uid()), 'paused state persisted');
select ok(public.set_my_pool_alert_enabled(
  (select id from public.notification_rules where user_id = auth.uid()), true
), 'owner resumes alert');
select is(
  (public.create_my_pool_alert('canonical-pool-a', 65, 'free', 'immediate', null, null, 'UTC', 1440, 'alert-request-a') ->> 'id'),
  (select id::text from public.notification_rules where user_id = auth.uid()),
  'repeated create request is idempotent'
);

set local request.jwt.claims = '{"sub":"66666666-6666-4666-8666-666666666666","role":"authenticated"}';
select is(jsonb_array_length(public.list_my_pool_alerts()), 0, 'second user cannot read first user alert');
select throws_ok(
  $$select public.update_my_pool_alert(
    (select id from public.notification_rules where user_id = '55555555-5555-4555-8555-555555555555'),
    10, 'all', 'immediate', null, null, 'UTC', 60
  )$$,
  'alert unavailable',
  'second user cannot update first user alert'
);
select ok(not public.set_my_pool_alert_enabled(
  (select id from public.notification_rules where user_id = '55555555-5555-4555-8555-555555555555'), false
), 'second user cannot pause first user alert');
select ok(not public.delete_my_pool_alert(
  (select id from public.notification_rules where user_id = '55555555-5555-4555-8555-555555555555')
), 'second user cannot delete first user alert');
select throws_ok(
  $$select public.create_my_pool_alert('pool-b', 0, 'all', 'immediate', null, null, 'UTC', 1440, 'alert-request-b')$$,
  'verified Telegram connection required',
  'unlinked user cannot create externally routed alert'
);

set local request.jwt.claims = '{"sub":"55555555-5555-4555-8555-555555555555","role":"authenticated"}';
select ok(public.delete_my_pool_alert(
  (select id from public.notification_rules where user_id = auth.uid())
), 'owner deletes alert');
select is(jsonb_array_length(public.list_my_pool_alerts()), 0, 'deleted alert is absent from product list');
select ok((select deleted_at is not null and not enabled from public.notification_rules where user_id = auth.uid()),
  'delete is an auditable disabled tombstone');

set local request.jwt.claims = '{"sub":"77777777-7777-4777-8777-777777777777","role":"authenticated"}';
select throws_ok(
  $$select public.create_my_pool_alert('free-pool', 60, 'pro', 'immediate', null, null, 'UTC', 1440, 'free-pro-request')$$,
  'Pro entitlement required',
  'free account cannot create a Pro-tier alert'
);

set local request.jwt.claims = '{"sub":"88888888-8888-4888-8888-888888888888","role":"authenticated"}';
select lives_ok(
  $$select public.create_my_pool_alert('pro-pool', 60, 'pro', 'immediate', null, null, 'UTC', 1440, 'pro-alert-request')$$,
  'Pro account can create a Pro-tier alert'
);

set local request.jwt.claims = '{"sub":"99999999-9999-4999-8999-999999999999","role":"authenticated"}';
select throws_ok(
  $$select public.create_my_pool_alert('demo-pool', 60, 'free', 'immediate', null, null, 'UTC', 1440, 'demo-alert-request')$$,
  'external delivery is unavailable for demo access',
  'demo access cannot create an external-delivery alert'
);

set local request.jwt.claims = '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';
select lives_ok(
  $$select public.create_my_pool_alert('admin-pool', 60, 'pro', 'immediate', null, null, 'UTC', 1440, 'admin-alert-request')$$,
  'admin entitlement can create a Pro-tier alert'
);

reset role;
set local role anon;
set local request.jwt.claims = '{"role":"anon"}';
select throws_ok(
  $$select public.list_my_pool_alerts()$$,
  '42501',
  'permission denied for function list_my_pool_alerts',
  'anonymous alert listing rejected before function execution'
);

select * from finish();
rollback;
