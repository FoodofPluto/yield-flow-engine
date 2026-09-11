-- Prompt 18F. Render's validated beta configuration is the administrative
-- source; its startup supervisor atomically replaces this private snapshot.
-- No snapshot means no external participant capability. No participant IDs
-- are embedded in this migration. Apply before deploying the startup sync.
begin;

create table if not exists private.beta_admission (
    singleton boolean primary key default true check (singleton),
    enabled boolean not null,
    allowed_user_ids uuid[] not null,
    synchronized_at timestamptz not null default now(),
    check (not enabled or cardinality(allowed_user_ids) > 0),
    check (array_position(allowed_user_ids, null) is null)
);
alter table private.beta_admission enable row level security;
revoke all on private.beta_admission from public, anon, authenticated, service_role;

create or replace function public.service_sync_beta_admission(beta_enabled boolean, approved_user_ids uuid[])
returns boolean language plpgsql security definer set search_path = '' as $$
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    if beta_enabled is null or approved_user_ids is null
      or (beta_enabled and cardinality(approved_user_ids) = 0)
      or array_position(approved_user_ids, null) is not null then
      raise exception 'invalid beta admission configuration';
    end if;
    insert into private.beta_admission(singleton, enabled, allowed_user_ids)
      values(true, beta_enabled, approved_user_ids)
      on conflict(singleton) do update set enabled = excluded.enabled,
        allowed_user_ids = excluded.allowed_user_ids, synchronized_at = now();
    return true;
end;
$$;
revoke all on function public.service_sync_beta_admission(boolean, uuid[]) from public, anon, authenticated;
grant execute on function public.service_sync_beta_admission(boolean, uuid[]) to service_role;

-- Parameterized helpers are PRIVATE and callable only by their owner, never
-- by API users or the worker. Public caller RPCs always supply auth.uid().
create or replace function private.alert_beta_admitted(target_user_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
    select exists(select 1 from private.beta_admission b
      join auth.users u on u.id = target_user_id
      join public.entitlements e on e.user_id = u.id
      where b.singleton and u.email_confirmed_at is not null and u.deleted_at is null
        and (not b.enabled or e.is_admin or target_user_id = any(b.allowed_user_ids)));
$$;

create or replace function private.alert_paid_entitled(target_user_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
    select exists(select 1 from public.entitlements e
      join auth.users u on u.id = e.user_id
      where e.user_id = target_user_id and u.email_confirmed_at is not null and u.deleted_at is null
        and (e.is_admin or e.pro_active or e.lifetime_access
          or (e.subscription_pro_active and exists(select 1 from public.subscriptions s
            where s.user_id = e.user_id and s.provider = 'stripe' and s.status = 'active'
              and (s.current_period_end is null or s.current_period_end > now())))));
$$;

create or replace function private.alert_authorization_error(target_user_id uuid)
returns text language plpgsql stable security definer set search_path = '' as $$
begin
    if target_user_id is null then return 'authentication required'; end if;
    if not private.alert_beta_admitted(target_user_id) then return 'beta admission required'; end if;
    if exists(select 1 from public.entitlements where user_id = target_user_id and demo_expires_at > now()) then
      return 'external delivery is unavailable for demo access';
    end if;
    if not private.alert_paid_entitled(target_user_id) then return 'Pro entitlement required'; end if;
    if not exists(select 1 from public.telegram_connections c
      where c.user_id = target_user_id and c.state = 'linked'
        and c.verified_at is not null and c.revoked_at is null) then
      return 'verified Telegram connection required';
    end if;
    return null;
end;
$$;

create or replace function private.require_my_alert_authorization()
returns void language plpgsql security definer set search_path = '' as $$
declare failure text;
begin
    failure := private.alert_authorization_error(auth.uid());
    if failure is not null then raise exception '%', failure; end if;
end;
$$;
revoke all on function private.alert_beta_admitted(uuid) from public, anon, authenticated, service_role;
revoke all on function private.alert_paid_entitled(uuid) from public, anon, authenticated, service_role;
revoke all on function private.alert_authorization_error(uuid) from public, anon, authenticated, service_role;
revoke all on function private.require_my_alert_authorization() from public, anon, authenticated, service_role;

-- The account adapter reads these current database decisions. Browser input
-- cannot select an owner or supply entitlement/admission values.
create or replace function public.get_my_alert_authorization()
returns jsonb language plpgsql security definer set search_path = '' as $$
begin
    if auth.uid() is null then raise exception 'authentication required'; end if;
    return jsonb_build_object('beta_approved', private.alert_beta_admitted(auth.uid()),
      'paid_entitled', private.alert_paid_entitled(auth.uid()),
      'external_alerts_allowed', private.alert_authorization_error(auth.uid()) is null);
end;
$$;
revoke all on function public.get_my_alert_authorization() from public, anon;
grant execute on function public.get_my_alert_authorization() to authenticated;

-- Existing compatible RPC definitions follow; CREATE OR REPLACE preserves
-- their ownership and existing ACLs. All caller checks remain auth.uid based.
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
declare result jsonb;
begin
    perform private.require_my_alert_authorization();
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
declare changed_id uuid; result jsonb;
begin
    if auth.uid() is null then raise exception 'authentication required'; end if;
    if not exists(select 1 from public.notification_rules where id = notification_rule_id
      and user_id = auth.uid() and target_type = 'pool' and deleted_at is null) then
      raise exception 'alert unavailable';
    end if;
    perform private.require_my_alert_authorization();
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
    if alert_enabled then perform private.require_my_alert_authorization(); end if;
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

create or replace function public.request_notification_test(notification_rule_id uuid)
returns uuid language plpgsql security definer set search_path = '' as $$
declare request_id uuid;
begin
    perform private.require_my_alert_authorization();
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
      'entitled_to_pro', private.alert_paid_entitled(r.user_id),
      'demo_active', coalesce(e.demo_expires_at > now() and e.demo_environment = target_environment, false)
    ) order by r.created_at), '[]'::jsonb) into result
    from public.notification_rules r
    left join public.entitlements e on e.user_id = r.user_id
    left join public.telegram_connections connection on connection.id = r.telegram_connection_id
      and connection.user_id = r.user_id and connection.state = 'linked'
    where (r.user_id is null or private.alert_authorization_error(r.user_id) is null)
      and r.enabled and r.rule_kind = 'market' and r.deleted_at is null
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
    where (r.user_id is null or private.alert_authorization_error(r.user_id) is null)
      and d.state in ('queued', 'retry') and d.next_attempt_at <= now() and d.attempt_count < 3
      and r.enabled and r.deleted_at is null
      and (r.user_id is null or connection.id is not null)
      and (r.user_id is null or not coalesce(e.demo_expires_at > now(), false))
      and (lower(coalesce(s.payload ->> 'tier', 'free')) <> 'pro' or r.user_id is null
        or private.alert_paid_entitled(r.user_id))
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

