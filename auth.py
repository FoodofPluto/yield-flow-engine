import uuid
import streamlit as st

from supabase_auth import AuthSessionError, request_magic_link, sign_in_with_password

def login_form():
    st.markdown("#### Verified sign in")
    email = st.text_input(
        "Email",
        placeholder="name@example.com",
        key="supabase_login_email",
    )
    password = st.text_input(
        "Password",
        type="password",
        key="supabase_login_password",
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Sign in", key="supabase_sign_in_button"):
            try:
                sign_in_with_password(email, password)
                st.success("Signed in with verified Supabase auth.")
                st.rerun()
            except AuthSessionError as exc:
                st.error(str(exc))
            except Exception:
                st.error("Verified sign-in failed.")
    with col2:
        if st.button("Email link", key="supabase_magic_link_button"):
            try:
                request_magic_link(email)
                st.info("Check your email for the sign-in link.")
            except AuthSessionError as exc:
                st.error(str(exc))
            except Exception:
                st.error("Could not send magic link.")

    st.markdown("#### Legacy free session")
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

def get_current_user():
    email = st.session_state.get("auth_email")
    if not email:
        return None
    return {"email": email}

def logout_button():
    if st.button("Log out", key="logout_button"):
        st.session_state.pop("auth_email", None)
        st.session_state.pop("auth_session_id", None)
        st.session_state.pop("auth_session_claimed", None)
        st.session_state.pop("access_granted", None)
        st.rerun()
