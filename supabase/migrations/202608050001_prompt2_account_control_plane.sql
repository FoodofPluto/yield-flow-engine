-- FuruFlow Prompt 2 account and entitlement control plane.
-- Apply with `supabase db push` after linking the intended project.

create schema if not exists extensions;
create schema if not exists private;
create extension if not exists pgcrypto with schema extensions;
create extension if not exists pg_cron;

create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    display_name text check (display_name is null or char_length(display_name) between 1 and 80),
    timezone text not null default 'UTC' check (char_length(timezone) between 1 and 64),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.entitlements (
    user_id uuid primary key references auth.users(id) on delete cascade,
    is_admin boolean not null default false,
    pro_active boolean not null default false,
    lifetime_access boolean not null default false,
    demo_expires_at timestamptz,
    demo_environment text check (demo_environment is null or demo_environment in ('development', 'staging', 'test')),
    source text not null default 'system' check (source in ('system', 'admin_cli', 'stripe', 'legacy_migration')),
    updated_at timestamptz not null default now(),
    constraint demo_fields_together check (
        (demo_expires_at is null and demo_environment is null)
        or (demo_expires_at is not null and demo_environment is not null)
    )
);

create table if not exists public.subscriptions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    provider text not null default 'stripe' check (provider = 'stripe'),
    provider_customer_id text,
    provider_subscription_id text unique,
    latest_checkout_session_id text,
    status text not null default 'inactive',
    current_period_end timestamptz,
    cancel_at_period_end boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, provider)
);

create table if not exists public.admin_audit (
    id bigint generated always as identity primary key,
    actor_user_id uuid references auth.users(id) on delete set null,
    target_user_id uuid references auth.users(id) on delete set null,
    action text not null check (char_length(action) between 1 and 64),
    reason text check (reason is null or char_length(reason) <= 256),
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists public.webhook_events (
    provider text not null default 'stripe',
    event_id text not null,
    event_type text,
    state text not null default 'processing' check (state in ('processing', 'processed', 'failed')),
    attempts integer not null default 1 check (attempts > 0),
    last_error_code text,
    received_at timestamptz not null default now(),
    processed_at timestamptz,
    primary key (provider, event_id)
);

create table if not exists public.account_sessions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    session_hash bytea not null unique,
    created_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    expires_at timestamptz not null,
    revoked_at timestamptz,
    revoke_reason text
);

create table if not exists public.browser_sessions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    opaque_hash text not null unique check (opaque_hash ~ '^[0-9a-f]{64}$'),
    access_token_ciphertext text not null,
    refresh_token_ciphertext text,
    created_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    expires_at timestamptz not null,
    revoked_at timestamptz
);

create table if not exists public.browser_session_tickets (
    ticket_hash text primary key check (ticket_hash ~ '^[0-9a-f]{64}$'),
    browser_session_id uuid not null references public.browser_sessions(id) on delete cascade,
    opaque_ciphertext text not null,
    expires_at timestamptz not null,
    consumed_at timestamptz
);

create index if not exists account_sessions_user_active_idx
    on public.account_sessions (user_id, last_seen_at desc) where revoked_at is null;
create index if not exists admin_audit_target_created_idx
    on public.admin_audit (target_user_id, created_at desc);

create or replace function public.touch_updated_at()
returns trigger language plpgsql set search_path = '' as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists profiles_touch_updated_at on public.profiles;
create trigger profiles_touch_updated_at before update on public.profiles
for each row execute function public.touch_updated_at();
drop trigger if exists entitlements_touch_updated_at on public.entitlements;
create trigger entitlements_touch_updated_at before update on public.entitlements
for each row execute function public.touch_updated_at();
drop trigger if exists subscriptions_touch_updated_at on public.subscriptions;
create trigger subscriptions_touch_updated_at before update on public.subscriptions
for each row execute function public.touch_updated_at();

