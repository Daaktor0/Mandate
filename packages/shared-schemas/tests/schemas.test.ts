import { randomUUID } from "node:crypto";

import { describe, expect, it } from "vitest";

import {
  ConfirmEntityRequestSchema,
  ConfirmEntityResponseSchema,
  ClarificationSetSchema,
  CreateReportRequestResponseSchema,
  CreateReportRequestSchema,
  EvidenceSchema,
  JobMessageSchema,
} from "../typescript";

describe("RUN-05 shared-schema validation", () => {
  it("RESEARCH-04/07 keeps the mandatory clarification contract explainable and safe", () => {
    const clarificationSet = ClarificationSetSchema.parse({
      schemaVersion: 1,
      reportRequestId: randomUUID(),
      entityId: randomUUID(),
      questions: [
        {
          questionId: "client_role",
          code: "client_role",
          prompt: "Which role best describes you for this transaction?",
          reason: "Role changes the research emphasis.",
          mandatory: true,
          answerKind: "single_select",
          answerOptions: ["company_promoter", "investor_acquirer"],
          confidentialitySafe: true,
        },
      ],
      evidenceIds: [],
      sparseData: true,
      plannerVersion: "preliminary-clarification-v1",
    });

    expect(clarificationSet.questions[0].confidentialitySafe).toBe(true);
    expect(() =>
      ClarificationSetSchema.parse({
        ...clarificationSet,
        questions: [
          {
            ...clarificationSet.questions[0],
            confidential: "matter narrative",
          },
        ],
      }),
    ).toThrow();
  });

  it("accepts an identifier-only JobMessage", () => {
    const message = JobMessageSchema.parse({
      schemaVersion: 1,
      jobId: randomUUID(),
      reportRequestId: randomUUID(),
      userId: randomUUID(),
      confirmedEntityId: randomUUID(),
      attempt: 1,
      traceId: "trace-schema-001",
      budgetProfile: "mvp-standard",
    });

    expect(message.schemaVersion).toBe(1);
  });

  it("rejects identity fields in a JobMessage", () => {
    expect(() =>
      JobMessageSchema.parse({
        schemaVersion: 1,
        jobId: randomUUID(),
        reportRequestId: randomUUID(),
        userId: randomUUID(),
        confirmedEntityId: randomUUID(),
        attempt: 1,
        traceId: "trace-schema-002",
        budgetProfile: "mvp-standard",
        userEmail: "lawyer@example.com",
      }),
    ).toThrow();
  });

  it("rejects evidence outside the source-tier range", () => {
    expect(() =>
      EvidenceSchema.parse({
        schemaVersion: 1,
        evidenceId: randomUUID(),
        jobId: randomUUID(),
        url: "https://example.com/source",
        canonicalUrl: "https://example.com/source",
        title: "Public source",
        publisher: "Example",
        sourceTier: 6,
        accessedAt: "2026-07-13T12:00:00+05:30",
        excerpt: "Public information.",
        contentHash: "a".repeat(64),
        entityIdentifiers: {
          legalNames: ["Example Private Limited"],
          cins: [],
          addresses: [],
        },
        companyControlled: true,
        extractionMethod: "fixture",
        promptInjectionSuspected: false,
        retentionClass: "with_report",
      }),
    ).toThrow();
  });

  it("INTAKE-01/04 keeps the unversioned intake transport strict", () => {
    expect(
      CreateReportRequestSchema.parse({
        inputKind: "legal_name",
        legalName: "Example Private Limited",
        confidentialAck: true,
      }).inputKind,
    ).toBe("legal_name");

    expect(() =>
      CreateReportRequestSchema.parse({
        inputKind: "legal_name",
        legalName: "Example Private Limited",
        confidentialAck: true,
        description: "Confidential narrative must never enter intake.",
      }),
    ).toThrow();

    expect(
      CreateReportRequestResponseSchema.parse({
        reportRequest: {
          id: randomUUID(),
          inputKind: "legal_name",
          url: null,
          legalName: "Example Private Limited",
          cin: null,
          confidentialAckAt: "2026-07-13T20:30:00+00:00",
          state: "draft",
          createdAt: "2026-07-13T20:30:00+00:00",
          updatedAt: "2026-07-13T20:30:00+00:00",
        },
      }).reportRequest.state,
    ).toBe("draft");
  });

  it("ENTITY-03/04/07 keeps confirmation decisions strict and bounded", () => {
    expect(
      ConfirmEntityRequestSchema.parse({
        action: "confirm",
        candidateId: randomUUID(),
        relatedEntityIds: [randomUUID(), randomUUID()],
      }).relatedEntityIds,
    ).toHaveLength(2);

    expect(() =>
      ConfirmEntityRequestSchema.parse({
        action: "confirm",
        candidateId: randomUUID(),
        relatedEntityIds: [randomUUID(), randomUUID(), randomUUID()],
      }),
    ).toThrow();

    expect(() =>
      ConfirmEntityRequestSchema.parse({
        action: "none_of_these",
        description: "Confidential transaction narrative",
      }),
    ).toThrow();

    expect(
      ConfirmEntityResponseSchema.parse({
        state: "preliminary_research",
        confirmedEntityId: randomUUID(),
        relatedEntityIds: [],
        guidance: null,
      }).state,
    ).toBe("preliminary_research");
  });
});
