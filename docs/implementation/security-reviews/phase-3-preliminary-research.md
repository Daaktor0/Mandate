# Phase 3 security review — preliminary research and clarification planner

**Scope:** the unpaid pre-B light task, bounded preliminary evidence inventory,
and deterministic clarification question planner.

| Threat | Control | Evidence |
|---|---|---|
| Research runs before entity confirmation | The request contract requires state=preliminary_research and a confirmed entity_id; the SQL loader joins the confirmed entity and the completion RPC locks the request state | PreliminaryResearchRequest; repository scope test; migration state checks |
| User identity or matter narrative reaches a provider | The provider context contains only confirmed public entity fields; user_id exists only for repository ownership lookup; no question or provider payload has account, firm, billing, letterhead or narrative fields | test_RESEARCH_01_light_task_persists_questions_after_confirmation; worker/web README boundaries |
| Fetched content bypasses admission | Every fetched page is converted through capture_page_candidate and admit_evidence; failures are discarded as bounded gaps and only admitted metadata is retained | test_RESEARCH_01_preliminary_runner_admits_bounded_evidence |
| A sparse result is presented as complete | Zero or one admitted source sets sparseData=true; the mandatory role question remains available and the later API can require sparse-data disclosure before generation | test_RESEARCH_01_preliminary_runner_keeps_sparse_result_reviewable; migration column |
| Optional questions become an intake burden | The planner emits optional questions only for explicit material signals and always emits exactly one mandatory role question | test_RESEARCH_02_06_optional_questions_follow_material_signals |
| Clarification solicits confidential content | Questions are generated from fixed templates, marked confidentialitySafe=true, and checked against sensitive-request terms; free-text answer screening remains a required next slice | test_RESEARCH_03_planner_rejects_unsafe_question_policy; generated ClarificationSet schema |
| A replay overwrites later state | complete_preliminary_research returns the existing clarification state when already awaiting clarification and rejects unrelated states; terminal failure is no-charge and idempotent | migration RPC |

The planner is deterministic and zero-spend. It does not claim lawyer review,
live-provider quality, or completion of the later answer-screening/API/UI
slice.
