import os
import streamlit as st
from db import init_db, get_user_by_email, upsert_user
from auth import login_form, logout_button, get_current_user
from entitlements import can_access_pro, grant_lifetime_access
from stripe_stub import render_checkout_section

st.set_page_config(page_title="FuruFlow Pro", page_icon="📈", layout="wide")

ADMIN_EMAILS = {
    email.strip().lower()
    for email in os.getenv("ADMIN_EMAILS", "you@example.com").split(",")
    if email.strip()
}

init_db()

st.title("FuruFlow")
st.caption("Production-style starter for one-time Pro unlock + persistent access")

with st.sidebar:
    st.header("Account")

user = get_current_user()

if not user:
    with st.sidebar:
        login_form()
    st.info("Sign in with your email to continue.")
    st.stop()

email = user["email"].lower()
# Always upsert after login so an existing user can still be promoted to admin
db_user = upsert_user(email=email, is_admin=(email in ADMIN_EMAILS))

# Refresh after possible admin update
db_user = get_user_by_email(email)
access = can_access_pro(db_user)
st.session_state["access_granted"] = access

with st.sidebar:
    st.write(f"Signed in as: **{db_user['email']}**")
    st.write(f"Admin: **{'Yes' if db_user['is_admin'] else 'No'}**")
    st.write(f"Lifetime access: **{'Yes' if db_user['lifetime_access'] else 'No'}**")
    st.write(f"Pro active: **{'Yes' if db_user['pro_active'] else 'No'}**")
    logout_button()

if st.session_state["access_granted"]:
    st.success("Welcome to FuruFlow Pro.")
    tab1, tab2, tab3 = st.tabs(["Dashboard", "Opportunities", "Admin Notes"])

    with tab1:
        st.subheader("Dashboard")
        st.write("Your Pro analytics dashboard would load here.")
        st.metric("Tracked protocols", 128)
        st.metric("Opportunities today", 37)
        st.metric("Avg top APY", "21.4%")

    with tab2:
        st.subheader("Opportunities")
        st.dataframe(
            [
                {"protocol": "Aave", "chain": "Ethereum", "apy": "8.1%", "risk": "Low"},
                {"protocol": "Pendle", "chain": "Arbitrum", "apy": "18.6%", "risk": "Medium"},
                {"protocol": "Morpho", "chain": "Base", "apy": "11.9%", "risk": "Low"},
            ],
            use_container_width=True,
        )

    with tab3:
        st.subheader("Operational notes")
        st.markdown(
            """
            - Access is entitlement-based, not session-purchase-based.
            - Buyers pay once and then open Pro through login.
            - Admins bypass the paywall automatically.
            - Replace the demo checkout with Stripe webhook-driven unlocks.
            """
        )
else:
    st.warning("FuruFlow Pro required.")
    st.write("A paying user should only need to purchase once. After that, login should open Pro directly.")
    render_checkout_section(current_email=db_user["email"])

    st.divider()
    st.subheader("Restore access")
    st.write("If someone already paid, they should sign back into the same email account used for purchase.")
    if st.button("Demo: Restore / Unlock Pro for this account"):
        grant_lifetime_access(db_user["email"])
        st.session_state["access_granted"] = True
        st.success("Pro restored for this account.")
        st.rerun()
