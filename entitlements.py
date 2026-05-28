from db import get_user_by_email, set_lifetime_access
from auth_service import can_access_pro


def grant_lifetime_access(email: str):
    user = get_user_by_email(email)
    if user:
        set_lifetime_access(email, True)
