-- FuruFlow Prompt 6 authenticated pool alerts and verified Telegram linkage.
-- Apply after 202608150001_prompt5_telegram_automation.sql.

create table if not exists public.telegram_connections (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null unique references auth.users(id) on delete cascade,
    telegram_chat_id text not null unique check (char_length(telegram_chat_id) between 1 and 128),
    state text not null default 'linked' check (state in ('linked', 'revoked')),
    verified_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check ((state = 'linked' and verified_at is not null and revoked_at is null)
      or (state = 'revoked' and revoked_at is not null))
);

drop trigger if exists telegram_connections_touch_updated_at on public.telegram_connections;
create trigger telegram_connections_touch_updated_at before update on public.telegram_connections
for each row execute function public.touch_updated_at();

alter table public.telegram_connections enable row level security;
revoke all on table public.telegram_connections from public, anon, authenticated;
grant all on table public.telegram_connections to service_role;

alter table public.notification_rules alter column telegram_chat_id drop not null;
alter table public.notification_rules
    add column if not exists telegram_connection_id uuid references public.telegram_connections(id) on delete set null,
    add column if not exists target_type text not null default 'any_signal'
      check (target_type in ('any_signal', 'pool')),
    add column if not exists target_pool_id text
      check (target_pool_id is null or char_length(target_pool_id) between 1 and 200),
    add column if not exists condition_type text not null default 'signal_qualified'
      check (condition_type = 'signal_qualified'),
    add column if not exists client_request_key text
      check (client_request_key is null or char_length(client_request_key) between 8 and 100),
    add column if not exists last_evaluated_at timestamptz,
    add column if not exists last_triggered_at timestamptz,
    add column if not exists deleted_at timestamptz;

-- Existing user-entered raw destinations were not verified by Prompt 5. Keep
-- their rows for audit, but disable them and remove routing until relinked.
update public.notification_rules
set enabled = false, telegram_chat_id = null
where user_id is not null and telegram_chat_id is not null;

alter table public.notification_rules
    drop constraint if exists notification_rules_target_consistency;
alter table public.notification_rules
    add constraint notification_rules_target_consistency check (
      (target_type = 'any_signal' and target_pool_id is null)
      or (target_type = 'pool' and target_pool_id is not null)
    );
alter table public.notification_rules
    drop constraint if exists notification_rules_destination_consistency;
alter table public.notification_rules
    add constraint notification_rules_destination_consistency check (
      (user_id is null and telegram_chat_id is not null and telegram_connection_id is null)
      or (user_id is not null and telegram_chat_id is null
        and (not enabled or telegram_connection_id is not null))
    );

create unique index if not exists notification_rules_user_request_key_idx
    on public.notification_rules(user_id, client_request_key)
    where user_id is not null and client_request_key is not null;
create index if not exists notification_rules_pool_alert_idx
    on public.notification_rules(user_id, target_pool_id, enabled)
    where deleted_at is null and target_type = 'pool';

-- Browser writes are routed through ownership-deriving RPCs below. Retain
-- self-select for existing RLS-backed delivery-history policies.
revoke insert, update, delete on public.notification_rules from authenticated;

create or replace function public.get_my_telegram_status()
returns jsonb language plpgsql security definer set search_path = '' as $$
declare connection public.telegram_connections%rowtype;
begin
    if auth.uid() is null then raise exception 'authentication required'; end if;
    select * into connection from public.telegram_connections where user_id = auth.uid();
    return jsonb_build_object(
      'available', connection.id is not null and connection.state = 'linked',
      'channel', 'telegram',
      'status', case when connection.id is null then 'not_linked' else connection.state end,
      'linked_at', case when connection.state = 'linked' then connection.verified_at else null end
    );
end;
$$;

