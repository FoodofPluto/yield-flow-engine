-- FuruFlow Prompt 7 authenticated saved pools.
-- Saved pools intentionally have no dependency on notification rules or delivery.

create table if not exists public.saved_pools (
    user_id uuid not null references auth.users(id) on delete cascade,
    pool_id text not null check (
      char_length(pool_id) between 1 and 200 and pool_id = trim(pool_id)
    ),
    created_at timestamptz not null default now(),
    primary key (user_id, pool_id)
);

create index if not exists saved_pools_owner_recent_idx
    on public.saved_pools(user_id, created_at desc, pool_id asc);

alter table public.saved_pools enable row level security;

drop policy if exists saved_pools_select_own on public.saved_pools;
create policy saved_pools_select_own on public.saved_pools
    for select to authenticated using (user_id = auth.uid());

drop policy if exists saved_pools_insert_own on public.saved_pools;
create policy saved_pools_insert_own on public.saved_pools
    for insert to authenticated with check (user_id = auth.uid());

drop policy if exists saved_pools_delete_own on public.saved_pools;
create policy saved_pools_delete_own on public.saved_pools
    for delete to authenticated using (user_id = auth.uid());

-- Browser writes use RPCs with no caller-supplied user ID. Direct writes remain
-- unavailable even though defensive RLS policies also enforce ownership.
revoke all on table public.saved_pools from public, anon, authenticated;
grant select on table public.saved_pools to authenticated;
grant all on table public.saved_pools to service_role;

create or replace function public.list_my_saved_pools()
returns jsonb language plpgsql security definer set search_path = '' as $$
declare result jsonb;
begin
    if auth.uid() is null then raise exception 'authentication required'; end if;
    select coalesce(jsonb_agg(jsonb_build_object(
      'pool_id', saved.pool_id,
      'created_at', saved.created_at
    ) order by saved.created_at desc, saved.pool_id asc), '[]'::jsonb)
      into result
      from public.saved_pools saved
      where saved.user_id = auth.uid();
    return result;
end;
$$;

create or replace function public.save_my_pool(requested_pool_id text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare saved public.saved_pools%rowtype;
begin
    if auth.uid() is null then raise exception 'authentication required'; end if;
    if requested_pool_id is null
      or char_length(trim(requested_pool_id)) < 1
      or char_length(requested_pool_id) > 200 then
      raise exception 'invalid pool';
    end if;
    insert into public.saved_pools(user_id, pool_id)
      values(auth.uid(), trim(requested_pool_id))
      on conflict(user_id, pool_id) do nothing;
    select * into saved from public.saved_pools
      where user_id = auth.uid() and pool_id = trim(requested_pool_id);
    return jsonb_build_object('pool_id', saved.pool_id, 'created_at', saved.created_at);
end;
$$;

create or replace function public.delete_my_saved_pool(requested_pool_id text)
returns boolean language plpgsql security definer set search_path = '' as $$
declare changed integer;
begin
    if auth.uid() is null then raise exception 'authentication required'; end if;
    if requested_pool_id is null
      or char_length(trim(requested_pool_id)) < 1
      or char_length(requested_pool_id) > 200 then
      raise exception 'invalid pool';
    end if;
    delete from public.saved_pools
      where user_id = auth.uid() and pool_id = trim(requested_pool_id);
    get diagnostics changed = row_count;
    return changed = 1;
end;
$$;

revoke all on function public.list_my_saved_pools() from public;
revoke all on function public.save_my_pool(text) from public;
revoke all on function public.delete_my_saved_pool(text) from public;

grant execute on function public.list_my_saved_pools() to authenticated;
grant execute on function public.save_my_pool(text) to authenticated;
grant execute on function public.delete_my_saved_pool(text) to authenticated;
