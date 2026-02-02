# comparadordeseguro.es — MVP+ Product Requirements (draft)

## TL;DR
Create a Spanish insurance comparison platform that guides users from quote input → clear options → lead submission → manager follow‑up. MVP focuses on 1–2 verticals (auto + home or auto + health), with a strong compliance foundation (RGPD/LOPDGDD, cookies, LSSI‑CE), SEO groundwork, and a minimal CRM funnel.

---

## 1) Product goals & success metrics

### Goals
1. User provides data.
2. User sees understandable price/coverage options.
3. User submits a lead or starts purchase.
4. Manager/partner closes the sale.

### MVP KPIs
- Calculator → lead conversion.
- CPL/CPA by channel (SEO/PPC/partners).
- Share of leads with valid contact info.
- Quote speed (TTFB/INP) and stability.
- SEO indexation, organic visibility, and growth on commercial clusters.

---

## 2) MVP scope & scaling

### Recommended MVP verticals
- **Seguro de coche (auto)**
- **Seguro de hogar (home)**
- *(Optional instead of home)* **Seguro de salud (health)**

Rationale: auto/home are simpler to start. Health should avoid sensitive data on MVP.

### Phase 2 (post‑MVP)
- Life, death, travel, pets, rental, community, etc.

---

## 3) Roles & access

- **Guest**: browse, calculator, compare, lead form.
- **User (optional)**: account, saved quotes, documents.
- **Operator/manager**: lead processing, statuses, notes, outreach.
- **Admin**: products/providers, content, SEO pages, access, integrations, logs.
- **Partner (optional)**: access to own leads and reports.

---

## 4) User flows

### 4.1 Main MVP flow
1. Landing → pick insurance type
2. Multi‑step calculator
3. Results screen (offer cards)
4. Compare 2–4 offers (coverage matrix)
5. CTA: “Get a call / Apply” (lead form) or “Send via WhatsApp/Email”
6. Thank‑you page + conversion tracking

### 4.2 Alternate flows
- “Quick lead” without results (PPC‑friendly)
- “More data required” path if calculation needs extra inputs

---

## 5) Functional requirements

### 5.1 Calculator (forms)
General:
- Multi‑step, progress indicator, localStorage autosave
- Validation: ES phone, email, required fields
- Tooltips/glossary (franchise, terceros, todo riesgo, etc.)
- Separate consent checkboxes: privacy, cookies, marketing

**Auto (minimal):**
- Vehicle: brand/model/year/version/fuel (use catalogs)
- Use: personal/work, mileage ranges
- Driver: age, experience, incidents/accidents (categories)
- Postal code (pricing)
- Desired coverage: terceros / terceros ampliado / todo riesgo; franchise optional

**Home (minimal):**
- Property type, size (ranges), address/CP, year built (range)
- Owner/tenant
- Coverage: content/structure, liability, water damage, etc.

**Health (if MVP):**
- Age, CP, plan type (with/without copay), hospitalization, dental options
- **Avoid medical history/diagnosis collection** at MVP

### 5.2 Results & comparison
- Offer card: price/month and price/year, franchise, badges, 5–8 key coverages
- “Details” modal/page with full coverages, exclusions, documents (PDF)
- Comparison matrix: rows as coverages, columns as offers
- Filters: price, franchise, coverage type, provider, “online purchase”
- Sorting: price, value score, popularity

### 5.3 Lead management (internal CRM)
- Lead list: date, product type, status, source, UTM, offer price, contact
- Lead detail: form data, selected offers, communication history
- Status flow: New → Contacted → Qualified → Offer sent → Won/Lost
- Assignment, notes, tags, tasks
- CSV export; webhook to external CRM (optional)

### 5.4 Content & SEO
- SEO landing clusters (examples):
  - `/seguros/coche/terceros/`
  - `/seguros/hogar/barato/`
  - `/seguros/salud/sin-copago/`
