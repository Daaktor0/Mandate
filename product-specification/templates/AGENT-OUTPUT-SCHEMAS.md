# Agent Output Schemas

Convert these illustrative contracts into strict Pydantic and TypeScript schemas. Validate every model output.

## Entity candidate

```json
{
  "legal_name": "Example Private Limited",
  "cin": "U12345MH2020PTC123456",
  "company_type": "private",
  "listed_status": "unlisted",
  "status": "active",
  "registered_office": {"state": "Maharashtra", "address_summary": "Mumbai"},
  "brand_names": ["Example"],
  "domain_relationship": "The privacy policy identifies Example Private Limited as operator.",
  "confidence_score": 91,
  "confidence_label": "strong_match",
  "evidence_ids": ["ev_1", "ev_2"],
  "conflicts": [],
  "requires_user_confirmation": true
}
```

## Evidence

```json
{
  "id": "ev_1",
  "url": "https://example.com/privacy",
  "canonical_url": "https://example.com/privacy",
  "title": "Privacy Policy",
  "publisher": "Example",
  "source_tier": 2,
  "publication_date": null,
  "accessed_at": "2026-07-13T10:00:00Z",
  "excerpt": "This website is operated by Example Private Limited...",
  "content_hash": "sha256:...",
  "entity_identifiers": {"legal_names": ["Example Private Limited"], "cin": "U12345MH2020PTC123456", "addresses": []},
  "company_controlled": true,
  "rendering": "static_html",
  "prompt_injection_suspected": false
}
```

## Claim

```json
{
  "id": "claim_1",
  "subject": "Example Private Limited",
  "predicate": "incorporation_date",
  "object": "2020-04-01",
  "display_text": "The company was incorporated on 1 April 2020.",
  "claim_type": "verified_fact",
  "evidence_ids": ["ev_2"],
  "period": null,
  "confidence": "high",
  "freshness": "current",
  "contradiction_group": null,
  "verifier_status": "approved",
  "report_sections": ["corporate"]
}
```

## Research plan

```json
{
  "confirmed_entity_id": "entity_uuid",
  "mandatory_clarifications": [{
    "id": "client_role",
    "question": "Who are you preparing for?",
    "reason": "The research is broad, but useful kickoff questions differ by side.",
    "options": ["company_promoter", "investor_acquirer", "seller_transferor", "other"]
  }],
  "agents": [{
    "type": "business",
    "priority": "high",
    "objectives": ["business_model", "locations", "employees", "assets_ip"],
    "search_budget": 8,
    "page_budget": 20
  }],
  "total_budget": {"max_searches": 45, "max_pages": 100, "max_frontier_calls": 4, "max_runtime_seconds": 1200}
}
```

## Agent finding

```json
{
  "agent_type": "business",
  "findings": [{
    "topic": "operating_locations",
    "claim_ids": ["claim_20"],
    "summary": "The company states it has offices in Mumbai and Bengaluru.",
    "status": "company_claim",
    "gaps": ["Complete premises footprint is not public."],
    "suggested_questions": ["Please identify all offices, warehouses, factories and other premises and whether each is owned or leased."]
  }],
  "coverage": {"complete": ["products", "business_model"], "partial": ["locations", "employees"], "unavailable": ["customer_concentration"]},
  "additional_research_recommended": false
}
```

## Contradiction

```json
{
  "topic": "employee_count",
  "claim_ids": ["claim_40", "claim_41"],
  "description": "The website states 500+ employees; a recent report states about 350.",
  "possible_explanation": "Different dates or group-wide versus entity-only headcount.",
  "severity": "medium",
  "resolution": "disclose_as_conflict",
  "kickoff_question": "Please confirm current headcount for the legal entity, including permanent, contract and factory workers."
}
```

## Kickoff question

```json
{
  "question": "Please identify all offices, factories, warehouses and other premises used by the company, and confirm whether each is owned or leased.",
  "category": "business_operations",
  "priority": 1,
  "client_roles": ["investor_acquirer", "company_promoter"],
  "basis": {"evidence_gap": "Public sources identify two offices but do not establish the complete footprint.", "claim_ids": ["claim_20"]},
  "confidentiality_safe": true
}
```

## Quality gate

```json
{
  "entity_consistent": true,
  "material_claims_with_evidence": 54,
  "material_claims_total": 54,
  "unsupported_numerical_claims": 0,
  "high_severity_conflicts_unresolved": 0,
  "main_page_count": 2,
  "question_count": 12,
  "source_annex_present": true,
  "prohibited_data_detected": false,
  "pdf_overflow": false,
  "passed": true,
  "blocking_reasons": []
}
```
