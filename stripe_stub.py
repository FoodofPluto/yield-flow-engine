import streamlit as st
from db import upsert_user
from entitlements import grant_lifetime_access

def render_checkout_section(current_email: str):
    st.subheader("Unlock FuruFlow Pro")
    st.write("This starter uses a demo checkout. Replace this with Stripe Checkout + webhook fulfillment.")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**One-time purchase**")
        st.write("$49 lifetime unlock for this account")
        if st.button("Demo: Buy Pro once"):
            upsert_user(current_email, purchase_source="demo_checkout")
            grant_lifetime_access(current_email)
            st.success("Purchase recorded. This account now has lifetime Pro access.")
            st.rerun()

    with col2:
        st.markdown("**How production should work**")
        st.markdown(
            """
            1. User signs in  
            2. Clicks Stripe Checkout  
            3. Stripe webhook confirms payment  
            4. Your backend marks `lifetime_access = True`  
            5. Future logins open Pro automatically  
            """
        )
