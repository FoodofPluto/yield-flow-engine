-- FuruFlow Prompt 8 production billing lifecycle.
-- Prompt 2's manual Pro grant remains independent from subscription-derived Pro.

alter table public.entitlements
    add column if not exists subscription_pro_active boolean not null default false;

-- Prompt 2 used pro_active for Stripe fulfillment. Preserve any existing Stripe
-- access while moving it to the dedicated subscription-derived component.
update public.entitlements
set subscription_pro_active = pro_active,
    pro_active = false
where source = 'stripe' and pro_active;

alter table public.subscriptions
    add column if not exists last_provider_event_created bigint,
    add column if not exists last_provider_event_id text;

create unique index if not exists subscriptions_stripe_customer_unique_idx
    on public.subscriptions (provider_customer_id)
    where provider = 'stripe' and provider_customer_id is not null;

create index if not exists subscriptions_user_status_idx
    on public.subscriptions (user_id, status, updated_at desc);

-- Authenticated clients receive only the safe billing summary used by Account
-- & Billing. Provider identifiers remain service-role-only.
revoke select on table public.subscriptions from authenticated;
grant select (user_id, provider, status, current_period_end, cancel_at_period_end, created_at, updated_at)
    on table public.subscriptions to authenticated;

create or replace function public.service_set_stripe_customer(
    target_user_id uuid,
    customer_id text
) returns boolean language plpgsql security definer set search_path = '' as $$
declare existing_customer text; existing_owner uuid;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    if customer_id is null or customer_id !~ '^cus_[A-Za-z0-9]+$' or char_length(customer_id) > 255 then
      raise exception 'invalid Stripe customer';
    end if;
    if not exists(
      select 1 from auth.users where id = target_user_id
        and email_confirmed_at is not null and deleted_at is null and not coalesce(is_anonymous, false)
    ) then raise exception 'verified active user required'; end if;
    if exists(select 1 from public.entitlements where user_id = target_user_id and demo_expires_at > now()) then
      raise exception 'billing changes are forbidden for demo users';
    end if;
    select user_id into existing_owner from public.subscriptions
      where provider = 'stripe' and provider_customer_id = customer_id;
    if existing_owner is not null and existing_owner <> target_user_id then
      raise exception 'Stripe customer is already mapped';
    end if;
    select provider_customer_id into existing_customer from public.subscriptions
      where provider = 'stripe' and user_id = target_user_id for update;
    if existing_customer is not null and existing_customer <> customer_id then
      raise exception 'account already has a different Stripe customer';
    end if;
    insert into public.subscriptions(user_id, provider, provider_customer_id, status)
      values(target_user_id, 'stripe', customer_id, 'inactive')
    on conflict(user_id, provider) do update
      set provider_customer_id = excluded.provider_customer_id
      where public.subscriptions.provider_customer_id is null
         or public.subscriptions.provider_customer_id = excluded.provider_customer_id;
    return existing_customer is null;
end;
$$;

-- Replace Prompt 2's fulfillment RPC with a provider-event-ordered version.
drop function if exists public.service_apply_stripe_subscription(uuid, text, text, text, text, timestamptz, boolean);

