# 14 — Future Small-Model Training Roadmap

## Purpose

A smaller model may reduce cost, improve Mandate Brief consistency, support private deployment and reduce frontier dependence. It is not a shortcut to reliable web research.

## Good first tasks

- source classification;
- structured fact extraction;
- date/name/unit normalisation;
- duplicate/contradiction signals;
- evidence-to-field mapping;
- edit classification;
- approved-claim rewriting;
- standard-section first drafts;
- ranking verified question candidates.

## Keep stronger initially

Entity adjudication, open research planning, difficult regulation, multi-source conflicts, final high-risk synthesis and adverse entity matching.

## Training examples

Evidence → claim; claims → Mandate Brief section; system draft → lawyer edit; candidate questions → lawyer ranking; source → tier; claim pair → contradiction.

Public availability does not automatically grant training/licensing rights. Prefer derived schemas and owned/consented outputs over raw web dumps.

## Consent/anonymisation

Exclude identity, firm, letterhead, payments and confidential additions. Confirm consent, strip branding, classify edit reason, human-review corrections, track lineage and split train/test by company.

## Data readiness

Do not fine-tune on a handful of Mandate Briefs. Indicative minimum: several hundred approved section examples for a narrow task, preferably 1,000+ for robust drafting/extraction, stable schema/evaluation and measured prompting baseline.

## Methods

- **SFT:** style, extraction, Mandate Brief sections and question formatting.
- **DPO/preference tuning:** original vs lawyer-preferred wording and kept vs rejected questions.
- **RL/reward modelling:** not initially needed.

## Hugging Face workflow

Private dataset/model repositories, TRL for SFT/DPO, PEFT/LoRA or QLoRA, experiment monitoring, Hugging Face Jobs/cloud GPU, private Hub persistence, evaluation after checkpoints and a model card.

## Model selection

Choose later based on licence, structured output, context, Indian corporate/legal language, inference cost, quantisation, tooling and governance.

- 1–3B: extraction/classification, possible CPU deployment.
- 7–14B: stronger drafting, generally GPU for production.
- Larger: may undermine the cost/privacy objective.

## Deployment

Hostinger KVM 2 may run a very small quantised model slowly, but is not preferred for 7B+ production. Better options are a GPU cloud, Hugging Face endpoint, law-firm GPU or suitable managed regional GPU.

Hybrid design: small model handles extraction/formatting; frontier model handles hard/final work; confidence router escalates.

## Evaluation and cadence

Require exact field accuracy, low hallucination, provenance preservation, entity consistency, question quality, style, cost and latency. Begin in shadow mode. Release periodic curated dataset/model versions with reproducible configuration, held-out evaluation and rollback. No continuous training from unreviewed edits.

## Start milestone

Begin only after the paid MVP shows repetitive tasks, meaningful cost, enough consented data, a task where fine-tuning beats prompting and a suitable serving environment.
