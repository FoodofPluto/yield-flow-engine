import streamlit as st

def render_checkout_section(current_email: str):
    st.subheader("Unlock FuruFlow Pro")
    st.write("Use the purchase link below to unlock Pro for this account.")
    st.info(
        f"Signed in as: {current_email}. To avoid access issues, complete checkout with this same email."
    )
