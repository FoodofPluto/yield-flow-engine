from __future__ import annotations

import uuid

import streamlit as st

from auth_session import get_auth_session_store
from furuflow_auth import (
    PASSWORD_RECOVERY_KEY,
    AuthSessionError,
    complete_password_reset,
    handle_auth_callback,
    pop_auth_notice,
    request_magic_link,
    request_password_reset,
    resend_verification,
    sign_in_with_password,
    signup,
)


def _render_error(exc: AuthSessionError) -> None:
    st.error(str(exc))


def _render_notice() -> None:
    notice = pop_auth_notice()
    if not notice:
        return
    renderer = getattr(st, notice.get("level", "error"), st.error)
    renderer(notice.get("message", "Authentication could not be completed."))


def _process_callback() -> None:
    try:
        result = handle_auth_callback(st.query_params)
    except AuthSessionError as exc:
        _render_error(exc)
        return
    if not result:
        return
    if result["status"] == "password_recovery":
        st.success("Reset link accepted. Choose a new password below.")
    else:
        st.success("Email verified and sign-in completed.")


def _password_recovery_form() -> bool:
    if not st.session_state.get(PASSWORD_RECOVERY_KEY):
        return False
    st.markdown("#### Choose a new password")
    with st.form("supabase_complete_password_reset"):
        password = st.text_input("New password", type="password", key="supabase_reset_new_password")
        confirmation = st.text_input("Confirm new password", type="password", key="supabase_reset_confirm_password")
        submitted = st.form_submit_button("Update password")
    if submitted:
        if password != confirmation:
            st.error("Passwords do not match.")
        else:
            try:
                complete_password_reset(password)
                st.success("Password updated. You are signed in.")
                st.rerun()
            except AuthSessionError as exc:
                _render_error(exc)
    return True


def _sign_in_tab() -> None:
    with st.form("supabase_password_login"):
        email = st.text_input("Email", placeholder="name@example.com", key="supabase_login_email")
        password = st.text_input("Password", type="password", key="supabase_login_password")
        password_submit = st.form_submit_button("Sign in")
    if password_submit:
        try:
            sign_in_with_password(email, password)
            st.success("Signed in.")
            st.rerun()
        except AuthSessionError as exc:
            _render_error(exc)

    with st.form("supabase_magic_link"):
        magic_email = st.text_input("Email for sign-in link", placeholder="name@example.com", key="supabase_magic_email")
        magic_submit = st.form_submit_button("Email me a sign-in link")
    if magic_submit:
        try:
            request_magic_link(magic_email)
            st.info("If the account is eligible, a sign-in link is on its way.")
        except AuthSessionError as exc:
            _render_error(exc)


def _signup_tab() -> None:
    with st.form("supabase_signup"):
        email = st.text_input("Email", placeholder="name@example.com", key="supabase_signup_email")
        password = st.text_input("Password (12+ characters)", type="password", key="supabase_signup_password")
        confirmation = st.text_input("Confirm password", type="password", key="supabase_signup_confirmation")
        submitted = st.form_submit_button("Create account")
    if submitted:
        if password != confirmation:
            st.error("Passwords do not match.")
        else:
            try:
                result = signup(email, password)
                if result["status"] == "signed_in":
                    st.success("Account created and signed in.")
                    st.rerun()
                else:
                    st.info("Check your inbox to continue. If the account exists, use sign in or password reset.")
            except AuthSessionError as exc:
                _render_error(exc)

    with st.form("supabase_resend_verification"):
        resend_email = st.text_input("Email to verify", placeholder="name@example.com", key="supabase_resend_email")
        resend_submit = st.form_submit_button("Resend verification")
    if resend_submit:
        try:
            resend_verification(resend_email)
            st.info("If verification is pending, a new message is on its way.")
        except AuthSessionError as exc:
            _render_error(exc)


def _reset_tab() -> None:
    with st.form("supabase_password_reset_request"):
        email = st.text_input("Account email", placeholder="name@example.com", key="supabase_reset_email")
        submitted = st.form_submit_button("Send password-reset link")
    if submitted:
        try:
            request_password_reset(email)
            st.info("If the account exists, a password-reset link is on its way.")
        except AuthSessionError as exc:
            _render_error(exc)


def _legacy_free_session() -> None:
    with st.expander("Legacy free session"):
        st.caption("This unverified compatibility session cannot access Pro or admin features.")
        if "auth_email" not in st.session_state:
            st.session_state["auth_email"] = ""
        legacy_email = st.text_input(
            "Legacy email",
            value=st.session_state["auth_email"],
            placeholder="name@example.com",
            key="login_email_input",
        )
        if st.button("Continue free", key="sign_in_button"):
            legacy_email = (legacy_email or "").strip().lower()
            if "@" not in legacy_email:
                st.error("Enter a valid email.")
            else:
                st.session_state["auth_email"] = legacy_email
                st.session_state["auth_session_id"] = uuid.uuid4().hex
                st.session_state["auth_session_claimed"] = False
                st.rerun()


def login_form() -> None:
    _render_notice()
    _process_callback()
    if _password_recovery_form():
        return
    if get_auth_session_store().load():
        st.caption("Verified Supabase session active.")
        return

    st.markdown("#### Verified account")
    sign_in_tab, signup_tab, reset_tab = st.tabs(["Sign in", "Create", "Reset"])
    with sign_in_tab:
        _sign_in_tab()
    with signup_tab:
        _signup_tab()
    with reset_tab:
        _reset_tab()
    st.caption("Sessions are kept in server memory for this browser connection; closing or refreshing may require sign-in again.")
    _legacy_free_session()


def get_current_user():
    email = st.session_state.get("auth_email")
    if not email:
        return None
    return {"email": email}


def logout_button() -> None:
    if st.button("Log out", key="auth_module_logout_button"):
        from auth_service import logout

        logout()
        st.rerun()
