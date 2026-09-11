begin;
create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;
select plan(32);
set local request.jwt.claims = '{"role":"service_role"}';

insert into auth.users(id,email,email_confirmed_at,raw_app_meta_data,raw_user_meta_data)
values ('19c10000-0000-4000-8000-000000000001','admin19c1@example.invalid',now(),'{}','{}'),
       ('19c10000-0000-4000-8000-000000000002','free19c1@example.invalid',now(),'{}','{}');
update public.entitlements set is_admin=true where user_id='19c10000-0000-4000-8000-000000000001';
select public.service_sync_beta_admission(true,array['19c10000-0000-4000-8000-000000000001']::uuid[]);

select ok((select relrowsecurity from pg_class where oid='private.beta_invitations'::regclass),'RLS enabled');
select ok(not has_table_privilege('anon','private.beta_invitations','SELECT'),'anon cannot enumerate');
select ok(not has_table_privilege('authenticated','private.beta_invitations','SELECT'),'participant cannot enumerate');
select ok(not has_table_privilege('service_role','private.beta_invitations','SELECT'),'service cannot read hashes directly');
select ok(not has_function_privilege('anon','public.service_claim_beta_invitation(text)','EXECUTE'),'anon cannot redeem RPC');
select ok(not has_function_privilege('authenticated','public.service_create_beta_invitation(uuid,text)','EXECUTE'),'participant cannot issue RPC');
select ok(not has_function_privilege('authenticated','public.service_revoke_beta_invitation(uuid,uuid)','EXECUTE'),'participant cannot revoke RPC');
select ok(not has_function_privilege('authenticated','public.service_validate_beta_invitation(text)','EXECUTE'),'participant cannot probe hashes');
select ok(not has_function_privilege('service_role','private.consume_beta_invitation_for_new_user()','EXECUTE'),'trigger not publicly callable');
select ok((select proconfig @> array['search_path=""'] from pg_proc where oid='public.service_claim_beta_invitation(text)'::regprocedure),'empty search path');

set local role service_role;
select throws_ok($$select public.service_create_beta_invitation('19c10000-0000-4000-8000-000000000002',repeat('a',64))$$,'verified administrator actor required','nonadmin denied');
select lives_ok($$select public.service_create_beta_invitation('19c10000-0000-4000-8000-000000000001',repeat('a',64))$$,'admin issue');
select ok(public.service_validate_beta_invitation(repeat('a',64)),'valid unused');
select ok(not public.service_validate_beta_invitation(repeat('b',64)),'unknown denied');
select ok(not public.service_validate_beta_invitation('bad'),'malformed denied');
select ok(public.service_claim_beta_invitation(repeat('a',64)) is not null,'claim reserves one account');
select ok(public.service_claim_beta_invitation(repeat('a',64)) is null,'double claim denied');
select ok(not public.service_validate_beta_invitation(repeat('a',64)),'claimed cannot reenter');
reset role;

insert into auth.users(id,email,raw_app_meta_data,raw_user_meta_data)
select reserved_user_id,'participant19c1@example.invalid','{}','{}' from private.beta_invitations where token_digest=repeat('a',64);
select ok((select consumed_at is not null from private.beta_invitations where token_digest=repeat('a',64)),'creation consumes atomically');
select ok(not private.alert_beta_admitted((select reserved_user_id from private.beta_invitations where token_digest=repeat('a',64))),'unverified denied admission');
update auth.users set email_confirmed_at=now() where id=(select reserved_user_id from private.beta_invitations where token_digest=repeat('a',64));
select ok(private.alert_beta_admitted((select reserved_user_id from private.beta_invitations where token_digest=repeat('a',64))),'verified canonical admission');
select ok(not private.alert_paid_entitled((select reserved_user_id from private.beta_invitations where token_digest=repeat('a',64))),'no paid grants');
select public.service_sync_beta_admission(true,array['19c10000-0000-4000-8000-000000000001']::uuid[]);
select ok(private.alert_beta_admitted((select reserved_user_id from private.beta_invitations where token_digest=repeat('a',64))),'admission survives sync');
select ok(public.service_claim_beta_invitation(repeat('a',64)) is null,'consumed replay denied');
select ok(not public.service_revoke_beta_invitation('19c10000-0000-4000-8000-000000000001',(select id from private.beta_invitations where token_digest=repeat('a',64))),'invitation no longer authorizes ongoing account');

select public.service_create_beta_invitation('19c10000-0000-4000-8000-000000000001',repeat('c',64));
select public.service_revoke_beta_invitation('19c10000-0000-4000-8000-000000000001',(select id from private.beta_invitations where token_digest=repeat('c',64)));
select ok(public.service_claim_beta_invitation(repeat('c',64)) is null,'revoked denied');
select public.service_create_beta_invitation('19c10000-0000-4000-8000-000000000001',repeat('d',64));
update private.beta_invitations set created_at=now()-interval '25 hours',expires_at=now()-interval '1 hour' where token_digest=repeat('d',64);
select ok(public.service_claim_beta_invitation(repeat('d',64)) is null,'expired denied');
select public.service_create_beta_invitation('19c10000-0000-4000-8000-000000000001',repeat('e',64));
select public.service_claim_beta_invitation(repeat('e',64));
select public.service_revoke_beta_invitation('19c10000-0000-4000-8000-000000000001',(select id from private.beta_invitations where token_digest=repeat('e',64)));
select throws_ok($$insert into auth.users(id,email) select reserved_user_id,'revoked19c1@example.invalid' from private.beta_invitations where token_digest=repeat('e',64)$$,'invitation unavailable','revoked claim fails account transaction');
select ok(not exists(select 1 from auth.users where email='revoked19c1@example.invalid'),'failed transaction leaves no account');
select ok(not private.alert_beta_admitted('19c10000-0000-4000-8000-000000000002'),'other user cannot bypass admission');
select throws_ok($$select public.service_revoke_beta_invitation('19c10000-0000-4000-8000-000000000002',gen_random_uuid())$$,'verified administrator actor required','nonadmin cannot revoke');
select is((select count(*)::integer from private.beta_invitations where token_digest !~ '^[0-9a-f]{64}$'),0,'only digests stored');
select * from finish();
rollback;
