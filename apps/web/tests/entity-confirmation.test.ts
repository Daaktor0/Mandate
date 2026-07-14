import type { EntityCandidate } from "@mandate/shared-schemas";
import { describe, expect, it } from "vitest";

import {
  handleConfirmEntity,
  handleGetEntityCandidates,
} from "../lib/entity-confirmation/handler";
import type {
  CandidateListResult,
  ConfirmEntityCommand,
  ConfirmEntityResult,
  EntityConfirmationDependencies,
} from "../lib/entity-confirmation/types";

const USER_ID = "11111111-1111-4111-8111-111111111111";
const REQUEST_ID = "22222222-2222-4222-8222-222222222222";
const CANDIDATE_ID = "33333333-3333-4333-8333-333333333333";
const ENTITY_ID = "44444444-4444-4444-8444-444444444444";
const TRACE_ID = "trace-confirmation-test";

const CANDIDATE: EntityCandidate = {
  schemaVersion: 1,
  candidateId: CANDIDATE_ID,
  entityId: ENTITY_ID,
  legalName: "Example Private Limited",
  formerNames: [],
  cin: "U62099MH2024PTC123456",
  companyType: "private",
  listedStatus: "unlisted",
  status: "Active",
  registeredOfficeState: "Maharashtra",
  registeredOfficeSummary: "Mumbai, Maharashtra",
  primaryDomain: "example.com",
  brandNames: [],
  confidenceScore: 85,
  confidenceLabel: "strong_match",
  evidenceSnippets: [
    {
      evidenceId: "55555555-5555-4555-8555-555555555555",
      snippet: "The public company-data record matches the supplied CIN.",
      sourceUrl: "https://fixtures.mandate.local/company-data/smoke",
      companyControlled: false,
    },
  ],
  conflicts: [],
};

function post(body: unknown, headers: Record<string, string> = {}): Request {
  return new Request(
    `https://mandate.example/api/report-requests/${REQUEST_ID}/confirm-entity`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify(body),
    },
  );
}

function harness(
  options: {
    candidates?: CandidateListResult;
    confirmation?: ConfirmEntityResult;
  } = {},
) {
  const commands: ConfirmEntityCommand[] = [];
  const dependencies: EntityConfirmationDependencies = {
    async authenticate() {
      return { id: USER_ID };
    },
    async loadCandidates() {
      return (
        options.candidates ?? {
          kind: "found",
          state: "awaiting_entity_confirmation",
          candidates: [CANDIDATE],
        }
      );
    },
    async confirmEntity(command) {
      commands.push(command);
      return (
        options.confirmation ?? {
          kind: "accepted",
          response: {
            state: "preliminary_research",
            confirmedEntityId: ENTITY_ID,
            relatedEntityIds: [],
            guidance: null,
          },
        }
      );
    },
  };
  return { commands, dependencies };
}

async function errorCode(response: Response): Promise<string> {
  const body = (await response.json()) as { error: { code: string } };
  return body.error.code;
}

describe("entity-confirmation candidate API", () => {
  it("ENTITY-03 returns ordered evidence-bearing candidates", async () => {
    const test = harness();
    const response = await handleGetEntityCandidates(
      REQUEST_ID,
      test.dependencies,
      TRACE_ID,
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      state: "awaiting_entity_confirmation",
      candidates: [CANDIDATE],
    });
    expect(response.headers.get("X-Trace-Id")).toBe(TRACE_ID);
  });

  it("ENTITY-03 exposes no candidates while resolution is running", async () => {
    const test = harness({
      candidates: {
        kind: "found",
        state: "resolving_entity",
        candidates: [],
      },
    });
    const response = await handleGetEntityCandidates(
      REQUEST_ID,
      test.dependencies,
      TRACE_ID,
    );

    expect(await response.json()).toEqual({
      state: "resolving_entity",
      candidates: [],
    });
  });
});