create or replace function public.list_my_pool_alerts()
returns jsonb language plpgsql security definer set search_path = '' as $$
declare result jsonb;
begin
    if auth.uid() is null then raise exception 'authentication required'; end if;
    select coalesce(jsonb_agg(jsonb_build_object(
      'id', r.id, 'target_pool_id', r.target_pool_id, 'condition_type', r.condition_type,
      'enabled', r.enabled, 'minimum_strength', r.minimum_strength, 'signal_tier', r.signal_tier,
      'delivery_mode', r.delivery_mode, 'quiet_hours_start', r.quiet_hours_start,
      'quiet_hours_end', r.quiet_hours_end, 'timezone', r.timezone,
      'cooldown_minutes', r.cooldown_minutes, 'last_evaluated_at', r.last_evaluated_at,
      'last_triggered_at', r.last_triggered_at, 'created_at', r.created_at, 'updated_at', r.updated_at,
      'last_delivery_state', delivery.state, 'last_delivered_at', delivery.delivered_at
    ) order by r.created_at desc), '[]'::jsonb) into result
    from public.notification_rules r
    left join lateral (
      select d.state, d.delivered_at from public.notification_deliveries d
      where d.rule_id = r.id order by d.created_at desc limit 1
    ) delivery on true
    where r.user_id = auth.uid() and r.rule_kind = 'market'
      and r.target_type = 'pool' and r.deleted_at is null;
    return result;
end;
$$;