- CMS control: titles, copy, FAQ, trust blocks, coverage table data
- Internal linking, breadcrumbs, canonical, sitemap.xml, robots.txt
- Blog/guides: “Cómo elegir…”, “Qué cubre…”, “Diferencias entre…”

---

## 6) Pricing/offer integrations

### A) Lead‑gen MVP (fastest)
- Do not calculate real‑time tariffs.
- Show indicative packages or sample offers.
- Manager/partner provides final quote.

### B) Aggregator API pricing
- API integration with broker/aggregator to return quotes.
- Requires mapping coverages and error handling.

### C) Direct insurer integrations
- Highest effort; phase 2–3.

**Disclosure:** clarify broker/agent/lead‑gen status on the site.

---

## 7) Legal & compliance (Spain/EU)

Minimum requirements:
- **Privacy policy** (RGPD + LOPDGDD)
- **Cookie banner** + consent management center
- **Aviso legal / LSSI‑CE** with company info and terms
- Separate consents: lead contact vs marketing
- Consent logs with timestamp, text version, and source

**Important:** avoid collecting sensitive data (health) on MVP.

---

## 8) Non‑functional requirements

- Performance: green LCP/INP on mobile for SEO pages
- Accessibility: basic WCAG (contrast, focus, aria labels)
- Security: HTTPS + HSTS, rate limiting, optional captcha, 2FA for admin
- Reliability: error monitoring (e.g., Sentry), integration logs, alerts

---

## 9) Recommended stack

**Frontend**
- Next.js (App Router), TypeScript
- Tailwind + component library
- i18n: ES required, EN/RU optional

**Backend**
- Node.js (NestJS or Next API routes for MVP)
- PostgreSQL
- Optional queue: Redis/BullMQ for integrations

**Infra**
- Vercel/Render/Fly.io (MVP)
- S3‑compatible storage
- GitHub Actions CI/CD

---

## 10) Conceptual data model

- User
- Lead
- QuoteRequest
- Offer
- Provider
- Coverage
- OfferCoverage
- ConsentLog
- AuditLog

---

## 11) Admin panel minimum

- CRUD providers
- CRUD offers/templates (if no pricing API)
- Lead viewer + statuses + assignment
- SEO page management (title, meta, text, FAQ)
- Integration and error logs

---

## 12) Analytics & attribution

- GA4 + GTM
- Events:
  - `start_quote`, `step_complete`, `view_results`, `compare_add`, `lead_submit`
- Persist UTM at session level and attach to Lead
- Optional server‑side conversions (phase 2)

---

## 13) UX principles

- Honest display: price + coverage + rationale
- Low cognitive load: 1 question per screen (mobile)
- Trust: reviews, “how we earn,” partners, legal status
- Clear next steps after lead submission

---

## 14) Release plan

### MVP blocks
1. Marketing pages + SEO skeleton
2. Calculator + data save + results (sample offers acceptable)
3. Lead form + CRM admin
4. Compliance: privacy/cookies/aviso legal + consent logs

### Next
- Quote APIs
- User account
- Partner roles + reporting
- More verticals

---

## 15) Cursor implementation protocol (team rules)

### 15.1 Repo and standards
- Single Next.js repo or monorepo
- Strict TypeScript, ESLint, Prettier, husky pre‑commit
- Conventional Commits

### 15.2 Cursor project rules
- Use only TS/TSX
- Avoid extra dependencies unless necessary
- Central form engine + zod schemas
- Migrations + prisma/drizzle schema + seed
- No hardcoded copy: use i18n dictionaries
- Add unit tests for offer mapping/validators

### 15.3 Code generation sequence
1. Pages and routing
2. Form engine (steps + schema)
3. API for lead_submit + validation + rate limiting
4. Admin auth + RBAC
5. Analytics events
6. Legal pages + consent logging

---

## 16) Engineering note

A core long‑term challenge: normalizing coverage data across providers. Similar coverage names and different conditions require careful mapping and explainable comparison logic.
