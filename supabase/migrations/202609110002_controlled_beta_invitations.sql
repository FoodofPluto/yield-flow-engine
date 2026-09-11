-- Prompt 19C.1: service-only bearer invitations; canonical admission survives sync.
begin;
alter table private.beta_admission add column invited_user_ids uuid[] not null default '{}'
  check (array_position(invited_user_ids,null) is null);

create table private.beta_invitations (
    id uuid primary key default gen_random_uuid(),
    token_digest text not null unique check (token_digest ~ '^[0-9a-f]{64}$'),
    created_by uuid not null references auth.users(id),
    created_at timestamptz not null default now(),
    expires_at timestamptz not null default (now() + interval '24 hours'),
    claimed_at timestamptz,
    reserved_user_id uuid unique,
    consumed_at timestamptz,
    revoked_at timestamptz,
    check (expires_at > created_at and expires_at <= created_at + interval '24 hours'),
    check ((claimed_at is null) = (reserved_user_id is null)),
    check (consumed_at is null or (claimed_at is not null and revoked_at is null)),
    check (claimed_at is null or claimed_at >= created_at),
    check (consumed_at is null or consumed_at >= claimed_at),
    check (revoked_at is null or revoked_at >= created_at)
);
alter table private.beta_invitations enable row level security;
revoke all on private.beta_invitations from public, anon, authenticated, service_role;

create function private.require_invitation_operator(actor uuid)
returns void language plpgsql security definer set search_path = '' as $$
begin
    if not exists(select 1 from auth.users u join public.entitlements e on e.user_id=u.id
      where u.id=actor and u.email_confirmed_at is not null and u.deleted_at is null and e.is_admin) then
      raise exception 'verified administrator actor required';
    end if;
end;
$$;

create function public.service_create_beta_invitation(actor_user_id uuid, invitation_digest text)
returns uuid language plpgsql security definer set search_path = '' as $$
declare invitation_id uuid;
begin
    if coalesce(auth.jwt()->>'role','') <> 'service_role' then raise exception 'service role required'; end if;
    perform private.require_invitation_operator(actor_user_id);
    if not exists(select 1 from private.beta_admission where singleton and enabled) then
      raise exception 'closed beta required';
    end if;
    insert into private.beta_invitations(created_by, token_digest)
      values(actor_user_id, invitation_digest) returning id into invitation_id;
    return invitation_id;
end;
$$;

create function public.service_revoke_beta_invitation(actor_user_id uuid, invitation_id uuid)
returns boolean language plpgsql security definer set search_path = '' as $$
begin
    if coalesce(auth.jwt()->>'role','') <> 'service_role' then raise exception 'service role required'; end if;
    perform private.require_invitation_operator(actor_user_id);
    update private.beta_invitations set revoked_at=now()
      where id=invitation_id and consumed_at is null and revoked_at is null;
    return found;
end;
$$;

create function public.service_validate_beta_invitation(invitation_digest text)
returns boolean language sql security definer set search_path = '' as $$
    select coalesce(auth.jwt()->>'role','') = 'service_role' and exists(select 1 from private.beta_invitations i
      where i.token_digest=invitation_digest and i.expires_at>now()
        and i.claimed_at is null and i.revoked_at is null)
      and exists(select 1 from private.beta_admission where singleton and enabled);
$$;

-- A claim is terminal even if the external Auth request fails or times out.
-- Never release/reuse ambiguous claims: at most one Auth identity per invitation.
create function public.service_claim_beta_invitation(invitation_digest text)
returns uuid language plpgsql security definer set search_path = '' as $$
declare reserved uuid;
begin
    if coalesce(auth.jwt()->>'role','') <> 'service_role' then raise exception 'service role required'; end if;
    if not exists(select 1 from private.beta_admission where singleton and enabled) then return null; end if;
    update private.beta_invitations set claimed_at=now(), reserved_user_id=gen_random_uuid()
      where token_digest=invitation_digest and expires_at>now()
        and claimed_at is null and revoked_at is null
      returning reserved_user_id into reserved;
    return reserved;
end;
$$;

-- Admin createUser accepts the reserved UUID. No bearer/digest goes to Auth.
-- This trigger runs INSIDE the Auth insert transaction: consume + canonical
-- admission + account creation either commit together or all roll back.
create function private.consume_beta_invitation_for_new_user()
returns trigger language plpgsql security definer set search_path = '' as $$
declare invitation private.beta_invitations;
begin
    select * into invitation from private.beta_invitations
      where reserved_user_id=new.id for update;
    if not found then return new; end if;
    if invitation.consumed_at is not null or invitation.revoked_at is not null
      or invitation.expires_at<=now() or invitation.claimed_at<=now()-interval '5 minutes'
      or new.email_confirmed_at is not null or new.is_anonymous is true then
      raise exception 'invitation unavailable';
    end if;
    update private.beta_admission set invited_user_ids=array_append(invited_user_ids,new.id)
      where singleton and enabled and not new.id=any(invited_user_ids);
    if not found then raise exception 'invitation unavailable'; end if;
    update private.beta_invitations set consumed_at=now() where id=invitation.id;
    return new;
end;
$$;
create trigger furuflow_consume_beta_invitation after insert on auth.users
  for each row execute function private.consume_beta_invitation_for_new_user();

create or replace function private.alert_beta_admitted(target_user_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
    select exists(select 1 from private.beta_admission b
      join auth.users u on u.id = target_user_id
      join public.entitlements e on e.user_id = u.id
      where b.singleton and u.email_confirmed_at is not null and u.deleted_at is null
        and (not b.enabled or e.is_admin or target_user_id = any(b.allowed_user_ids)
          or target_user_id = any(b.invited_user_ids)));
$$;

revoke all on function private.require_invitation_operator(uuid) from public, anon, authenticated, service_role;
revoke all on function private.consume_beta_invitation_for_new_user() from public, anon, authenticated, service_role;
revoke all on function public.service_create_beta_invitation(uuid,text) from public, anon, authenticated;
revoke all on function public.service_revoke_beta_invitation(uuid,uuid) from public, anon, authenticated;
revoke all on function public.service_validate_beta_invitation(text) from public, anon, authenticated;
revoke all on function public.service_claim_beta_invitation(text) from public, anon, authenticated;
grant execute on function public.service_create_beta_invitation(uuid,text) to service_role;
grant execute on function public.service_revoke_beta_invitation(uuid,uuid) to service_role;
grant execute on function public.service_validate_beta_invitation(text) to service_role;
grant execute on function public.service_claim_beta_invitation(text) to service_role;
commit;