create or replace function public.service_apply_stripe_subscription(
    target_user_id uuid default null,
    customer_id text default null,
    subscription_id text default null,
    subscription_status text default 'inactive',
    checkout_session_id text default null,
    period_end timestamptz default null,
    cancels_at_period_end boolean default false,
    provider_event_created bigint default null,
    provider_event_id text default null
) returns uuid language plpgsql security definer set search_path = '' as $$
declare
    resolved_user_id uuid;
    customer_owner uuid;
    subscription_owner uuid;
    prior_event_created bigint;
    prior_event_id text;
    was_active boolean;
    now_active boolean;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    if provider_event_created is null or provider_event_created <= 0
       or provider_event_id is null or char_length(provider_event_id) > 255 then
      raise exception 'valid provider event ordering is required';
    end if;
    if subscription_status not in ('inactive', 'incomplete', 'incomplete_expired', 'trialing', 'active',
      'past_due', 'canceled', 'unpaid', 'paused') then raise exception 'unsupported subscription status'; end if;
    if customer_id is not null and (customer_id !~ '^cus_[A-Za-z0-9]+$' or char_length(customer_id) > 255) then
      raise exception 'invalid Stripe customer';
    end if;
    if subscription_id is not null and (subscription_id !~ '^sub_[A-Za-z0-9]+$' or char_length(subscription_id) > 255) then
      raise exception 'invalid Stripe subscription';
    end if;

    if subscription_id is not null then
      select user_id into subscription_owner from public.subscriptions
        where provider = 'stripe' and provider_subscription_id = subscription_id;
    end if;
    if customer_id is not null then
      select user_id into customer_owner from public.subscriptions
        where provider = 'stripe' and provider_customer_id = customer_id;
    end if;
    if subscription_owner is not null and customer_owner is not null and subscription_owner <> customer_owner then
      raise exception 'conflicting Stripe ownership mapping';
    end if;
    resolved_user_id := coalesce(subscription_owner, customer_owner);
    if resolved_user_id is null then raise exception 'verified user mapping required'; end if;
    if target_user_id is not null and target_user_id <> resolved_user_id then
      raise exception 'provider event user mapping mismatch';
    end if;
    if not exists(
      select 1 from auth.users where id = resolved_user_id
        and email_confirmed_at is not null and deleted_at is null and not coalesce(is_anonymous, false)
    ) then raise exception 'verified active user required'; end if;
    if exists(select 1 from public.entitlements where user_id = resolved_user_id and demo_expires_at > now()) then
      raise exception 'billing changes are forbidden for demo users';
    end if;

    insert into public.entitlements(user_id) values(resolved_user_id) on conflict(user_id) do nothing;
    select last_provider_event_created, last_provider_event_id
      into prior_event_created, prior_event_id
      from public.subscriptions where user_id = resolved_user_id and provider = 'stripe' for update;

    -- Comparing (created, id) makes equal-second events deterministic regardless
    -- of delivery order; strictly older events can never overwrite newer state.
    if prior_event_created is not null and
       (provider_event_created, provider_event_id) <= (prior_event_created, coalesce(prior_event_id, '')) then
      return resolved_user_id;
    end if;

    select subscription_pro_active into was_active from public.entitlements where user_id = resolved_user_id;
    now_active := subscription_status = 'active';
    insert into public.subscriptions(user_id, provider, provider_customer_id, provider_subscription_id,
      latest_checkout_session_id, status, current_period_end, cancel_at_period_end,
      last_provider_event_created, last_provider_event_id)
    values(resolved_user_id, 'stripe', customer_id, subscription_id, checkout_session_id, subscription_status,
      period_end, coalesce(cancels_at_period_end, false), provider_event_created, provider_event_id)
    on conflict(user_id, provider) do update set
      provider_customer_id = coalesce(excluded.provider_customer_id, public.subscriptions.provider_customer_id),
      provider_subscription_id = coalesce(excluded.provider_subscription_id, public.subscriptions.provider_subscription_id),
      latest_checkout_session_id = coalesce(excluded.latest_checkout_session_id, public.subscriptions.latest_checkout_session_id),
      status = excluded.status,
      current_period_end = excluded.current_period_end,
      cancel_at_period_end = excluded.cancel_at_period_end,
      last_provider_event_created = excluded.last_provider_event_created,
      last_provider_event_id = excluded.last_provider_event_id;
    update public.entitlements set subscription_pro_active = now_active where user_id = resolved_user_id;
    if was_active is distinct from now_active then
      insert into public.admin_audit(actor_user_id, target_user_id, action, reason, metadata)
      values(null, resolved_user_id, case when now_active then 'grant_subscription_pro' else 'revoke_subscription_pro' end,
        'stripe_subscription_sync', jsonb_build_object('source', 'stripe', 'status', subscription_status));
    end if;
    return resolved_user_id;
end;
$$;

create or replace function public.service_reconcile_subscription_entitlement(target_user_id uuid)
returns boolean language plpgsql security definer set search_path = '' as $$
declare expected boolean; current_value boolean;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    select coalesce(s.status = 'active', false), e.subscription_pro_active
      into expected, current_value
      from public.entitlements e
      left join public.subscriptions s on s.user_id = e.user_id and s.provider = 'stripe'
      where e.user_id = target_user_id for update of e;
    if current_value is null then raise exception 'target entitlement record is unavailable'; end if;
    if current_value is distinct from expected then
      update public.entitlements set subscription_pro_active = expected where user_id = target_user_id;
      insert into public.admin_audit(actor_user_id, target_user_id, action, reason, metadata)
      values(null, target_user_id, 'reconcile_subscription_pro', 'operator_reconciliation',
        jsonb_build_object('source', 'stored_subscription', 'enabled', expected));
      return true;
    end if;
    return false;
end;
$$;

revoke all on function public.service_set_stripe_customer(uuid, text) from public, anon, authenticated;
revoke all on function public.service_apply_stripe_subscription(uuid, text, text, text, text, timestamptz, boolean, bigint, text)
    from public, anon, authenticated;
revoke all on function public.service_reconcile_subscription_entitlement(uuid) from public, anon, authenticated;
grant execute on function public.service_set_stripe_customer(uuid, text) to service_role;
grant execute on function public.service_apply_stripe_subscription(uuid, text, text, text, text, timestamptz, boolean, bigint, text)
    to service_role;
grant execute on function public.service_reconcile_subscription_entitlement(uuid) to service_role;
