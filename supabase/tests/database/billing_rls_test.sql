begin;
create extension if not exists pgtap with schema extensions;

set local search_path = public, extensions;
select plan(25);

insert into auth.users(id, aud, role, email, email_confirmed_at, raw_app_meta_data, raw_user_meta_data)
values
  ('11111111-1111-4111-8111-111111111111', 'authenticated', 'authenticated', 'billing-a@example.invalid', now(), '{}', '{}'),
  ('22222222-2222-4222-8222-222222222222', 'authenticated', 'authenticated', 'billing-b@example.invalid', now(), '{}', '{}'),
  ('33333333-3333-4333-8333-333333333333', 'authenticated', 'authenticated', 'billing-demo@example.invalid', now(), '{}', '{}');

set local role service_role;
set local request.jwt.claims = '{"sub":"00000000-0000-0000-0000-000000000000","role":"service_role"}';

update public.entitlements set pro_active = true where user_id = '11111111-1111-4111-8111-111111111111';
update public.entitlements set demo_expires_at = now() + interval '10 minutes', demo_environment = 'staging'
where user_id = '33333333-3333-4333-8333-333333333333';

select ok(
  public.service_set_stripe_customer('11111111-1111-4111-8111-111111111111', 'cus_AAAAAAAAAAAAAAAA'),
  'service role binds a Stripe customer to the verified account'
);
select ok(
  not public.service_set_stripe_customer('11111111-1111-4111-8111-111111111111', 'cus_AAAAAAAAAAAAAAAA'),
  'repeated customer binding is idempotent'
);
select is(
  (select user_id from public.subscriptions where provider_customer_id = 'cus_AAAAAAAAAAAAAAAA'),
  '11111111-1111-4111-8111-111111111111'::uuid,
  'customer mapping belongs to User A'
);
select throws_ok(
  $$select public.service_set_stripe_customer('33333333-3333-4333-8333-333333333333', 'cus_DEMODEMODEMODEMO')$$,
  'billing changes are forbidden for demo users',
  'demo account cannot create billing state'
);

select is(
  public.service_apply_stripe_subscription(
    '11111111-1111-4111-8111-111111111111', 'cus_AAAAAAAAAAAAAAAA', 'sub_AAAAAAAAAAAAAAAA',
    'active', 'cs_AAAAAAAAAAAAAAAA', now() + interval '30 days', false, 200, 'evt_active'
  ),
  '11111111-1111-4111-8111-111111111111'::uuid,
  'active subscription applies to User A'
);
select ok(
  (select subscription_pro_active from public.entitlements where user_id = '11111111-1111-4111-8111-111111111111'),
  'active subscription grants subscription-derived Pro'
);
select ok(
  (select pro_active from public.entitlements where user_id = '11111111-1111-4111-8111-111111111111'),
  'manual Pro remains independently active'
);
select is(
  public.service_apply_stripe_subscription(
    null, 'cus_AAAAAAAAAAAAAAAA', 'sub_AAAAAAAAAAAAAAAA',
    'canceled', null, now(), false, 300, 'evt_canceled'
  ),
  '11111111-1111-4111-8111-111111111111'::uuid,
  'cancellation resolves through the trusted provider mapping'
);
select ok(
  not (select subscription_pro_active from public.entitlements where user_id = '11111111-1111-4111-8111-111111111111'),
  'cancellation removes only subscription-derived Pro'
);
select ok(
  (select pro_active from public.entitlements where user_id = '11111111-1111-4111-8111-111111111111'),
  'cancellation does not revoke the manual Pro grant'
);
select is(
  (select status from public.subscriptions where user_id = '11111111-1111-4111-8111-111111111111'),
  'canceled',
  'durable subscription state records cancellation'
);
select is(
  public.service_apply_stripe_subscription(
    null, 'cus_AAAAAAAAAAAAAAAA', 'sub_AAAAAAAAAAAAAAAA',
    'active', null, now() + interval '30 days', false, 100, 'evt_stale'
  ),
  '11111111-1111-4111-8111-111111111111'::uuid,
  'stale event is safely acknowledged for the mapped owner'
);
select is(
  (select status from public.subscriptions where user_id = '11111111-1111-4111-8111-111111111111'),
  'canceled',
  'stale event cannot overwrite newer canceled state'
);
select throws_ok(
  $$select public.service_apply_stripe_subscription(
    '22222222-2222-4222-8222-222222222222', 'cus_AAAAAAAAAAAAAAAA', 'sub_AAAAAAAAAAAAAAAA',
    'active', null, now(), false, 400, 'evt_cross_user'
  )$$,
  'provider event user mapping mismatch',
  'User B assertion cannot redirect User A webhook state'
);
select throws_ok(
  $$select public.service_apply_stripe_subscription(
    null, 'cus_REPLACEMENTCUSTOMER', 'sub_AAAAAAAAAAAAAAAA',
    'active', null, now(), false, 500, 'evt_customer_replacement'
  )$$,
  'provider customer mapping mismatch',
  'signed event cannot replace the persisted customer mapping'
);
select is(
  (select provider_customer_id from public.subscriptions where user_id = '11111111-1111-4111-8111-111111111111'),
  'cus_AAAAAAAAAAAAAAAA',
  'ownership conflict leaves the customer mapping unchanged'
);
select ok(public.service_begin_webhook_event('stripe', 'evt_duplicate', 'customer.subscription.updated'),
  'first webhook delivery is claimed');
select lives_ok(
  $$select public.service_finish_webhook_event('stripe', 'evt_duplicate', true, null)$$,
  'claimed webhook can be marked processed'
);
select ok(not public.service_begin_webhook_event('stripe', 'evt_duplicate', 'customer.subscription.updated'),
  'processed webhook duplicate is idempotently ignored');

reset role;
set local role authenticated;
set local request.jwt.claims = '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated"}';
select is((select count(user_id)::integer from public.subscriptions), 1, 'User A sees only own safe billing summary');
select ok(
  not has_column_privilege('authenticated', 'public.subscriptions', 'provider_customer_id', 'SELECT'),
  'authenticated clients cannot read Stripe customer identifiers'
);
select ok(not has_table_privilege('authenticated', 'public.subscriptions', 'INSERT'),
  'authenticated clients cannot create subscription mappings');
select ok(
  not has_function_privilege(
    'authenticated',
    'public.service_apply_stripe_subscription(uuid,text,text,text,text,timestamptz,boolean,bigint,text)',
    'EXECUTE'
  ),
  'authenticated clients cannot call fulfillment RPC'
);

set local request.jwt.claims = '{"sub":"22222222-2222-4222-8222-222222222222","role":"authenticated"}';
select is((select count(user_id)::integer from public.subscriptions), 0, 'User B cannot read User A billing row');
select ok(not has_table_privilege('authenticated', 'public.entitlements', 'UPDATE'),
  'browser cannot write arbitrary entitlement flags');

select * from finish();
rollback;