create or replace function public.handle_new_auth_user()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
    insert into public.profiles (id) values (new.id) on conflict (id) do nothing;
    insert into public.entitlements (user_id) values (new.id) on conflict (user_id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created_furuflow on auth.users;
create trigger on_auth_user_created_furuflow
after insert on auth.users for each row execute function public.handle_new_auth_user();

-- Reconcile verified users created before this migration without granting privilege.
insert into public.profiles (id)
select id from auth.users where email_confirmed_at is not null on conflict (id) do nothing;
insert into public.entitlements (user_id)
select id from auth.users where email_confirmed_at is not null on conflict (user_id) do nothing;

alter table public.profiles enable row level security;
alter table public.entitlements enable row level security;
alter table public.subscriptions enable row level security;
alter table public.admin_audit enable row level security;
alter table public.webhook_events enable row level security;
alter table public.account_sessions enable row level security;
alter table public.browser_sessions enable row level security;
alter table public.browser_session_tickets enable row level security;

revoke all on table public.profiles, public.entitlements, public.subscriptions,
    public.admin_audit, public.webhook_events, public.account_sessions from public, anon, authenticated;
revoke all on table public.browser_sessions, public.browser_session_tickets from public, anon, authenticated;
grant all on table public.profiles, public.entitlements, public.subscriptions,
    public.admin_audit, public.webhook_events, public.account_sessions,
    public.browser_sessions, public.browser_session_tickets to service_role;
grant select on public.profiles, public.entitlements, public.subscriptions to authenticated;
grant update (display_name, timezone) on public.profiles to authenticated;

drop policy if exists profiles_select_self on public.profiles;
create policy profiles_select_self on public.profiles for select to authenticated
using ((select auth.uid()) = id);
drop policy if exists profiles_update_self on public.profiles;
create policy profiles_update_self on public.profiles for update to authenticated
using ((select auth.uid()) = id) with check ((select auth.uid()) = id);
drop policy if exists entitlements_select_self on public.entitlements;
create policy entitlements_select_self on public.entitlements for select to authenticated
using ((select auth.uid()) = user_id);
drop policy if exists subscriptions_select_self on public.subscriptions;
create policy subscriptions_select_self on public.subscriptions for select to authenticated
using ((select auth.uid()) = user_id);

create or replace function public.claim_account_session(raw_session_id text, ttl_seconds integer default 86400)
returns uuid language plpgsql security definer set search_path = '' as $$
declare new_id uuid;
begin
    if auth.uid() is null or raw_session_id is null or char_length(raw_session_id) < 32 then
        raise exception 'invalid session claim';
    end if;
    if ttl_seconds < 300 or ttl_seconds > 604800 then
        raise exception 'invalid session ttl';
    end if;
    update public.account_sessions set revoked_at = now(), revoke_reason = 'replaced'
      where user_id = auth.uid() and revoked_at is null;
    insert into public.account_sessions (user_id, session_hash, expires_at)
      values (auth.uid(), extensions.digest(raw_session_id, 'sha256'), now() + make_interval(secs => ttl_seconds))
      returning id into new_id;
    return new_id;
end;
$$;

create or replace function public.touch_account_session(raw_session_id text)
returns boolean language plpgsql security definer set search_path = '' as $$
declare touched integer;
begin
    if auth.uid() is null then return false; end if;
    update public.account_sessions set last_seen_at = now()
      where user_id = auth.uid()
        and session_hash = extensions.digest(raw_session_id, 'sha256')
        and revoked_at is null and expires_at > now();
    get diagnostics touched = row_count;
    return touched = 1;
end;
$$;

create or replace function public.revoke_account_session(raw_session_id text)
returns boolean language plpgsql security definer set search_path = '' as $$
declare touched integer;
begin
    if auth.uid() is null then return false; end if;
    update public.account_sessions set revoked_at = now(), revoke_reason = 'logout'
      where user_id = auth.uid() and session_hash = extensions.digest(raw_session_id, 'sha256') and revoked_at is null;
    get diagnostics touched = row_count;
    return touched = 1;
end;
$$;

revoke all on function public.claim_account_session(text, integer) from public;
revoke all on function public.touch_account_session(text) from public;
revoke all on function public.revoke_account_session(text) from public;
grant execute on function public.claim_account_session(text, integer) to authenticated;
grant execute on function public.touch_account_session(text) to authenticated;
grant execute on function public.revoke_account_session(text) to authenticated;

create or replace function public.service_set_entitlement(
    target_user_id uuid,
    entitlement_name text,
    enabled boolean,
    actor_user_id uuid,
    change_reason text default null,
    demo_expiry timestamptz default null,
    target_environment text default null,
    change_source text default 'admin_cli'
) returns boolean language plpgsql security definer set search_path = '' as $$
declare current_value boolean; changed boolean := false; verified boolean;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    if not exists(
      select 1 from auth.users u join public.entitlements e on e.user_id = u.id
      where u.id = actor_user_id and u.email_confirmed_at is not null and u.deleted_at is null and e.is_admin
    ) then raise exception 'verified administrator actor required'; end if;
    select email_confirmed_at is not null into verified from auth.users where id = target_user_id and deleted_at is null;
    if verified is distinct from true then raise exception 'target must be a verified active Supabase user'; end if;
    insert into public.profiles (id) values (target_user_id) on conflict (id) do nothing;
    insert into public.entitlements (user_id) values (target_user_id) on conflict (user_id) do nothing;
    if entitlement_name in ('admin', 'pro', 'lifetime') and enabled and exists(
      select 1 from public.entitlements where user_id = target_user_id and demo_expires_at > now()
    ) then raise exception 'demo users cannot receive privileged or billing entitlements'; end if;
    if entitlement_name = 'admin' then
        select is_admin into current_value from public.entitlements where user_id = target_user_id;
        changed := current_value is distinct from enabled;
        update public.entitlements set is_admin = enabled, source = change_source where user_id = target_user_id;
    elsif entitlement_name = 'pro' then
        select pro_active into current_value from public.entitlements where user_id = target_user_id;
        changed := current_value is distinct from enabled;
        update public.entitlements set pro_active = enabled, source = change_source where user_id = target_user_id;
    elsif entitlement_name = 'lifetime' then
        select lifetime_access into current_value from public.entitlements where user_id = target_user_id;
        changed := current_value is distinct from enabled;
        update public.entitlements set lifetime_access = enabled, source = change_source where user_id = target_user_id;
    elsif entitlement_name = 'demo' then
        if enabled and (demo_expiry is null or demo_expiry <= now() or demo_expiry > now() + interval '24 hours'
            or target_environment not in ('development', 'staging', 'test')) then
            raise exception 'demo must be non-production and expire within 24 hours';
        end if;
        if enabled and exists(
          select 1 from public.entitlements e where e.user_id = target_user_id
            and (e.is_admin or e.pro_active or e.lifetime_access)
        ) then raise exception 'demo requires an unprivileged free account'; end if;
        if enabled and exists(
          select 1 from public.subscriptions s where s.user_id = target_user_id and s.status in ('trialing', 'active', 'past_due')
        ) then raise exception 'demo cannot alter or coexist with active billing'; end if;
        select demo_expires_at is not null and demo_expires_at > now() into current_value
          from public.entitlements where user_id = target_user_id;
        changed := current_value is distinct from enabled or (enabled and demo_expires_at is distinct from demo_expiry);
        update public.entitlements set demo_expires_at = case when enabled then demo_expiry end,
            demo_environment = case when enabled then target_environment end, source = change_source
          where user_id = target_user_id;
    else raise exception 'unknown entitlement';
    end if;
    if changed then
        insert into public.admin_audit(actor_user_id, target_user_id, action, reason, metadata)
        values (actor_user_id, target_user_id, case when enabled then 'grant_' else 'revoke_' end || entitlement_name,
            change_reason, jsonb_build_object('source', change_source));
    end if;
    return changed;
end;
$$;

create or replace function public.bootstrap_first_admin(target_user_id uuid, change_reason text default 'first_admin_bootstrap')
returns boolean language plpgsql security definer set search_path = '' as $$
declare existing_admin uuid; target_verified boolean;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    select email_confirmed_at is not null into target_verified from auth.users where id = target_user_id and deleted_at is null;
    if target_verified is distinct from true then raise exception 'target must be a verified active Supabase user'; end if;
    select user_id into existing_admin from public.entitlements where is_admin order by updated_at limit 1;
    if existing_admin is not null and existing_admin <> target_user_id then raise exception 'an administrator already exists'; end if;
    insert into public.profiles(id) values(target_user_id) on conflict(id) do nothing;
    insert into public.entitlements(user_id, is_admin, source) values(target_user_id, true, 'admin_cli')
      on conflict(user_id) do update set is_admin = true, source = 'admin_cli';
    if existing_admin is null then
      insert into public.admin_audit(actor_user_id, target_user_id, action, reason)
      values(target_user_id, target_user_id, 'bootstrap_admin', change_reason);
      return true;
    end if;
    return false;
end;
$$;

create or replace function private.cleanup_expired_demo_entitlements()
returns integer language plpgsql security definer set search_path = '' as $$
declare cleaned integer;
begin
    with expired as (
      update public.entitlements set demo_expires_at = null, demo_environment = null, source = 'system'
      where demo_expires_at is not null and demo_expires_at <= now() returning user_id
    ), revoke_accounts as (
      update public.account_sessions set revoked_at = now(), revoke_reason = 'demo_expired'
      where revoked_at is null and user_id in (select user_id from expired) returning id
    ), revoke_browsers as (
      update public.browser_sessions set revoked_at = now()
      where revoked_at is null and user_id in (select user_id from expired) returning id
    ) select count(*) into cleaned from expired;
    delete from public.browser_session_tickets where consumed_at is not null or expires_at <= now();
    delete from public.browser_sessions where expires_at <= now() and revoked_at is not null;
    return cleaned;
end;
$$;

revoke all on function private.cleanup_expired_demo_entitlements() from public, anon, authenticated, service_role;

create or replace function public.cleanup_expired_demo_entitlements()
returns integer language plpgsql security definer set search_path = '' as $$
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    return private.cleanup_expired_demo_entitlements();
end;
$$;

select cron.unschedule(jobid) from cron.job where jobname = 'furuflow-demo-cleanup';
select cron.schedule(
  'furuflow-demo-cleanup',
  '*/5 * * * *',
  'select private.cleanup_expired_demo_entitlements()'
);

revoke all on function public.service_set_entitlement(uuid, text, boolean, uuid, text, timestamptz, text, text) from public;
revoke all on function public.bootstrap_first_admin(uuid, text) from public;
revoke all on function public.cleanup_expired_demo_entitlements() from public;
grant execute on function public.service_set_entitlement(uuid, text, boolean, uuid, text, timestamptz, text, text) to service_role;
grant execute on function public.bootstrap_first_admin(uuid, text) to service_role;
grant execute on function public.cleanup_expired_demo_entitlements() to service_role;

create or replace function public.service_begin_webhook_event(event_provider text, incoming_event_id text, incoming_type text)
returns boolean language plpgsql security definer set search_path = '' as $$
declare prior_state text; prior_received_at timestamptz; inserted_id text;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    insert into public.webhook_events(provider, event_id, event_type)
      values(event_provider, incoming_event_id, incoming_type)
      on conflict(provider, event_id) do nothing returning event_id into inserted_id;
    if inserted_id is not null then return true; end if;
    select state, received_at into prior_state, prior_received_at from public.webhook_events
      where provider = event_provider and event_id = incoming_event_id for update;
    if prior_state = 'processed' or (prior_state = 'processing' and prior_received_at > now() - interval '5 minutes')
      then return false; end if;
    update public.webhook_events set state = 'processing', attempts = attempts + 1,
      event_type = incoming_type, last_error_code = null, received_at = now()
      where provider = event_provider and event_id = incoming_event_id;
    return true;
end;
$$;

create or replace function public.service_finish_webhook_event(
    event_provider text, incoming_event_id text, succeeded boolean, error_code text default null
) returns void language plpgsql security definer set search_path = '' as $$
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    update public.webhook_events set state = case when succeeded then 'processed' else 'failed' end,
      processed_at = case when succeeded then now() else null end,
      last_error_code = case when succeeded then null else left(error_code, 64) end
      where provider = event_provider and event_id = incoming_event_id;
end;
$$;

create or replace function public.service_apply_stripe_subscription(
    target_user_id uuid default null,
    customer_id text default null,
    subscription_id text default null,
    subscription_status text default 'inactive',
    checkout_session_id text default null,
    period_end timestamptz default null,
    cancels_at_period_end boolean default false
) returns uuid language plpgsql security definer set search_path = '' as $$
declare resolved_user_id uuid; was_active boolean; now_active boolean;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    resolved_user_id := target_user_id;
    if resolved_user_id is null and subscription_id is not null then
      select user_id into resolved_user_id from public.subscriptions where provider_subscription_id = subscription_id;
    end if;
    if resolved_user_id is null and customer_id is not null then
      select user_id into resolved_user_id from public.subscriptions where provider_customer_id = customer_id;
    end if;
    if resolved_user_id is null then raise exception 'verified user mapping required'; end if;
    if not exists(select 1 from auth.users where id = resolved_user_id and email_confirmed_at is not null and deleted_at is null)
      then raise exception 'verified active user required'; end if;
    if exists(select 1 from public.entitlements where user_id = resolved_user_id and demo_expires_at > now())
      then raise exception 'billing changes are forbidden for demo users'; end if;
    insert into public.entitlements(user_id) values(resolved_user_id) on conflict(user_id) do nothing;
    select pro_active into was_active from public.entitlements where user_id = resolved_user_id;
    now_active := subscription_status in ('trialing', 'active', 'past_due');
    insert into public.subscriptions(user_id, provider_customer_id, provider_subscription_id,
      latest_checkout_session_id, status, current_period_end, cancel_at_period_end)
    values(resolved_user_id, customer_id, subscription_id, checkout_session_id, subscription_status,
      period_end, coalesce(cancels_at_period_end, false))
    on conflict(user_id, provider) do update set
      provider_customer_id = coalesce(excluded.provider_customer_id, public.subscriptions.provider_customer_id),
      provider_subscription_id = coalesce(excluded.provider_subscription_id, public.subscriptions.provider_subscription_id),
      latest_checkout_session_id = coalesce(excluded.latest_checkout_session_id, public.subscriptions.latest_checkout_session_id),
      status = excluded.status, current_period_end = excluded.current_period_end,
      cancel_at_period_end = excluded.cancel_at_period_end;
    update public.entitlements set pro_active = now_active, source = 'stripe' where user_id = resolved_user_id;
    if was_active is distinct from now_active then
      insert into public.admin_audit(actor_user_id, target_user_id, action, reason, metadata)
      values(null, resolved_user_id, case when now_active then 'grant_pro' else 'revoke_pro' end,
        'stripe_subscription_sync', jsonb_build_object('source', 'stripe', 'status', subscription_status));
    end if;
    return resolved_user_id;
end;
$$;

revoke all on function public.service_begin_webhook_event(text, text, text) from public;
revoke all on function public.service_finish_webhook_event(text, text, boolean, text) from public;
revoke all on function public.service_apply_stripe_subscription(uuid, text, text, text, text, timestamptz, boolean) from public;
grant execute on function public.service_begin_webhook_event(text, text, text) to service_role;
grant execute on function public.service_finish_webhook_event(text, text, boolean, text) to service_role;
grant execute on function public.service_apply_stripe_subscription(uuid, text, text, text, text, timestamptz, boolean) to service_role;