create or replace function public.service_claim_notification_test(worker_instance text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare candidate public.notification_test_requests%rowtype;
begin
    if coalesce(auth.jwt() ->> 'role', '') <> 'service_role' then raise exception 'service role required'; end if;
    select t.* into candidate from public.notification_test_requests t
    join public.notification_rules r on r.id = t.rule_id and r.user_id = t.user_id
    join public.telegram_connections c on c.id = r.telegram_connection_id and c.user_id = r.user_id
    left join public.entitlements e on e.user_id = t.user_id
    where private.alert_authorization_error(t.user_id) is null
      and (t.state = 'pending' or (t.state = 'processing' and t.processing_at < now() - interval '5 minutes'))
      and r.enabled and r.deleted_at is null and c.state = 'linked'
      and not coalesce(e.demo_expires_at > now(), false)
    order by t.requested_at for update of t skip locked limit 1;
    if candidate.id is null then return null; end if;
    update public.notification_test_requests set state = 'processing', processing_at = now(), claimed_by = worker_instance
      where id = candidate.id;
    return jsonb_build_object('id', candidate.id, 'rule_id', candidate.rule_id);
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
    if not exists(select 1 from public.notification_rules where id = notification_rule_id and enabled and deleted_at is null
      and (user_id is null or private.alert_authorization_error(user_id) is null)) then
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

-- Explicit ACL reconciliation: older hosted default privileges may include
-- anon/authenticated even after revoking PUBLIC. Do not rely on defaults.
revoke all on function public.get_my_telegram_status() from public, anon;
grant execute on function public.get_my_telegram_status() to authenticated;
revoke all on function public.create_my_pool_alert(text, integer, text, text, time, time, text, integer, text) from public, anon;
grant execute on function public.create_my_pool_alert(text, integer, text, text, time, time, text, integer, text) to authenticated;
revoke all on function public.update_my_pool_alert(uuid, integer, text, text, time, time, text, integer) from public, anon;
grant execute on function public.update_my_pool_alert(uuid, integer, text, text, time, time, text, integer) to authenticated;
revoke all on function public.set_my_pool_alert_enabled(uuid, boolean) from public, anon;
grant execute on function public.set_my_pool_alert_enabled(uuid, boolean) to authenticated;
revoke all on function public.delete_my_pool_alert(uuid) from public, anon;
grant execute on function public.delete_my_pool_alert(uuid) to authenticated;
revoke all on function public.request_notification_test(uuid) from public, anon;
grant execute on function public.request_notification_test(uuid) to authenticated;
revoke all on function public.service_list_notification_rules(text) from public, anon, authenticated;
grant execute on function public.service_list_notification_rules(text) to service_role;
revoke all on function public.service_claim_telegram_delivery(text) from public, anon, authenticated;
grant execute on function public.service_claim_telegram_delivery(text) to service_role;
revoke all on function public.service_claim_notification_test(text) from public, anon, authenticated;
grant execute on function public.service_claim_notification_test(text) to service_role;
revoke all on function public.service_enqueue_telegram_delivery(uuid, uuid, text, text, jsonb, text, timestamptz, text) from public, anon, authenticated;
grant execute on function public.service_enqueue_telegram_delivery(uuid, uuid, text, text, jsonb, text, timestamptz, text) to service_role;

commit;
