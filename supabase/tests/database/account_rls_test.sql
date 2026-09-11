begin;
create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;
select plan(13);

-- The rollback-only runner can target an already initialized staging project.
-- Preserve existing identities; verify bootstrap refuses to replace its Admin.
create temporary table prior_admins as select user_id from public.entitlements where is_admin;
grant select on prior_admins to service_role;

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
select case when exists(select 1 from prior_admins) then throws_ok(
  $$select public.bootstrap_first_admin('11111111-1111-4111-8111-111111111111', 'rls_test')$$,
  'an administrator already exists', 'bootstrap preserves an existing administrator'
) else ok(public.bootstrap_first_admin('11111111-1111-4111-8111-111111111111', 'rls_test'), 'first admin bootstrapped') end;
select ok(not exists(select 1 from prior_admins p left join public.entitlements e on e.user_id=p.user_id
  where e.is_admin is distinct from true), 'bootstrap never revokes existing administrators');
-- A synthetic actor for the independent entitlement/audit tests below.
update public.entitlements set is_admin=true where user_id='11111111-1111-4111-8111-111111111111';
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
