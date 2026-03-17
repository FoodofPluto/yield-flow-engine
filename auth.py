import streamlit as st

def login_form():
    if "auth_email" not in st.session_state:
        st.session_state["auth_email"] = ""

    email = st.text_input(
        "Email",
        value=st.session_state["auth_email"],
        placeholder="name@example.com",
        key="login_email_input",
    )

    if st.button("Sign in", key="sign_in_button"):
        email = (email or "").strip().lower()
        if "@" not in email:
            st.error("Enter a valid email.")
        else:
            st.session_state["auth_email"] = email
            st.rerun()

def get_current_user():
    email = st.session_state.get("auth_email")
    if not email:
        return None
    return {"email": email}

def logout_button():
    if st.button("Log out", key="logout_button"):
        st.session_state.pop("auth_email", None)
        st.session_state.pop("access_granted", None)
        st.rerun()
