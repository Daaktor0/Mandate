# Designer Prompt — Mandate Brand Kit and Product Design System

> Give this prompt to the designer (human or AI) producing Mandate's brand identity and UI/UX system. The product spec deferred "final visual design" (doc 16); this brief fills that gap. `product-specification/docs/03-user-journey-and-screen-spec.md` and `product-specification/templates/MANDATE-BRIEF-TEMPLATE.md` are required reading.

---

You are the brand and product designer for **Mandate**, a legal-tech product for Indian corporate transaction lawyers (partners and associates at law firms, plus independent practitioners). Mandate turns a company website or legal name into a **Mandate Brief** — a concise, source-backed, two-page transaction-preparation report with a tailored kickoff-call question set.

Positioning: *transaction preparation tool* — "public-information intelligence for better transaction kickoff calls." Tagline: **"Know the company before the first call."** Mandate is explicitly **not** an AI lawyer, a due-diligence replacement, a legal-opinion engine or a data room, and the design must never imply it is.

## Brand personality

Precise, calm, senior, trustworthy — the confidence of a well-prepared associate handing a partner a flawless brief. Closer to a premium professional publication than an AI startup. **Avoid:** robot/agent/chat imagery, sparkle-AI clichés, "tokens/credits" gamification, gavel-and-scales legal clichés, dark-pattern urgency, and anything implying exhaustive legal coverage.

## Deliverables

### 1. Logo suite
Wordmark ("Mandate") + a standalone mark. Must survive: 16 px favicon, browser tab, email header, PDF report header at print resolution, and monochrome (report/letterhead contexts). Provide: full-colour, mono black, mono reverse; clear-space and minimum-size rules; misuse examples. Formats: SVG (source of truth) + PNG exports + favicon/OG set. Also a lockup treatment for "Mandate Brief" as a *report title style* (not a second logo) — the product is Mandate; Mandate Brief is what it produces.

### 2. Colour system
Semantic token palette (not just swatches): brand primary, surfaces, text hierarchy, borders, focus, and **functional colour sets** for:
- the ten dashboard statuses (Entity confirmation required, Clarification required, Queued, Researching, Verifying, Drafting, Preparing Mandate Brief, Ready, Failed — entitlement restored, Deleted);
- the four entity-confidence labels (Strong match / Probable match / Ambiguous / Insufficient evidence);
- the six claim-type labels (verified fact, company claim, third-party report, inference, conflict, not publicly available) — these carry epistemic meaning and must be distinguishable without colour alone (pair with icon/shape/text).
Every text/background pair must pass **WCAG 2.1 AA** (NFR-06). Light theme is primary; dark theme optional but tokens should be structured to allow it.

### 3. Typography
Two roles: a UI typeface and a **document typeface for the Mandate Brief** (screen + PDF). Hard constraints: licences must permit self-hosted web embedding **and PDF embedding** (the renderer embeds fonts server-side; no CDN loading); clean ₹ glyph; strong tabular numerals (CINs like `U12345MH2020PTC123456`, dates, figures); comfortable at dense two-page print sizes (~9.5–11 pt) and readable in long tables. Provide the full scale (sizes/weights/line-heights) for UI and for print.

### 4. UI component system
Design tokens (colour, type, spacing, radius, elevation) exportable as CSS variables / Tailwind config, plus components: buttons, inputs, tabs (Website / Legal name intake), checkbox (the mandatory "I confirm that I am not submitting confidential information" must be prominent, not fine print), **entity-candidate cards** (legal name, CIN, status, registered office, domain relationship, evidence snippets, confidence badge, actions: "This is the company / None of these / Enter legal name / Add CIN"), **generation-progress checklist** (the seven stages as a truthful checklist with timestamps — no percentage bars, no fake spinners), the **Mandate Brief editor** (paginated document canvas + source/confidence side panel + version selector + save/regenerate/issue/letterhead/download actions + inline warning style for unsupported user-added text), letterhead upload with margin/continuation preview, dashboards, empty states, error states (including "Failed — entitlement restored", which should feel like kept trust, not breakage), modals, toasts.

### 5. Screen designs
High-fidelity for the doc-03 flows: landing page; sign-in (Google/Microsoft); first-login profile; dashboard; new Mandate Brief (both tabs); entity confirmation; clarification (mandatory client-role question with its "why this matters" explainer); generation progress; brief editor; letterhead; download (version, entity/CIN, research date, annex toggle, disclaimer); issue reporting; account/payments incl. entitlement display (available vs reserved) and pricing (₹999 single / ₹3,499 five / ₹5,999 ten — presented as Mandate Brief packs, never tokens). Landing must include: positioning, transaction-preparation promise, public-information-only explanation, sample Mandate Brief preview, three-step flow, pricing, login buttons, and the not-legal-advice statement; it must avoid agent diagrams and coverage claims.

### 6. Mandate Brief document design
The flagship artefact — design it like a lawyer's work product. A4, default two pages (range 1–4), following the template structure: header block (legal name, brand, CIN, type/status, registered office, prepared-for, research date), executive snapshot (≤6 bullets), sections 1–6, prioritised kickoff-question list, source annex (separate, outside the page count), verbatim disclaimer. Requirements: neutral professional tone; claim-type labelling integrated elegantly (not noisy badges on every line); **letterhead compatibility** — users stamp their firm's letterhead as background/header, so define safe margins and a header zone that tolerates it; no raw URLs in the body (sources live in the annex); print-deterministic layout (no elements that reflow unpredictably). Deliver as a styled specimen with real-looking placeholder content.

### 7. Voice and naming sheet
One page: **Mandate** = product, **Mandate Brief** = report (never "brief" alone in headings, never "MandateBrief"); sample phrasing ("Create a Mandate Brief", "Your Mandate Brief is ready"); "Matters for attention" is a fixed heading; uncertainty phrasing patterns ("the company states…", "not publicly established"); banned vocabulary (tokens, AI lawyer, due diligence replacement, guaranteed/complete coverage).

## Handoff format

Figma file (or equivalent) with published components and styles; token export (JSON + CSS variables); logo SVG/PNG package; font files with licence documentation proving web + PDF embedding rights; the Mandate Brief specimen as PDF; a short usage guide. Name layers/components to match the spec's terms (entity candidate, claim type, matters for attention) so engineering maps them 1:1.

## Acceptance checklist

- [ ] AA contrast verified for every token pair; statuses/labels distinguishable without colour alone
- [ ] Logo legible at 16 px and in mono on a letterhead-style page
- [ ] Fonts licensed for self-hosted web + PDF embedding; ₹ and tabular numerals verified
- [ ] Progress UI contains no percentages or fake motion
- [ ] Mandate Brief specimen fits the two-page default with the template's full structure and disclaimer
- [ ] Landing page includes all required elements and none of the banned ones
- [ ] All naming matches the voice sheet
