begin;
create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;
select plan(25);

insert into auth.users(id, aud, role, email, email_confirmed_at, raw_app_meta_data, raw_user_meta_data)
values
  ('10101010-1010-4010-8010-101010101010', 'authenticated', 'authenticated', 'watch-a@example.invalid', now(), '{}', '{}'),
  ('20202020-2020-4020-8020-202020202020', 'authenticated', 'authenticated', 'watch-b@example.invalid', now(), '{}', '{}');

set local role authenticated;
set local request.jwt.claims = '{"sub":"10101010-1010-4010-8010-101010101010","role":"authenticated"}';
select lives_ok($$select public.save_my_pool('canonical-pool-x')$$, 'User A saves Pool X');
select is(jsonb_array_length(public.list_my_saved_pools()), 1, 'User A sees the saved pool');
select is(public.list_my_saved_pools() -> 0 ->> 'pool_id', 'canonical-pool-x', 'canonical identity is retained');
select is(public.save_my_pool('canonical-pool-x') ->> 'pool_id', 'canonical-pool-x', 'duplicate save is idempotent');
select is((select count(*) from public.saved_pools)::integer, 1, 'duplicate save creates one record');
select lives_ok($$select public.save_my_pool('pool-a-only')$$, 'User A can save another pool');
select is((select count(*) from public.notification_rules where user_id = auth.uid())::integer, 0,
  'saving a pool creates no Alert');

reset role;
set local role service_role;
set local request.jwt.claims = '{"sub":"00000000-0000-0000-0000-000000000000","role":"service_role"}';
insert into public.notification_rules(user_id, rule_key, rule_kind, enabled, target_type, target_pool_id)
values('10101010-1010-4010-8010-101010101010', 'watchlist-independence', 'market', false, 'pool', 'canonical-pool-x');

set local role authenticated;
set local request.jwt.claims = '{"sub":"10101010-1010-4010-8010-101010101010","role":"authenticated"}';
select ok(public.delete_my_saved_pool('canonical-pool-x'), 'User A removes own Pool X');
select is((select count(*) from public.notification_rules where user_id = auth.uid())::integer, 1,
  'removing a saved pool deletes no Alert');
select is((select count(*) from public.notification_deliveries)::integer, 0,
  'saving and removing enqueue no Telegram delivery');
select is((select count(*) from public.saved_pools where pool_id = 'canonical-pool-x')::integer, 0,
  'removed saved record is absent for User A');

set local request.jwt.claims = '{"sub":"20202020-2020-4020-8020-202020202020","role":"authenticated"}';
select is(jsonb_array_length(public.list_my_saved_pools()), 0, 'User B cannot see User A saves');
select lives_ok($$select public.save_my_pool('canonical-pool-x')$$, 'User B independently saves Pool X');
select lives_ok($$select public.save_my_pool('pool-b-only')$$, 'User B saves a private pool');
select is(jsonb_array_length(public.list_my_saved_pools()), 2, 'User B sees only own saves');
select ok(not public.delete_my_saved_pool('pool-a-only'), 'User B cannot delete User A saved pool');
select throws_ok(
  $$insert into public.saved_pools(user_id, pool_id) values('10101010-1010-4010-8010-101010101010', 'forged-owner')$$,
  '42501',
  'permission denied for table saved_pools',
  'direct caller-supplied ownership write is denied'
);

set local request.jwt.claims = '{"sub":"10101010-1010-4010-8010-101010101010","role":"authenticated"}';
select is(jsonb_array_length(public.list_my_saved_pools()), 1, 'User A still sees only own remaining save');
select ok(not public.delete_my_saved_pool('pool-b-only'), 'User A cannot delete User B saved pool');
select is(public.list_my_saved_pools() -> 0 ->> 'pool_id', 'pool-a-only', 'User A record survived User B delete attempt');

set local request.jwt.claims = '{"sub":"20202020-2020-4020-8020-202020202020","role":"authenticated"}';
select is(jsonb_array_length(public.list_my_saved_pools()), 2, 'User B records survived User A delete attempt');
select ok(public.delete_my_saved_pool('pool-b-only'), 'User B removes own saved pool');
select is(jsonb_array_length(public.list_my_saved_pools()), 1, 'User B removal persists');

reset role;
set local role service_role;
select is((select count(*) from public.saved_pools where pool_id = 'canonical-pool-x')::integer, 1,
  'the same canonical pool is independently owned by User B');

reset role;
set local role anon;
set local request.jwt.claims = '{"role":"anon"}';
select throws_ok(
  $$select public.list_my_saved_pools()$$,
  '42501',
  'permission denied for function list_my_saved_pools',
  'anonymous saved-pool listing is rejected'
);

select * from finish();
rollback;