create or replace function public.create_my_pool_alert(
    requested_target_pool_id text,
    requested_minimum_strength integer default 0,
    requested_signal_tier text default 'all',
    requested_delivery_mode text default 'immediate',
    requested_quiet_hours_start time default null,
    requested_quiet_hours_end time default null,
    requested_timezone text default 'UTC',
    requested_cooldown_minutes integer default 1440,
    request_key text default null
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare connection public.telegram_connections%rowtype; alert_id uuid;
declare pro_allowed boolean; result jsonb;
begin
    if auth.uid() is null then raise exception 'authentication required'; end if;
    if char_length(trim(requested_target_pool_id)) < 1 or char_length(requested_target_pool_id) > 200 then raise exception 'invalid pool'; end if;
    if requested_minimum_strength < 0 or requested_minimum_strength > 100 then raise exception 'invalid strength'; end if;
    if requested_signal_tier not in ('all', 'free', 'pro') then raise exception 'invalid signal tier'; end if;
    if requested_delivery_mode not in ('immediate', 'digest') then raise exception 'invalid delivery mode'; end if;
    if (requested_quiet_hours_start is null) <> (requested_quiet_hours_end is null) then
      raise exception 'quiet hours must include start and end';
    end if;
    if requested_cooldown_minutes < 1 or requested_cooldown_minutes > 43200 then raise exception 'invalid cooldown'; end if;
    if not exists(select 1 from pg_catalog.pg_timezone_names where name = requested_timezone) then
      raise exception 'invalid timezone';
    end if;
    if request_key is null or char_length(request_key) < 8 or char_length(request_key) > 100 then
      raise exception 'invalid request key';
    end if;
    if exists(select 1 from public.entitlements where user_id = auth.uid() and demo_expires_at > now()) then
      raise exception 'external delivery is unavailable for demo access';
    end if;
    select * into connection from public.telegram_connections
      where user_id = auth.uid() and state = 'linked' for update;
    if connection.id is null then raise exception 'verified Telegram connection required'; end if;
    select coalesce(is_admin or pro_active or lifetime_access, false) into pro_allowed
      from public.entitlements where user_id = auth.uid();
    if requested_signal_tier = 'pro' and not coalesce(pro_allowed, false) then
      raise exception 'Pro entitlement required';
    end if;
    insert into public.notification_rules(
      user_id, rule_key, rule_kind, telegram_chat_id, telegram_connection_id,
      enabled, minimum_strength, signal_tier, delivery_mode, quiet_hours_start,
      quiet_hours_end, timezone, cooldown_minutes, target_type, target_pool_id,
      condition_type, client_request_key
    ) values(
      auth.uid(), 'user-alert-' || pg_catalog.md5(auth.uid()::text || ':' || request_key),
      'market', null, connection.id,
      true, requested_minimum_strength, requested_signal_tier, requested_delivery_mode, requested_quiet_hours_start,
      requested_quiet_hours_end, requested_timezone, requested_cooldown_minutes,
      'pool', trim(requested_target_pool_id), 'signal_qualified', request_key
    ) on conflict(user_id, client_request_key) where user_id is not null and client_request_key is not null
      do update set client_request_key = excluded.client_request_key returning id into alert_id;
    select jsonb_build_object('id', id, 'target_pool_id', notification_rules.target_pool_id,
      'enabled', enabled, 'minimum_strength', notification_rules.minimum_strength,
      'signal_tier', signal_tier, 'delivery_mode', delivery_mode)
      into result from public.notification_rules where id = alert_id and user_id = auth.uid();
    return result;
end;
$$;

create or replace function public.update_my_pool_alert(
    notification_rule_id uuid,
    requested_minimum_strength integer,
    requested_signal_tier text,
    requested_delivery_mode text,
    requested_quiet_hours_start time,
    requested_quiet_hours_end time,
    requested_timezone text,
    requested_cooldown_minutes integer
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare changed_id uuid; pro_allowed boolean; result jsonb;
begin
    if auth.uid() is null then raise exception 'authentication required'; end if;
    if requested_minimum_strength < 0 or requested_minimum_strength > 100 then raise exception 'invalid strength'; end if;
    if requested_signal_tier not in ('all', 'free', 'pro') then raise exception 'invalid signal tier'; end if;
    if requested_delivery_mode not in ('immediate', 'digest') then raise exception 'invalid delivery mode'; end if;
    if (requested_quiet_hours_start is null) <> (requested_quiet_hours_end is null) then
      raise exception 'quiet hours must include start and end';
    end if;
    if requested_cooldown_minutes < 1 or requested_cooldown_minutes > 43200 then raise exception 'invalid cooldown'; end if;
    if not exists(select 1 from pg_catalog.pg_timezone_names where name = requested_timezone) then
      raise exception 'invalid timezone';
    end if;
    select coalesce(is_admin or pro_active or lifetime_access, false) into pro_allowed
      from public.entitlements where user_id = auth.uid();
    if requested_signal_tier = 'pro' and not coalesce(pro_allowed, false) then
      raise exception 'Pro entitlement required';
    end if;
    update public.notification_rules set minimum_strength = requested_minimum_strength,
      signal_tier = requested_signal_tier, delivery_mode = requested_delivery_mode,
      quiet_hours_start = requested_quiet_hours_start, quiet_hours_end = requested_quiet_hours_end,
      timezone = requested_timezone, cooldown_minutes = requested_cooldown_minutes
      where id = notification_rule_id and user_id = auth.uid() and target_type = 'pool' and deleted_at is null
      returning id into changed_id;
    if changed_id is null then raise exception 'alert unavailable'; end if;
    select jsonb_build_object('id', id, 'target_pool_id', target_pool_id,
      'enabled', enabled, 'minimum_strength', notification_rules.minimum_strength,
      'signal_tier', signal_tier, 'delivery_mode', delivery_mode)
      into result from public.notification_rules where id = changed_id;
    return result;
end;
$$;

create or replace function public.set_my_pool_alert_enabled(notification_rule_id uuid, alert_enabled boolean)
returns boolean language plpgsql security definer set search_path = '' as $$
declare changed integer;
begin
    if auth.uid() is null then raise exception 'authentication required'; end if;
    if alert_enabled and not exists(
      select 1 from public.telegram_connections c where c.user_id = auth.uid() and c.state = 'linked'
    ) then raise exception 'verified Telegram connection required'; end if;
    if alert_enabled and exists(
      select 1 from public.entitlements where user_id = auth.uid() and demo_expires_at > now()
    ) then raise exception 'external delivery is unavailable for demo access'; end if;
    update public.notification_rules set enabled = alert_enabled
      where id = notification_rule_id and user_id = auth.uid() and target_type = 'pool' and deleted_at is null;
    get diagnostics changed = row_count;
    return changed = 1;
end;
$$;

create or replace function public.delete_my_pool_alert(notification_rule_id uuid)
returns boolean language plpgsql security definer set search_path = '' as $$
declare changed integer;
begin
    if auth.uid() is null then raise exception 'authentication required'; end if;
    update public.notification_rules set enabled = false, deleted_at = now()
      where id = notification_rule_id and user_id = auth.uid() and target_type = 'pool' and deleted_at is null;
    get diagnostics changed = row_count;
    return changed = 1;
end;
$$;

create or replace function public.service_set_user_telegram_connection(
    target_user_id uuid, destination_chat_id text, connection_linked boolean default true
) returns uuid language plpgsql security definer set search_path = '' as $$
declare connection_id uuid;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    if not exists(select 1 from auth.users where id = target_user_id
      and email_confirmed_at is not null and deleted_at is null) then raise exception 'verified active user required'; end if;
    if connection_linked then
      if char_length(destination_chat_id) < 1 or char_length(destination_chat_id) > 128 then
        raise exception 'invalid Telegram destination';
      end if;
      insert into public.telegram_connections(user_id, telegram_chat_id, state, verified_at, revoked_at)
      values(target_user_id, destination_chat_id, 'linked', now(), null)
      on conflict(user_id) do update set telegram_chat_id = excluded.telegram_chat_id,
        state = 'linked', verified_at = now(), revoked_at = null returning id into connection_id;
      update public.notification_rules set telegram_connection_id = connection_id
        where user_id = target_user_id and deleted_at is null;
    else
      update public.telegram_connections set state = 'revoked', revoked_at = now()
        where user_id = target_user_id returning id into connection_id;
      update public.notification_rules set enabled = false where user_id = target_user_id and deleted_at is null;
    end if;
    return connection_id;
end;
$$;

create or replace function public.service_record_notification_rule_evaluations(
    automation_run_id uuid, evaluated_rule_ids uuid[], triggered_rule_ids uuid[] default '{}'::uuid[]
) returns void language plpgsql security definer set search_path = '' as $$
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    if not exists(select 1 from public.automation_runs where id = automation_run_id) then raise exception 'run missing'; end if;
    update public.notification_rules set last_evaluated_at = now(),
      last_triggered_at = case when id = any(triggered_rule_ids) then now() else last_triggered_at end
      where id = any(evaluated_rule_ids) and enabled and deleted_at is null;
end;
$$;

create or replace function public.service_list_notification_rules(target_environment text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare result jsonb;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    select coalesce(jsonb_agg(jsonb_build_object(
      'id', r.id, 'user_id', r.user_id,
      'telegram_chat_id', coalesce(r.telegram_chat_id, connection.telegram_chat_id),
      'enabled', r.enabled, 'minimum_strength', r.minimum_strength, 'signal_tier', r.signal_tier,
      'delivery_mode', r.delivery_mode, 'quiet_hours_start', r.quiet_hours_start,
      'quiet_hours_end', r.quiet_hours_end, 'timezone', r.timezone,
      'cooldown_minutes', r.cooldown_minutes, 'rule_kind', r.rule_kind,
      'target_type', r.target_type, 'target_pool_id', r.target_pool_id,
      'condition_type', r.condition_type,
      'entitled_to_pro', coalesce(e.is_admin or e.pro_active or e.lifetime_access, false),
      'demo_active', coalesce(e.demo_expires_at > now() and e.demo_environment = target_environment, false)
    ) order by r.created_at), '[]'::jsonb) into result
    from public.notification_rules r
    left join public.entitlements e on e.user_id = r.user_id
    left join public.telegram_connections connection on connection.id = r.telegram_connection_id
      and connection.user_id = r.user_id and connection.state = 'linked'
    where r.enabled and r.rule_kind = 'market' and r.deleted_at is null
      and (r.user_id is null or connection.id is not null);
    return result;
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
    left join public.telegram_connections connection on connection.id = r.telegram_connection_id
      and connection.user_id = r.user_id and connection.state = 'linked'
    where d.state in ('queued', 'retry') and d.next_attempt_at <= now() and d.attempt_count < 3
      and r.enabled and r.deleted_at is null
      and (r.user_id is null or connection.id is not null)
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
      'telegram_chat_id', coalesce(r.telegram_chat_id, connection.telegram_chat_id),
      'message_text', d.message_text, 'delivery_kind', d.delivery_kind) into result
      from public.notification_deliveries d
      join public.notification_rules r on r.id = d.rule_id
      left join public.telegram_connections connection on connection.id = r.telegram_connection_id
      where d.id = candidate.id;
    return result;
end;
$$;

create or replace function public.request_notification_test(notification_rule_id uuid)
returns uuid language plpgsql security definer set search_path = '' as $$
declare request_id uuid;
begin
    if auth.uid() is null then raise exception 'authentication required'; end if;
    if not exists(select 1 from public.notification_rules r
      join public.telegram_connections c on c.id = r.telegram_connection_id and c.user_id = r.user_id
      where r.id = notification_rule_id and r.user_id = auth.uid() and r.enabled
        and r.deleted_at is null and c.state = 'linked') then
      raise exception 'enabled alert with verified Telegram connection required';
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
    join public.telegram_connections c on c.id = r.telegram_connection_id and c.user_id = r.user_id
    left join public.entitlements e on e.user_id = t.user_id
    where (t.state = 'pending' or (t.state = 'processing' and t.processing_at < now() - interval '5 minutes'))
      and r.enabled and r.deleted_at is null and c.state = 'linked'
      and not coalesce(e.demo_expires_at > now(), false)
    order by t.requested_at for update of t skip locked limit 1;
    if candidate.id is null then return null; end if;
    update public.notification_test_requests set state = 'processing', processing_at = now(), claimed_by = worker_instance
      where id = candidate.id;
    return jsonb_build_object('id', candidate.id, 'rule_id', candidate.rule_id);
end;
$$;

revoke all on function public.get_my_telegram_status() from public;
revoke all on function public.list_my_pool_alerts() from public;
revoke all on function public.create_my_pool_alert(text, integer, text, text, time, time, text, integer, text) from public;
revoke all on function public.update_my_pool_alert(uuid, integer, text, text, time, time, text, integer) from public;
revoke all on function public.set_my_pool_alert_enabled(uuid, boolean) from public;
revoke all on function public.delete_my_pool_alert(uuid) from public;
revoke all on function public.service_set_user_telegram_connection(uuid, text, boolean) from public;
revoke all on function public.service_record_notification_rule_evaluations(uuid, uuid[], uuid[]) from public;
revoke all on function public.service_list_notification_rules(text) from public;
revoke all on function public.service_claim_telegram_delivery(text) from public;
revoke all on function public.request_notification_test(uuid) from public;
revoke all on function public.service_claim_notification_test(text) from public;

grant execute on function public.get_my_telegram_status() to authenticated;
grant execute on function public.list_my_pool_alerts() to authenticated;
grant execute on function public.create_my_pool_alert(text, integer, text, text, time, time, text, integer, text) to authenticated;
grant execute on function public.update_my_pool_alert(uuid, integer, text, text, time, time, text, integer) to authenticated;
grant execute on function public.set_my_pool_alert_enabled(uuid, boolean) to authenticated;
grant execute on function public.delete_my_pool_alert(uuid) to authenticated;
grant execute on function public.request_notification_test(uuid) to authenticated;
grant execute on function public.service_set_user_telegram_connection(uuid, text, boolean) to service_role;
grant execute on function public.service_record_notification_rule_evaluations(uuid, uuid[], uuid[]) to service_role;
grant execute on function public.service_list_notification_rules(text) to service_role;
grant execute on function public.service_claim_telegram_delivery(text) to service_role;
grant execute on function public.service_claim_notification_test(text) to service_role;
