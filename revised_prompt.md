# Revised Build Prompt — Yield Flow Engine Rebrand + UI Upgrade

Transform the current Yield Flow Engine Streamlit app into a polished, product-grade DeFi yield analytics dashboard that feels materially closer to a lightweight companion to DeFiLlama rather than a basic internal tool.

## Core goals
- Rename the app with a distinctive product identity instead of "Yield Flow Engine"
- Make the UI feel premium, spacious, modern, and readable
- Eliminate the need to horizontally scroll to understand the core tables and charts
- Improve the visual hierarchy so the app feels trustworthy and professional
- Preserve the app's yield-scanning purpose while positioning it as a serious DeFi analytics product

## Product positioning
This should feel like:
- a clean DeFi analytics dashboard
- a companion tool for comparing and filtering yield opportunities quickly
- something a user could open beside DeFiLlama for faster decision-making
- a product that could later evolve into its own recognizable brand

## Brand direction
Create a stronger product identity and use one selected name consistently across:
- page title
- hero/header section
- sidebar branding
- export/download labels
- future repo/docs references

Candidate naming should feel crypto-native, memorable, and slightly playful or sharp without sounding amateur.
Examples of naming energy only: Furu, Del Mule, Frog CLI.
Do not copy those directly unless explicitly selected.

## UI and UX requirements
### Typography
- All text must be clearly legible against a dark UI
- Remove low-contrast font colors, especially any blue-on-dark-blue combinations that are hard to read
- Use simple, clean, modern font styling
- Establish strong hierarchy across title, section headings, metrics, labels, and table text

### Layout
- Use Streamlit wide layout
- Add more spacing and padding between major sections
- Avoid cramped containers and overly compressed columns
- Use full-width sections where appropriate
- Make the dashboard feel breathable and intentional

### Tables and charts
- Fix the sideways scrolling problem for the main opportunities table and chart sections
- Prioritize a compact set of essential columns in the main table
- Move secondary fields into drilldowns, expanders, tabs, or detail views
- Charts should fit the content width cleanly and feel visually integrated
- Main tables should use container width and better column selection so the important data is visible immediately

### Visual polish
- Add a premium dashboard feel through:
  - better cards
  - cleaner section separation
  - subtle gradients or panel styling
  - improved metric presentation
  - stronger alignment and consistency
- Keep the design restrained and professional rather than flashy

## Functional upgrades
### Live data
- Pull live DeFi yield data from the available DeFiLlama yield endpoint
- Cache responses appropriately for Streamlit performance
- Gracefully handle API failures with a fallback state

### Analytics structure
Include at minimum:
- summary KPI cards
- filtered opportunities table
- chain or protocol overview chart
- single-pool or single-protocol drilldown area
- pool links for deeper external inspection

### Risk layer
Add an initial protocol/pool risk heuristic that is explicitly labeled as a heuristic, not a guarantee.
Use simple observable fields such as:
- APY extremity
- TVL size
- strategy/exposure type
- stablecoin vs non-stablecoin nature

Return:
- numeric risk score
- categorical risk band

## Product quality standard
The result should feel like:
- a real MVP dashboard
- something that can be shown publicly without feeling rough
- a meaningful upgrade from a developer utility into a presentable analytics product

## Deliverables
Return updated Streamlit code that includes:
- improved branding
- improved dark-theme readability
- wider, cleaner layout
- reduced horizontal scrolling
- live DeFiLlama integration
- pool links
- risk scoring heuristic
- polished KPI cards
- improved table and chart presentation

Also provide:
- 5 to 10 brand name candidates
- the recommended final name
- a short explanation of why it best fits the product