describe("entity-confirmation decision API", () => {
  it("ENTITY-03 records an explicit primary candidate and no entitlement data", async () => {
    const test = harness();
    const response = await handleConfirmEntity(
      post(
        {
          action: "confirm",
          candidateId: CANDIDATE_ID,
          relatedEntityIds: [],
        },
        { "Idempotency-Key": "confirm-entity-001" },
      ),
      REQUEST_ID,
      test.dependencies,
      TRACE_ID,
    );

    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({
      state: "preliminary_research",
      confirmedEntityId: ENTITY_ID,
      relatedEntityIds: [],
      guidance: null,
    });
    expect(test.commands).toEqual([
      {
        reportRequestId: REQUEST_ID,
        decision: {
          action: "confirm",
          candidateId: CANDIDATE_ID,
          relatedEntityIds: [],
        },
        idempotencyKey: "confirm-entity-001",
        traceId: TRACE_ID,
      },
    ]);
    expect(test.commands[0]).not.toHaveProperty("entitlement");
  });

  it("ENTITY-04 accepts none-of-these without identifiers or narrative", async () => {
    const test = harness({
      confirmation: {
        kind: "accepted",
        response: {
          state: "draft",
          confirmedEntityId: null,
          relatedEntityIds: [],
          guidance: "Enter the registered legal name or add the CIN.",
        },
      },
    });
    const response = await handleConfirmEntity(
      post({ action: "none_of_these" }),
      REQUEST_ID,
      test.dependencies,
      TRACE_ID,
    );

    expect(response.status).toBe(200);
    expect(test.commands[0]?.decision).toEqual({
      action: "none_of_these",
      relatedEntityIds: [],
    });
  });

  it("ENTITY-04 requires a legal name or CIN before refine", async () => {
    const test = harness();
    const response = await handleConfirmEntity(
      post({ action: "refine", state: "Maharashtra" }),
      REQUEST_ID,
      test.dependencies,
      TRACE_ID,
    );

    expect(response.status).toBe(422);
    expect(await errorCode(response)).toBe("INVALID_REQUEST");
    expect(test.commands).toHaveLength(0);
  });

  it("ENTITY-07 rejects duplicate or oversized related-entity scope", async () => {
    const test = harness();
    const response = await handleConfirmEntity(
      post({
        action: "confirm",
        candidateId: CANDIDATE_ID,
        relatedEntityIds: [ENTITY_ID, ENTITY_ID],
      }),
      REQUEST_ID,
      test.dependencies,
      TRACE_ID,
    );

    expect(response.status).toBe(422);
    expect(await errorCode(response)).toBe("INVALID_REQUEST");
    expect(test.commands).toHaveLength(0);
  });

  it("INTAKE-04 rejects confirmation narrative fields", async () => {
    const test = harness();
    const response = await handleConfirmEntity(
      post({
        action: "none_of_these",
        description: "Confidential mandate facts",
      }),
      REQUEST_ID,
      test.dependencies,
      TRACE_ID,
    );

    expect(response.status).toBe(422);
    expect(test.commands).toHaveLength(0);
  });

  it.each([
    [{ kind: "not_found" } as const, 404, "REQUEST_NOT_FOUND"],
    [{ kind: "state_conflict" } as const, 409, "INVALID_REQUEST_STATE"],
    [{ kind: "idempotency_conflict" } as const, 409, "IDEMPOTENCY_CONFLICT"],
    [{ kind: "invalid" } as const, 422, "INVALID_REQUEST"],
    [
      { kind: "rate_limited", retryAfterSeconds: 3600 } as const,
      429,
      "RATE_LIMITED",
    ],
  ])("maps stable persistence outcome %j", async (result, status, code) => {
    const test = harness({ confirmation: result });
    const response = await handleConfirmEntity(
      post({ action: "none_of_these" }),
      REQUEST_ID,
      test.dependencies,
      TRACE_ID,
    );

    expect(response.status).toBe(status);
    expect(await errorCode(response)).toBe(code);
  });

  it("SEC-01 rejects unauthenticated decisions before persistence", async () => {
    const dependencies: EntityConfirmationDependencies = {
      async authenticate() {
        return null;
      },
      async loadCandidates() {
        throw new Error("must not run");
      },
      async confirmEntity() {
        throw new Error("must not run");
      },
    };
    const response = await handleConfirmEntity(
      post({ action: "none_of_these" }),
      REQUEST_ID,
      dependencies,
      TRACE_ID,
    );

    expect(response.status).toBe(401);
    expect(await errorCode(response)).toBe("UNAUTHENTICATED");
  });
});
