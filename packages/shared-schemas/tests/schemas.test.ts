import { randomUUID } from "node:crypto";

import { describe, expect, it } from "vitest";

import { EvidenceSchema, JobMessageSchema } from "../typescript";

describe("RUN-05 shared-schema validation", () => {
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
});
