-- FuruFlow Prompt 5 durable Telegram automation, retention, and monitoring.
-- Apply after 202608050001_prompt2_account_control_plane.sql.

create table if not exists public.automation_runs (
    id uuid primary key default gen_random_uuid(),
    invocation_key text not null unique check (char_length(invocation_key) between 8 and 200),
    worker_instance text not null check (char_length(worker_instance) between 1 and 160),
    scheduled_for timestamptz not null,
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    scan_outcome text check (scan_outcome is null or scan_outcome in
      ('succeeded', 'zero_signals', 'provider_failed', 'infrastructure_failed')),
    signal_count integer not null default 0 check (signal_count >= 0),
    safe_error_code text check (safe_error_code is null or char_length(safe_error_code) <= 64),
    claim_count integer not null default 1 check (claim_count > 0),
    created_at timestamptz not null default now()
);

create index if not exists automation_runs_scheduled_idx
    on public.automation_runs (scheduled_for desc);
create index if not exists automation_runs_outcome_idx
    on public.automation_runs (scan_outcome, finished_at desc);

create table if not exists public.automation_heartbeats (
    worker_name text primary key check (char_length(worker_name) between 1 and 80),
    worker_instance text not null check (char_length(worker_instance) between 1 and 160),
    state text not null check (state in ('starting', 'scanning', 'delivering', 'idle', 'degraded', 'disabled')),
    active_run_id uuid references public.automation_runs(id) on delete set null,
    heartbeat_at timestamptz not null default now()
);

create table if not exists public.notification_rules (
    id uuid primary key default gen_random_uuid(),
    user_id uuid default auth.uid() references auth.users(id) on delete cascade,
    rule_key text not null default gen_random_uuid()::text check (char_length(rule_key) between 1 and 100),
    rule_kind text not null default 'market' check (rule_kind in ('market', 'test')),
    channel text not null default 'telegram' check (channel = 'telegram'),
    telegram_chat_id text not null check (char_length(telegram_chat_id) between 1 and 128),
    enabled boolean not null default true,
    minimum_strength integer not null default 0 check (minimum_strength between 0 and 100),
    signal_tier text not null default 'all' check (signal_tier in ('all', 'free', 'pro')),
    delivery_mode text not null default 'immediate' check (delivery_mode in ('immediate', 'digest')),
    quiet_hours_start time,
    quiet_hours_end time,
    timezone text not null default 'UTC' check (char_length(timezone) between 1 and 64),
    cooldown_minutes integer not null default 1440 check (cooldown_minutes between 1 and 43200),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, rule_key),
    check ((quiet_hours_start is null) = (quiet_hours_end is null))
);

create unique index if not exists notification_rules_system_key_idx
    on public.notification_rules (rule_key) where user_id is null;
create index if not exists notification_rules_user_idx
    on public.notification_rules (user_id, enabled);

drop trigger if exists notification_rules_touch_updated_at on public.notification_rules;
create trigger notification_rules_touch_updated_at before update on public.notification_rules
for each row execute function public.touch_updated_at();

create table if not exists public.signal_snapshots (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references public.automation_runs(id) on delete cascade,
    signal_fingerprint text not null check (char_length(signal_fingerprint) = 64),
    payload jsonb not null check (jsonb_typeof(payload) = 'object'),
    created_at timestamptz not null default now(),
    unique (run_id, signal_fingerprint)
);

