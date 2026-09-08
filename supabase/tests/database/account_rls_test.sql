begin;
create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;
select plan(12);

insert into auth.users(id, aud, role, email, email_confirmed_at, raw_app_meta_data, raw_user_meta_data)
values
  ('11111111-1111-4111-8111-111111111111', 'authenticated', 'authenticated', 'rls-a@example.invalid', now(), '{}', '{}'),
  ('22222222-2222-4222-8222-222222222222', 'authenticated', 'authenticated', 'rls-b@example.invalid', now(), '{}', '{}');

set local role authenticated;
set local request.jwt.claims = '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated"}';

select is((select count(*)::integer from public.profiles), 1, 'user sees only own profile');
select is((select count(*)::integer from public.entitlements), 1, 'user sees only own entitlement');
select is((select count(*)::integer from public.subscriptions), 0, 'user sees no other subscriptions');
select ok(has_column_privilege('authenticated', 'public.profiles', 'display_name', 'UPDATE'), 'safe profile field writable');
select ok(has_column_privilege('authenticated', 'public.profiles', 'timezone', 'UPDATE'), 'safe timezone field writable');
select ok(not has_table_privilege('authenticated', 'public.entitlements', 'UPDATE'), 'entitlement self-write denied');
select ok(not has_table_privilege('authenticated', 'public.subscriptions', 'INSERT'), 'subscription self-write denied');
select ok(not has_table_privilege('authenticated', 'public.admin_audit', 'INSERT'), 'audit fabrication denied');
select ok(
  not has_function_privilege(
    'authenticated',
    'public.service_set_entitlement(uuid,text,boolean,uuid,text,timestamptz,text,text)',
    'EXECUTE'
  ),
  'trusted entitlement function denied to authenticated users'
);

reset role;
set local role service_role;
set local request.jwt.claims = '{"sub":"00000000-0000-0000-0000-000000000000","role":"service_role"}';
select ok(public.bootstrap_first_admin('11111111-1111-4111-8111-111111111111', 'rls_test'), 'first admin bootstrapped');
select ok(
  public.service_set_entitlement(
    '22222222-2222-4222-8222-222222222222', 'pro', true,
    '11111111-1111-4111-8111-111111111111', 'rls_test', null, null, 'admin_cli'
  ),
  'service role can grant reviewed Pro'
);
select is(
  (select count(*)::integer from public.admin_audit where target_user_id = '22222222-2222-4222-8222-222222222222'),
  1,
  'service entitlement change creates one audit record'
);

select * from finish();
rollback;
