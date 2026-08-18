begin;

-- Prompt 2 trusted entitlement mutation:
-- service-only; browser/API user roles must never execute it.
revoke execute on function public.service_set_entitlement(
    uuid,
    text,
    boolean,
    uuid,
    text,
    timestamptz,
    text,
    text
) from public, anon, authenticated;

grant execute on function public.service_set_entitlement(
    uuid,
    text,
    boolean,
    uuid,
    text,
    timestamptz,
    text,
    text
) to service_role;


-- Prompt 5 Telegram worker claim:
-- service-only.
revoke execute on function public.service_claim_telegram_delivery(text)
from public, anon, authenticated;

grant execute on function public.service_claim_telegram_delivery(text)
to service_role;


-- Prompt 7 saved-pool listing:
-- authenticated users may invoke; anonymous users may not enter the RPC.
revoke execute on function public.list_my_saved_pools()
from public, anon;

grant execute on function public.list_my_saved_pools()
to authenticated, service_role;


-- Prompt 6 alert listing:
-- authenticated users may invoke; anonymous users may not enter the RPC.
revoke execute on function public.list_my_pool_alerts()
from public, anon;

grant execute on function public.list_my_pool_alerts()
to authenticated, service_role;

commit;
