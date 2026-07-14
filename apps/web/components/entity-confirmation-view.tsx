"use client";

import type { EntityCandidate } from "@mandate/shared-schemas";
import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

type CandidateState =
  | "draft"
  | "resolving_entity"
  | "awaiting_entity_confirmation"
  | "preliminary_research"
  | "failed_no_charge";

type CandidateEnvelope = Readonly<{
  state: CandidateState;
  candidates: EntityCandidate[];
}>;

type ErrorEnvelope = Readonly<{
  error?: Readonly<{ message?: string }>;
}>;

const CONFIDENCE_LABELS: Record<EntityCandidate["confidenceLabel"], string> = {
  strong_match: "Strong match",
  probable_match: "Probable match",
  ambiguous: "Ambiguous",
  insufficient_evidence: "Insufficient evidence",
};

function sourceHost(sourceUrl: string): string {
  try {
    return new URL(sourceUrl).hostname;
  } catch {
    return "Public source";
  }
}

async function responseMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as ErrorEnvelope;
    return body.error?.message ?? "The request could not be completed.";
  } catch {
    return "The request could not be completed.";
  }
}

export function EntityConfirmationView({
  reportRequestId,
  initialState,
  initialCandidates,
}: Readonly<{
  reportRequestId: string;
  initialState: CandidateState;
  initialCandidates: EntityCandidate[];
}>) {
  const [state, setState] = useState<CandidateState>(initialState);
  const [candidates, setCandidates] =
    useState<EntityCandidate[]>(initialCandidates);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(
    null,
  );
  const [relatedEntityIds, setRelatedEntityIds] = useState<string[]>([]);
  const [showRefine, setShowRefine] = useState(initialState === "draft");
  const [showRelated, setShowRelated] = useState(false);
  const [legalName, setLegalName] = useState("");
  const [cin, setCin] = useState("");
  const [guidance, setGuidance] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const selectedCandidate = useMemo(
    () =>
      candidates.find(
        (candidate) => candidate.candidateId === selectedCandidateId,
      ),
    [candidates, selectedCandidateId],
  );
  const relatedSuggestions = useMemo(
    () =>
      candidates.filter(
        (candidate) =>
          candidate.entityId !== undefined &&
          candidate.entityId !== null &&
          candidate.relatedEntityReason !== undefined &&
          candidate.relatedEntityReason !== null &&
          candidate.relatedEntityReason.trim() !== "" &&
          candidate.candidateId !== selectedCandidateId,
      ),
    [candidates, selectedCandidateId],
  );

  useEffect(() => {
    if (state !== "resolving_entity") {
      return;
    }
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function poll(): Promise<void> {
      try {
        const response = await fetch(
          `/api/report-requests/${reportRequestId}/entity-candidates`,
          { cache: "no-store" },
        );
        if (!response.ok) {
          throw new Error(await responseMessage(response));
        }
        const body = (await response.json()) as CandidateEnvelope;
        if (!active) {
          return;
        }
        setState(body.state);
        setCandidates(body.candidates);
        setError(null);
        if (body.state === "resolving_entity") {
          timer = setTimeout(() => void poll(), 2500);
        }
      } catch (pollError) {
        if (!active) {
          return;
        }
        setError(
          pollError instanceof Error
            ? pollError.message
            : "Entity resolution could not be refreshed.",
        );
        timer = setTimeout(() => void poll(), 5000);
      }
    }

    void poll();
    return () => {
      active = false;
      if (timer !== undefined) {
        clearTimeout(timer);
      }
    };
  }, [reportRequestId, state]);

  async function submitDecision(
    decision: Record<string, unknown>,
  ): Promise<void> {
    setPending(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/report-requests/${reportRequestId}/confirm-entity`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": crypto.randomUUID(),
          },
          body: JSON.stringify(decision),
        },
      );
      if (!response.ok) {
        throw new Error(await responseMessage(response));
      }
      const body = (await response.json()) as {
        state: CandidateState;
        guidance: string | null;
      };
      setState(body.state);
      setGuidance(body.guidance);
      if (body.state === "draft") {
        setCandidates([]);
        setSelectedCandidateId(null);
        setRelatedEntityIds([]);
        setShowRefine(true);
      } else if (body.state === "resolving_entity") {
        setCandidates([]);
        setSelectedCandidateId(null);
        setRelatedEntityIds([]);
        setShowRefine(false);
      }
    } catch (submissionError) {
      setError(
        submissionError instanceof Error
          ? submissionError.message
          : "The entity decision could not be saved.",
      );
    } finally {
      setPending(false);
    }
  }

  function selectPrimary(candidate: EntityCandidate): void {
    setSelectedCandidateId(candidate.candidateId);
    if (candidate.entityId !== undefined && candidate.entityId !== null) {
      setRelatedEntityIds((current) =>
        current.filter((entityId) => entityId !== candidate.entityId),
      );
    }
  }

  function toggleRelated(entityId: string): void {
    setRelatedEntityIds((current) => {
      if (current.includes(entityId)) {
        return current.filter((value) => value !== entityId);
      }
      if (current.length >= 2) {
        setError(
          "A Mandate Brief can include at most two material related entities.",
        );
        return current;
      }
      setError(null);
      return [...current, entityId];
    });
  }

  function refine(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const normalisedName = legalName.trim();
    const normalisedCin = cin.trim().toUpperCase();
    if (normalisedName === "" && normalisedCin === "") {
      setError("Enter a registered legal name or CIN before resolving again.");
      return;
    }
    void submitDecision({
      action: "refine",
      ...(normalisedName === "" ? {} : { legalName: normalisedName }),
      ...(normalisedCin === "" ? {} : { cin: normalisedCin }),
    });
  }

  if (state === "preliminary_research") {
    return (
      <main className="confirmation-shell">
        <section className="confirmation-panel confirmation-complete">
          <p className="eyebrow">Entity confirmed</p>
          <h1>{selectedCandidate?.legalName ?? "Legal entity confirmed"}</h1>
          <p>
            Mandate has recorded the primary legal entity. Preliminary
            public-source research is the next stage; no report entitlement has
            been reserved yet.
          </p>
        </section>
      </main>
    );
  }

  return (
    <main className="confirmation-shell">
      <header className="confirmation-header">
        <div>
          <p className="eyebrow">Create Mandate Brief · Step 2</p>
          <h1>Confirm the legal entity</h1>
          <p className="lede">
            Brands, websites and legal entities often differ. Review the public
            evidence and choose the company the Mandate Brief should cover.
          </p>
        </div>
        <aside className="no-charge-note">
          <strong>No entitlement is reserved here.</strong>
          <span>Research continues only after your explicit confirmation.</span>
        </aside>
      </header>

      <div className="status-region" aria-live="polite">
        {state === "resolving_entity" ? (
          <p className="status-card">Identifying legal-entity candidates…</p>
        ) : null}
        {state === "failed_no_charge" ? (
          <p className="status-card status-warning">
            No reliable candidate was found. Add the registered legal name or
            CIN below. You have not been charged.
          </p>
        ) : null}
        {guidance !== null ? <p className="status-card">{guidance}</p> : null}
        {error !== null ? (
          <p className="status-card status-error">{error}</p>
        ) : null}
      </div>

      {state === "awaiting_entity_confirmation" ? (
        <section
          className="candidate-list"
          aria-label="Legal entity candidates"
        >
          {candidates.map((candidate) => (
            <article
              className={`candidate-card ${
                selectedCandidateId === candidate.candidateId
                  ? "candidate-selected"
                  : ""
              }`}
              key={candidate.candidateId}
            >
              <label className="candidate-choice">
                <input
                  type="radio"
                  name="primary-entity"
                  checked={selectedCandidateId === candidate.candidateId}
                  onChange={() => selectPrimary(candidate)}
                />
                <span>
                  <span className="candidate-title-row">
                    <strong>{candidate.legalName}</strong>
                    <span
                      className={`confidence confidence-${candidate.confidenceLabel}`}
                    >
                      {CONFIDENCE_LABELS[candidate.confidenceLabel]}
                    </span>
                  </span>
                  <span className="candidate-score">
                    Confidence score {candidate.confidenceScore}/100
                  </span>
                </span>
              </label>

              <dl className="candidate-facts">
                <div>
                  <dt>CIN</dt>
                  <dd>
                    {candidate.cin ?? "Not found in the available sources"}
                  </dd>
                </div>
                <div>
                  <dt>Status</dt>
                  <dd>{candidate.status ?? "Not confirmed"}</dd>
                </div>
                <div>
                  <dt>Registered office</dt>
                  <dd>
                    {candidate.registeredOfficeSummary ??
                      candidate.registeredOfficeState ??
                      "Not confirmed"}
                  </dd>
                </div>
                <div>
                  <dt>Domain relationship</dt>
                  <dd>
                    {candidate.primaryDomain === undefined ||
                    candidate.primaryDomain === null
                      ? "No verified domain linkage"
                      : candidate.primaryDomain}
                  </dd>
                </div>
              </dl>

              <div className="evidence-block">
                <h2>Why this candidate appeared</h2>
                <ul>
                  {candidate.evidenceSnippets.slice(0, 4).map((evidence) => (
                    <li key={evidence.evidenceId}>
                      <span>{evidence.snippet}</span>
                      <small>
                        {evidence.companyControlled
                          ? "Company-controlled"
                          : "Public data"}
                        {" · "}
                        {sourceHost(evidence.sourceUrl)}
                      </small>
                    </li>
                  ))}
                </ul>
              </div>

              {candidate.conflicts.length > 0 ? (
                <div className="conflict-block">
                  <h2>Conflicts or limitations</h2>
                  <ul>
                    {candidate.conflicts.map((conflict) => (
                      <li key={conflict}>{conflict}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </article>
          ))}

          <div className="confirmation-actions">
            <button
              className="primary-action"
              type="button"
              disabled={selectedCandidateId === null || pending}
              onClick={() =>
                void submitDecision({
                  action: "confirm",
                  candidateId: selectedCandidateId,
                  relatedEntityIds,
                })
              }
            >
              {pending ? "Saving…" : "This is the company"}
            </button>
            <button
              className="secondary-action"
              type="button"
              disabled={pending}
              onClick={() => void submitDecision({ action: "none_of_these" })}
            >
              None of these
            </button>
            <button
              className="text-action"
              type="button"
              onClick={() => setShowRefine((current) => !current)}
            >
              Enter legal name or add CIN
            </button>
            {relatedSuggestions.length > 0 ? (
              <button
                className="text-action"
                type="button"
                onClick={() => setShowRelated((current) => !current)}
              >
                Clarify multiple entities
              </button>
            ) : null}
          </div>

          {showRelated && relatedSuggestions.length > 0 ? (
            <fieldset className="related-scope">
              <legend>Material related entities (optional, maximum two)</legend>
              <p>
                Include another entity only when it materially owns IP, employs
                staff, holds licences, owns assets or premises, contracts,
                receives revenue, or controls the primary entity.
              </p>
              {relatedSuggestions.map((candidate) => (
                <label key={candidate.candidateId}>
                  <input
                    type="checkbox"
                    checked={relatedEntityIds.includes(
                      candidate.entityId as string,
                    )}
                    onChange={() => toggleRelated(candidate.entityId as string)}
                  />
                  <span>
                    <strong>{candidate.legalName}</strong>
                    <small>{candidate.relatedEntityReason}</small>
                  </span>
                </label>
              ))}
            </fieldset>
          ) : null}
        </section>
      ) : null}

      {showRefine || state === "failed_no_charge" || state === "draft" ? (
        <form className="refine-panel" onSubmit={refine}>
          <div>
            <p className="eyebrow">Refine the search</p>
            <h2>Use public identity details only</h2>
            <p>
              Enter the registered legal name, the CIN, or both. Do not enter
              mandate facts, transaction details or confidential information.
            </p>
          </div>
          <label>
            Registered legal name
            <input
              type="text"
              maxLength={300}
              value={legalName}
              onChange={(event) => setLegalName(event.target.value)}
              placeholder="Example Private Limited"
              autoComplete="organization"
            />
          </label>
          <label>
            CIN
            <input
              type="text"
              maxLength={21}
              value={cin}
              onChange={(event) => setCin(event.target.value.toUpperCase())}
              placeholder="U12345MH2024PTC123456"
              spellCheck={false}
            />
          </label>
          <button className="primary-action" type="submit" disabled={pending}>
            {pending ? "Resolving…" : "Resolve again"}
          </button>
        </form>
      ) : null}
    </main>
  );
}
