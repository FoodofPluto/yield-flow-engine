Merged build note: this package restores the original FuruFlow terminal UI and keeps the account-based Pro access system.

# FuruFlow Pro Production Starter

This zip gives you a **production-style starter** for the exact behavior you asked for:

- **You** can access FuruFlow Pro without paying yourself
- A real buyer should **purchase once**
- After purchase, the buyer should be able to **log in and open Pro directly**
- The app should **not force repeated paywall loops**

## What is inside

- `app.py` — Streamlit app with login, paywall gate, session cache, and Pro area
- `auth.py` — simple email sign-in session helper
- `db.py` — SQLite user database
- `entitlements.py` — access rules
- `stripe_stub.py` — demo one-time unlock flow
- `stripe_webhook_example.py` — example backend webhook handler for real Stripe fulfillment
- `.env.example` — environment variable template
- `requirements.txt` — Python packages

## Core architecture

The app uses this access logic:

1. User signs in with email
2. App checks the database for that user
3. Access is granted if any of the following are true:
   - user is admin
   - `DEV_MODE=true`
   - `lifetime_access=True`
   - `pro_active=True`

That means your real customers should **not** get stuck re-buying. Their entitlement lives in the database, not only in a temporary session.

## Quick start

Create and activate a virtual environment if you want, then install:

```bash
pip install -r requirements.txt
```

Run the app:

```bash
streamlit run app.py
```

## Give yourself permanent access

Open `.env.example`, copy it to `.env`, then set:

```env
ADMIN_EMAILS=yourrealemail@example.com
```

You can also set the variable directly in your environment.

## How this avoids repeat paywall friction

This starter does **not** rely on “did the checkout just happen right now?”

Instead it stores access in the database.  
That is the key difference.

When someone pays, your production flow should:

- complete Stripe Checkout
- receive a Stripe webhook on your backend
- locate the user by email or Stripe customer ID
- set `lifetime_access = True`

After that, every future login opens Pro directly.

## Recommended production flow for FuruFlow

### For you
- admin email bypass

### For customers
- sign in once
- buy once
- entitlement saved permanently
- return later and open Pro via login

### For the app
- check access once on load
- store the result in session state
- let Pro users move around freely

## Important note

This zip includes a **demo checkout button** for testing.  
It does **not** include a live hosted backend or real Stripe secret handling in the Streamlit app.

That is deliberate.

For production:
- keep Stripe secrets on the backend
- use `stripe_webhook_example.py` as the starting pattern
- do not trust the frontend alone for granting paid access

## Best next integration step

Wire this into your existing FuruFlow / Yield Flow Streamlit app by:

1. moving your current dashboard into the `if access_granted:` area
2. replacing the demo checkout UI with a real Stripe Checkout button
3. deploying the webhook separately
4. persisting users in a real hosted database later if needed

## Minimal implementation checklist

- [ ] Set your admin email
- [ ] Test login
- [ ] Test demo purchase
- [ ] Confirm repeat login opens Pro
- [ ] Replace demo purchase with Stripe Checkout
- [ ] Deploy Stripe webhook
- [ ] Mark paid users in DB automatically

## Files to edit first

- `app.py`
- `.env.example`
- `stripe_webhook_example.py`
