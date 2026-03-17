import os
from db import get_user_by_email, set_lifetime_access

def can_access_pro(user: dict) -> bool:
    if not user:
        return False

    if user.get("is_admin"):
        return True

    if os.getenv("DEV_MODE", "").lower() == "true":
        return True

    if user.get("lifetime_access"):
        return True

    if user.get("pro_active"):
        return True

    return False

def grant_lifetime_access(email: str):
    user = get_user_by_email(email)
    if user:
        set_lifetime_access(email, True)
