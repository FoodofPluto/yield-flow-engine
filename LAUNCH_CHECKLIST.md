# FuruFlow launch checklist

## 1) Make the URL look like a website

If you are hosting on Streamlit Community Cloud, change the subdomain in App Settings so the link reads like a product website.
Example target:

`https://furuflow.streamlit.app`

## 2) Make Pro access persistent

- Keep the Streamlit app public for free mode
- Require users to sign in with the same email they use at checkout
- Let Stripe webhooks turn `pro_active` on and off in the database

## 3) What to tell testers

Ask them to test four things:

1. Can they open free mode without friction?
2. Can they sign in successfully?
3. After paying, does Pro unlock for the same email?
4. If they return later, does their Pro access still remain?

## 4) Best launch surfaces

- Product Hunt
- relevant DeFi / yield farming Discord servers that explicitly allow tool sharing
- X / Twitter threads around DeFi tooling
- subreddit communities only when the specific subreddit allows feedback or self-promo

## 5) What not to do

- Do not post the link as a blind promo everywhere
- Do not ask for fake engagement or botted ratings
- Do not post to DeFi communities without disclosing risks and what the product actually does