create table if not exists public.notification_deliveries (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references public.automation_runs(id) on delete restrict,
    rule_id uuid not null references public.notification_rules(id) on delete cascade,
    signal_snapshot_id uuid not null references public.signal_snapshots(id) on delete restrict,
    logical_delivery_key text not null unique check (char_length(logical_delivery_key) = 64),
    delivery_kind text not null default 'signal' check (delivery_kind in ('signal', 'digest', 'test')),
    message_text text not null check (char_length(message_text) between 1 and 4096),
    state text not null default 'queued' check (state in
      ('queued', 'sending', 'retry', 'delivered', 'dead_letter', 'cancelled')),
    attempt_count integer not null default 0 check (attempt_count between 0 and 3),
    next_attempt_at timestamptz not null default now(),
    claimed_at timestamptz,
    claimed_by text,
    delivered_at timestamptz,
    provider_message_id text check (provider_message_id is null or char_length(provider_message_id) <= 128),
    safe_error_code text check (safe_error_code is null or char_length(safe_error_code) <= 64),
    ambiguous_outcome boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists notification_deliveries_claim_idx
    on public.notification_deliveries (state, next_attempt_at, created_at);
create index if not exists notification_deliveries_rule_history_idx
    on public.notification_deliveries (rule_id, created_at desc);

drop trigger if exists notification_deliveries_touch_updated_at on public.notification_deliveries;
create trigger notification_deliveries_touch_updated_at before update on public.notification_deliveries
for each row execute function public.touch_updated_at();

create table if not exists public.notification_delivery_attempts (
    id uuid primary key default gen_random_uuid(),
    delivery_id uuid not null references public.notification_deliveries(id) on delete cascade,
    attempt_number integer not null check (attempt_number between 1 and 3),
    worker_instance text not null check (char_length(worker_instance) between 1 and 160),
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    outcome text check (outcome is null or outcome in ('delivered', 'retry', 'dead_letter')),
    safe_error_code text check (safe_error_code is null or char_length(safe_error_code) <= 64),
    ambiguous_outcome boolean not null default false,
    unique (delivery_id, attempt_number)
);

create table if not exists public.notification_test_requests (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    rule_id uuid not null references public.notification_rules(id) on delete cascade,
    state text not null default 'pending' check (state in ('pending', 'processing', 'enqueued', 'failed')),
    requested_at timestamptz not null default now(),
    processing_at timestamptz,
    claimed_by text,
    processed_at timestamptz,
    safe_error_code text check (safe_error_code is null or char_length(safe_error_code) <= 64)
);

create index if not exists notification_test_requests_pending_idx
    on public.notification_test_requests (state, requested_at);

alter table public.automation_runs enable row level security;
alter table public.automation_heartbeats enable row level security;
alter table public.notification_rules enable row level security;
alter table public.signal_snapshots enable row level security;
alter table public.notification_deliveries enable row level security;
alter table public.notification_delivery_attempts enable row level security;
alter table public.notification_test_requests enable row level security;

revoke all on table public.automation_runs, public.automation_heartbeats,
    public.notification_rules, public.signal_snapshots, public.notification_deliveries,
    public.notification_delivery_attempts, public.notification_test_requests
    from public, anon, authenticated;
grant all on table public.automation_runs, public.automation_heartbeats,
    public.notification_rules, public.signal_snapshots, public.notification_deliveries,
    public.notification_delivery_attempts, public.notification_test_requests to service_role;
grant select, insert, update on public.notification_rules to authenticated;
grant select on public.notification_deliveries, public.notification_delivery_attempts to authenticated;
grant select on public.notification_test_requests to authenticated;

drop policy if exists notification_rules_select_self on public.notification_rules;
create policy notification_rules_select_self on public.notification_rules for select to authenticated
using ((select auth.uid()) = user_id);
drop policy if exists notification_rules_insert_self on public.notification_rules;
create policy notification_rules_insert_self on public.notification_rules for insert to authenticated
with check ((select auth.uid()) = user_id);
drop policy if exists notification_rules_update_self on public.notification_rules;
create policy notification_rules_update_self on public.notification_rules for update to authenticated
using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
drop policy if exists notification_deliveries_select_self on public.notification_deliveries;
create policy notification_deliveries_select_self on public.notification_deliveries for select to authenticated
using (exists (
  select 1 from public.notification_rules r where r.id = rule_id and r.user_id = (select auth.uid())
));
drop policy if exists notification_delivery_attempts_select_self on public.notification_delivery_attempts;
create policy notification_delivery_attempts_select_self on public.notification_delivery_attempts for select to authenticated
using (exists (
  select 1 from public.notification_deliveries d
  join public.notification_rules r on r.id = d.rule_id
  where d.id = delivery_id and r.user_id = (select auth.uid())
));
drop policy if exists notification_test_requests_select_self on public.notification_test_requests;
create policy notification_test_requests_select_self on public.notification_test_requests for select to authenticated
using ((select auth.uid()) = user_id);

create or replace view public.notification_delivery_history
with (security_invoker = true) as
select d.id, d.rule_id, d.delivery_kind, d.state, d.attempt_count,
       d.next_attempt_at, d.delivered_at, d.safe_error_code, d.ambiguous_outcome, d.created_at
from public.notification_deliveries d;

revoke all on public.notification_delivery_history from public, anon;
grant select on public.notification_delivery_history to authenticated, service_role;

create or replace function public.service_begin_automation_run(
    logical_invocation_key text, worker_instance text, scheduled_time timestamptz
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare run_row public.automation_runs%rowtype; inserted_id uuid;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    insert into public.automation_runs(invocation_key, worker_instance, scheduled_for)
      values(logical_invocation_key, worker_instance, scheduled_time)
      on conflict(invocation_key) do nothing returning id into inserted_id;
    if inserted_id is not null then
      return jsonb_build_object('id', inserted_id, 'claimed', true);
    end if;
    select * into run_row from public.automation_runs where invocation_key = logical_invocation_key for update;
    if run_row.finished_at is not null or run_row.started_at > now() - interval '5 minutes' then
      return jsonb_build_object('id', run_row.id, 'claimed', false, 'outcome', run_row.scan_outcome);
    end if;
    update public.automation_runs set worker_instance = service_begin_automation_run.worker_instance,
      started_at = now(), claim_count = claim_count + 1, safe_error_code = null
      where id = run_row.id;
    return jsonb_build_object('id', run_row.id, 'claimed', true, 'recovered', true);
end;
$$;

create or replace function public.service_automation_heartbeat(
    active_run_id uuid, worker_instance text, worker_state text
) returns void language plpgsql security definer set search_path = '' as $$
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    insert into public.automation_heartbeats(worker_name, worker_instance, state, active_run_id)
      values('telegram', worker_instance, worker_state, active_run_id)
      on conflict(worker_name) do update set worker_instance = excluded.worker_instance,
        state = excluded.state, active_run_id = excluded.active_run_id, heartbeat_at = now();
end;
$$;

create or replace function public.service_finish_automation_scan(
    automation_run_id uuid, scan_outcome text, generated_signal_count integer, safe_error_code text default null
) returns void language plpgsql security definer set search_path = '' as $$
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    if scan_outcome not in ('succeeded', 'zero_signals', 'provider_failed', 'infrastructure_failed') then
      raise exception 'invalid scan outcome';
    end if;
    update public.automation_runs set scan_outcome = service_finish_automation_scan.scan_outcome,
      signal_count = greatest(generated_signal_count, 0),
      safe_error_code = left(service_finish_automation_scan.safe_error_code, 64), finished_at = now()
      where id = automation_run_id and finished_at is null;
end;
$$;

create or replace function public.service_list_notification_rules(target_environment text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare result jsonb;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    select coalesce(jsonb_agg(jsonb_build_object(
      'id', r.id, 'user_id', r.user_id, 'telegram_chat_id', r.telegram_chat_id,
      'enabled', r.enabled, 'minimum_strength', r.minimum_strength, 'signal_tier', r.signal_tier,
      'delivery_mode', r.delivery_mode, 'quiet_hours_start', r.quiet_hours_start,
      'quiet_hours_end', r.quiet_hours_end, 'timezone', r.timezone,
      'cooldown_minutes', r.cooldown_minutes,
      'entitled_to_pro', coalesce(e.is_admin or e.pro_active or e.lifetime_access, false),
      'demo_active', coalesce(e.demo_expires_at > now() and e.demo_environment = target_environment, false)
    ) order by r.created_at), '[]'::jsonb) into result
    from public.notification_rules r left join public.entitlements e on e.user_id = r.user_id
    where r.enabled and r.rule_kind = 'market';
    return result;
end;
$$;

create or replace function public.service_upsert_system_notification_rule(
    destination_chat_id text, rule_enabled boolean
) returns uuid language plpgsql security definer set search_path = '' as $$
declare result uuid;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    insert into public.notification_rules(user_id, rule_key, rule_kind, telegram_chat_id, enabled, minimum_strength,
      signal_tier, delivery_mode, timezone, cooldown_minutes)
    values(null, 'system-default', 'market', destination_chat_id, rule_enabled, 0, 'all', 'immediate', 'UTC', 1440)
    on conflict(rule_key) where user_id is null do update set telegram_chat_id = excluded.telegram_chat_id,
      enabled = excluded.enabled returning id into result;
    return result;
end;
$$;

create or replace function public.service_enqueue_staging_notification_test(
    destination_chat_id text, test_idempotency_key text, target_environment text
) returns boolean language plpgsql security definer set search_path = '' as $$
declare v_run_id uuid; v_rule_id uuid; v_snapshot_id uuid; v_inserted_id uuid;
declare fingerprint text; delivery_key text;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    if target_environment not in ('development', 'staging', 'test') then raise exception 'test delivery forbidden'; end if;
    if char_length(test_idempotency_key) < 8 or char_length(test_idempotency_key) > 100 then
      raise exception 'invalid test idempotency key';
    end if;
    insert into public.automation_runs(invocation_key, worker_instance, scheduled_for,
      finished_at, scan_outcome, signal_count)
    values('test:' || target_environment || ':' || test_idempotency_key, 'operator-test', now(),
      now(), 'zero_signals', 0)
    on conflict(invocation_key) do update set invocation_key = excluded.invocation_key returning id into v_run_id;
    insert into public.notification_rules(user_id, rule_key, rule_kind, telegram_chat_id, enabled,
      minimum_strength, signal_tier, delivery_mode, timezone, cooldown_minutes)
    values(null, 'controlled-staging-test', 'test', destination_chat_id, true, 0, 'all', 'immediate', 'UTC', 1)
    on conflict(rule_key) where user_id is null do update set telegram_chat_id = excluded.telegram_chat_id,
      enabled = true returning id into v_rule_id;
    fingerprint := encode(extensions.digest('test:' || test_idempotency_key, 'sha256'), 'hex');
    delivery_key := encode(extensions.digest('test-delivery:' || target_environment || ':' || test_idempotency_key,
      'sha256'), 'hex');
    insert into public.signal_snapshots(run_id, signal_fingerprint, payload)
    values(v_run_id, fingerprint, jsonb_build_object('kind', 'test', 'tier', 'free'))
    on conflict(run_id, signal_fingerprint) do update set payload = excluded.payload returning id into v_snapshot_id;
    insert into public.notification_deliveries(run_id, rule_id, signal_snapshot_id, logical_delivery_key,
      delivery_kind, message_text, next_attempt_at)
    values(v_run_id, v_rule_id, v_snapshot_id, delivery_key, 'test',
      'FuruFlow Telegram test: delivery configuration is working.', now())
    on conflict(logical_delivery_key) do nothing returning id into v_inserted_id;
    return v_inserted_id is not null;
end;
$$;

create or replace function public.service_enqueue_telegram_delivery(
    automation_run_id uuid, notification_rule_id uuid, stable_signal_fingerprint text,
    delivery_idempotency_key text, signal_payload jsonb, rendered_message text,
    not_before timestamptz, delivery_kind text default 'signal'
) returns boolean language plpgsql security definer set search_path = '' as $$
declare snapshot_id uuid; inserted_id uuid;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    if not exists(select 1 from public.automation_runs where id = automation_run_id) then raise exception 'run missing'; end if;
    if not exists(select 1 from public.notification_rules where id = notification_rule_id and enabled) then
      return false;
    end if;
    insert into public.signal_snapshots(run_id, signal_fingerprint, payload)
      values(automation_run_id, stable_signal_fingerprint, signal_payload)
      on conflict(run_id, signal_fingerprint) do update set payload = excluded.payload
      returning id into snapshot_id;
    insert into public.notification_deliveries(run_id, rule_id, signal_snapshot_id,
      logical_delivery_key, delivery_kind, message_text, next_attempt_at)
    values(automation_run_id, notification_rule_id, snapshot_id,
      delivery_idempotency_key, delivery_kind, rendered_message, not_before)
      on conflict(logical_delivery_key) do nothing returning id into inserted_id;
    return inserted_id is not null;
end;
$$;

create or replace function public.service_claim_telegram_delivery(worker_instance text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare candidate public.notification_deliveries%rowtype; result jsonb;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    select d.* into candidate from public.notification_deliveries d
    join public.notification_rules r on r.id = d.rule_id
    join public.signal_snapshots s on s.id = d.signal_snapshot_id
    left join public.entitlements e on e.user_id = r.user_id
    where d.state in ('queued', 'retry') and d.next_attempt_at <= now() and d.attempt_count < 3 and r.enabled
      and (r.user_id is null or not coalesce(e.demo_expires_at > now(), false))
      and (lower(coalesce(s.payload ->> 'tier', 'free')) <> 'pro' or r.user_id is null
        or coalesce(e.is_admin or e.pro_active or e.lifetime_access, false))
    order by d.next_attempt_at, d.created_at for update of d skip locked limit 1;
    if candidate.id is null then return null; end if;
    update public.notification_deliveries set state = 'sending', attempt_count = attempt_count + 1,
      claimed_at = now(), claimed_by = worker_instance, safe_error_code = null
      where id = candidate.id;
    insert into public.notification_delivery_attempts(delivery_id, attempt_number, worker_instance)
      values(candidate.id, candidate.attempt_count + 1, worker_instance);
    select jsonb_build_object('id', d.id, 'attempt_count', d.attempt_count,
      'telegram_chat_id', r.telegram_chat_id, 'message_text', d.message_text,
      'delivery_kind', d.delivery_kind) into result
      from public.notification_deliveries d join public.notification_rules r on r.id = d.rule_id
      where d.id = candidate.id;
    return result;
end;
$$;

create or replace function public.service_finish_telegram_delivery(
    claimed_delivery_id uuid, worker_instance text, delivered boolean,
    provider_message_id text default null, safe_error_code text default null,
    retryable boolean default false, ambiguous_outcome boolean default false,
    retry_time timestamptz default null
) returns text language plpgsql security definer set search_path = '' as $$
declare delivery public.notification_deliveries%rowtype; final_state text;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    select * into delivery from public.notification_deliveries where id = claimed_delivery_id for update;
    if delivery.id is null or delivery.state <> 'sending' or delivery.claimed_by <> worker_instance then
      raise exception 'delivery claim is not owned by worker';
    end if;
    if delivered then final_state := 'delivered';
    elsif ambiguous_outcome then final_state := 'dead_letter';
    elsif retryable and delivery.attempt_count < 3 and retry_time is not null then final_state := 'retry';
    else final_state := 'dead_letter';
    end if;
    update public.notification_deliveries set state = final_state,
      next_attempt_at = case when final_state = 'retry' then retry_time else next_attempt_at end,
      delivered_at = case when final_state = 'delivered' then now() else null end,
      provider_message_id = case when final_state = 'delivered'
        then left(service_finish_telegram_delivery.provider_message_id, 128) else null end,
      safe_error_code = case when final_state = 'delivered' then null
        when service_finish_telegram_delivery.ambiguous_outcome then 'ambiguous_delivery_outcome'
        else left(service_finish_telegram_delivery.safe_error_code, 64) end,
      ambiguous_outcome = service_finish_telegram_delivery.ambiguous_outcome,
      claimed_at = null, claimed_by = null where id = delivery.id;
    update public.notification_delivery_attempts set finished_at = now(), outcome = final_state,
      safe_error_code = case when final_state = 'delivered' then null
        when service_finish_telegram_delivery.ambiguous_outcome then 'ambiguous_delivery_outcome'
        else left(service_finish_telegram_delivery.safe_error_code, 64) end,
      ambiguous_outcome = service_finish_telegram_delivery.ambiguous_outcome
      where delivery_id = delivery.id and attempt_number = delivery.attempt_count;
    return final_state;
end;
$$;

create or replace function public.service_recover_abandoned_deliveries(stale_after_seconds integer default 300)
returns integer language plpgsql security definer set search_path = '' as $$
declare recovered integer;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    if stale_after_seconds < 60 or stale_after_seconds > 86400 then raise exception 'invalid stale interval'; end if;
    with abandoned as (
      update public.notification_deliveries set state = 'dead_letter', claimed_at = null, claimed_by = null,
        safe_error_code = 'abandoned_ambiguous_delivery', ambiguous_outcome = true
      where state = 'sending' and claimed_at < now() - make_interval(secs => stale_after_seconds)
      returning id, attempt_count
    ), attempts as (
      update public.notification_delivery_attempts a set finished_at = now(), outcome = 'dead_letter',
        safe_error_code = 'abandoned_ambiguous_delivery', ambiguous_outcome = true
      from abandoned x where a.delivery_id = x.id and a.attempt_number = x.attempt_count returning a.id
    ) select count(*) into recovered from abandoned;
    return recovered;
end;
$$;

create or replace function public.service_automation_health(stale_after_seconds integer default 900)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare result jsonb;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    select jsonb_build_object(
      'heartbeat_at', (select heartbeat_at from public.automation_heartbeats where worker_name = 'telegram'),
      'worker_state', (select state from public.automation_heartbeats where worker_name = 'telegram'),
      'stale', coalesce((select heartbeat_at < now() - make_interval(secs => stale_after_seconds)
        from public.automation_heartbeats where worker_name = 'telegram'), true),
      'last_run_at', (select started_at from public.automation_runs order by started_at desc limit 1),
      'last_run_outcome', (select scan_outcome from public.automation_runs order by started_at desc limit 1),
      'last_successful_scan_at', (select finished_at from public.automation_runs
        where scan_outcome in ('succeeded', 'zero_signals') order by finished_at desc limit 1),
      'last_successful_delivery_at', (select delivered_at from public.notification_deliveries
        where state = 'delivered' order by delivered_at desc limit 1),
      'recent_scan_failures', (select count(*) from public.automation_runs where finished_at > now() - interval '24 hours'
        and scan_outcome in ('provider_failed', 'infrastructure_failed')),
      'pending_retries', (select count(*) from public.notification_deliveries where state = 'retry'),
      'dead_letter_count_24h', (select count(*) from public.notification_deliveries
        where state = 'dead_letter' and updated_at > now() - interval '24 hours')
    ) into result;
    return result;
end;
$$;

create or replace function public.request_notification_test(notification_rule_id uuid)
returns uuid language plpgsql security definer set search_path = '' as $$
declare request_id uuid;
begin
    if auth.uid() is null then raise exception 'authentication required'; end if;
    if not exists(select 1 from public.notification_rules
      where id = notification_rule_id and user_id = auth.uid() and enabled) then
      raise exception 'enabled notification rule required';
    end if;
    if exists(select 1 from public.entitlements where user_id = auth.uid() and demo_expires_at > now()) then
      raise exception 'external delivery is unavailable for demo access';
    end if;
    insert into public.notification_test_requests(user_id, rule_id)
      values(auth.uid(), notification_rule_id) returning id into request_id;
    return request_id;
end;
$$;

create or replace function public.service_claim_notification_test(worker_instance text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare candidate public.notification_test_requests%rowtype;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    select t.* into candidate from public.notification_test_requests t
    join public.notification_rules r on r.id = t.rule_id and r.user_id = t.user_id
    left join public.entitlements e on e.user_id = t.user_id
    where (t.state = 'pending' or (t.state = 'processing' and t.processing_at < now() - interval '5 minutes'))
      and r.enabled and not coalesce(e.demo_expires_at > now(), false)
    order by t.requested_at for update of t skip locked limit 1;
    if candidate.id is null then return null; end if;
    update public.notification_test_requests set state = 'processing', processing_at = now(), claimed_by = worker_instance
      where id = candidate.id;
    return jsonb_build_object('id', candidate.id, 'rule_id', candidate.rule_id);
end;
$$;

create or replace function public.service_finish_notification_test(
    notification_test_request_id uuid, succeeded boolean, safe_error_code text default null
) returns void language plpgsql security definer set search_path = '' as $$
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    update public.notification_test_requests set state = case when succeeded then 'enqueued' else 'failed' end,
      processed_at = now(), processing_at = null, claimed_by = null,
      safe_error_code = case when succeeded then null
        else left(service_finish_notification_test.safe_error_code, 64) end
      where id = notification_test_request_id and state = 'processing';
end;
$$;

revoke all on function public.service_begin_automation_run(text, text, timestamptz) from public;
revoke all on function public.service_automation_heartbeat(uuid, text, text) from public;
revoke all on function public.service_finish_automation_scan(uuid, text, integer, text) from public;
revoke all on function public.service_list_notification_rules(text) from public;
revoke all on function public.service_upsert_system_notification_rule(text, boolean) from public;
revoke all on function public.service_enqueue_staging_notification_test(text, text, text) from public;
revoke all on function public.service_enqueue_telegram_delivery(uuid, uuid, text, text, jsonb, text, timestamptz, text) from public;
revoke all on function public.service_claim_telegram_delivery(text) from public;
revoke all on function public.service_finish_telegram_delivery(uuid, text, boolean, text, text, boolean, boolean, timestamptz) from public;
revoke all on function public.service_recover_abandoned_deliveries(integer) from public;
revoke all on function public.service_automation_health(integer) from public;
revoke all on function public.request_notification_test(uuid) from public;
revoke all on function public.service_claim_notification_test(text) from public;
revoke all on function public.service_finish_notification_test(uuid, boolean, text) from public;
grant execute on function public.service_begin_automation_run(text, text, timestamptz) to service_role;
grant execute on function public.service_automation_heartbeat(uuid, text, text) to service_role;
grant execute on function public.service_finish_automation_scan(uuid, text, integer, text) to service_role;
grant execute on function public.service_list_notification_rules(text) to service_role;
grant execute on function public.service_upsert_system_notification_rule(text, boolean) to service_role;
grant execute on function public.service_enqueue_staging_notification_test(text, text, text) to service_role;
grant execute on function public.service_enqueue_telegram_delivery(uuid, uuid, text, text, jsonb, text, timestamptz, text) to service_role;
grant execute on function public.service_claim_telegram_delivery(text) to service_role;
grant execute on function public.service_finish_telegram_delivery(uuid, text, boolean, text, text, boolean, boolean, timestamptz) to service_role;
grant execute on function public.service_recover_abandoned_deliveries(integer) to service_role;
grant execute on function public.service_automation_health(integer) to service_role;
grant execute on function public.request_notification_test(uuid) to authenticated;
grant execute on function public.service_claim_notification_test(text) to service_role;
grant execute on function public.service_finish_notification_test(uuid, boolean, text) to service_role;

-- Retain detailed operational history for 90 days and signal snapshots for 30 days.
create or replace function private.cleanup_automation_history()
returns void language plpgsql security definer set search_path = '' as $$
begin
    delete from public.notification_test_requests where requested_at < now() - interval '30 days';
    delete from public.notification_deliveries where created_at < now() - interval '90 days';
    delete from public.signal_snapshots where created_at < now() - interval '30 days'
      and not exists(select 1 from public.notification_deliveries d where d.signal_snapshot_id = signal_snapshots.id);
    delete from public.automation_runs where created_at < now() - interval '90 days'
      and not exists(select 1 from public.notification_deliveries d where d.run_id = automation_runs.id);
end;
$$;

revoke all on function private.cleanup_automation_history() from public, anon, authenticated, service_role;
select cron.unschedule(jobid) from cron.job where jobname = 'furuflow-automation-retention';
select cron.schedule('furuflow-automation-retention', '17 3 * * *', 'select private.cleanup_automation_history()');
