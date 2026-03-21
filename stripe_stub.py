import streamlit as st


def render_checkout_section(current_email: str):
    st.subheader("Unlock FuruFlow Pro")
    st.write("Use the checkout link below to unlock Pro for this account.")
    if current_email:
        st.info(
            f"Signed in as: {current_email}. FuruFlow now passes this email into checkout to reduce access mismatches."
        )
    else:
        st.info("Sign in with your email first so checkout can stay tied to the same account.")
