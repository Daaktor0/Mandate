import { describe, expect, it } from "vitest";

import {
  WEBSITE_ENTITY_CONFIRMATION_COPY,
  parseIntakeCommand,
} from "../lib/intake/contract";
import { handleCreateReportRequest } from "../lib/intake/handler";
import type {
  CreateReportRequestCommand,
  CreateReportRequestResult,
  IntakeDependencies,
} from "../lib/intake/types";

const USER_ID = "11111111-1111-4111-8111-111111111111";
const REQUEST_ID = "22222222-2222-4222-8222-222222222222";
const TRACE_ID = "trace-intake-test";
const NOW = "2026-07-13T20:30:00+00:00";

function storedRequest(command: CreateReportRequestCommand) {
  return {
    id: REQUEST_ID,
    inputKind: command.inputKind,
    url: command.url,
    legalName: command.legalName,
    cin: command.cin,
    confidentialAckAt: NOW,
    state: "draft" as const,
    createdAt: NOW,
    updatedAt: NOW,
  };
}

function createHarness(result?: CreateReportRequestResult) {
  const commands: CreateReportRequestCommand[] = [];
  const dependencies: IntakeDependencies = {
    async authenticate() {
      return { id: USER_ID };
    },
    async createReportRequest(command) {
      commands.push(command);
      return (
        result ?? { kind: "created", reportRequest: storedRequest(command) }
      );
    },
  };
  return { commands, dependencies };
}

function jsonRequest(
  body: unknown,
  headers: Record<string, string> = {},
): Request {
  return new Request("https://mandate.example/api/report-requests", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

async function errorCode(response: Response): Promise<string> {
  const body = (await response.json()) as { error: { code: string } };
  return body.error.code;
}

describe("Mandate Brief intake API", () => {
  it("AT-INTAKE-01 accepts exactly one website or legal-name input", async () => {
    const website = createHarness();
    const websiteResponse = await handleCreateReportRequest(
      jsonRequest({
        inputKind: "website",
        url: "https://Example.com/about#team",
        confidentialAck: true,
      }),
      website.dependencies,
      TRACE_ID,
    );
    expect(websiteResponse.status).toBe(201);
    expect(website.commands[0]).toMatchObject({
      inputKind: "website",
      url: "https://example.com/about",
      legalName: null,
    });

    const invalid = createHarness();
    const invalidResponse = await handleCreateReportRequest(
      jsonRequest({
        inputKind: "legal_name",
        url: "https://example.com",
        legalName: "Example Private Limited",
        confidentialAck: true,
      }),
      invalid.dependencies,
      TRACE_ID,
    );
    expect(invalidResponse.status).toBe(422);
    expect(invalid.commands).toHaveLength(0);
  });

  it("AT-INTAKE-02 preserves the authoritative entity-confirmation promise", () => {
    expect(WEBSITE_ENTITY_CONFIRMATION_COPY).toBe(
      "We will identify the legal entity behind this website and ask you to confirm it before research continues.",
    );
  });

  it.each([
    "http://localhost",
    "http://service.local",
    "http://10.0.0.1",
    "http://127.0.0.1",
    "http://2130706433",
    "http://169.254.169.254/latest/meta-data",
    "http://[::1]",
    "http://[::ffff:127.0.0.1]",
    "http://192.0.2.10",
    "ftp://example.com/file",
    "https://user:secret@example.com",
    "https://example.com/?access_token=secret",
    "https://example.com:8443",
    "not a URL",
  ])(
    "AT-INTAKE-03 rejects a non-public or unsupported URL: %s",
    async (url) => {
      const harness = createHarness();
      const response = await handleCreateReportRequest(
        jsonRequest({ inputKind: "website", url, confidentialAck: true }),
        harness.dependencies,
        TRACE_ID,
      );

      expect(response.status).toBe(422);
      expect(await errorCode(response)).toBe("INVALID_REQUEST");
      expect(harness.commands).toHaveLength(0);
    },
  );

  it("AT-INTAKE-03 accepts a canonical public HTTPS URL without fetching it", () => {
    const command = parseIntakeCommand(
      {
        inputKind: "website",
        url: "https://www.example.com/privacy?lang=en#controller",
        confidentialAck: true,
      },
      USER_ID,
      null,
    );

    expect(command.url).toBe("https://www.example.com/privacy?lang=en");
    expect(
      parseIntakeCommand(
        {
          inputKind: "website",
          url: "https://[2606:4700:4700::1111]/",
          confidentialAck: true,
        },
        USER_ID,
        null,
      ).url,
    ).toBe("https://[2606:4700:4700::1111]/");
  });

  it("AT-INTAKE-04 rejects confidential acknowledgement failures and extra narrative", async () => {
    const harness = createHarness();
    for (const body of [
      {
        inputKind: "legal_name",
        legalName: "Example Limited",
        confidentialAck: false,
      },
      {
        inputKind: "legal_name",
        legalName: "Example Limited",
        confidentialAck: true,
        description: "Private transaction details",
      },
    ]) {
      const response = await handleCreateReportRequest(
        jsonRequest(body),
        harness.dependencies,
        TRACE_ID,
      );
      expect(response.status).toBe(422);
    }
    expect(harness.commands).toHaveLength(0);
  });

  it("AT-INTAKE-05 keeps CIN optional and validates an exact CIN when supplied", async () => {
    const withoutCin = createHarness();
    await handleCreateReportRequest(
      jsonRequest({
        inputKind: "legal_name",
        legalName: "  Example   Private Limited  ",
        confidentialAck: true,
      }),
      withoutCin.dependencies,
      TRACE_ID,
    );
    expect(withoutCin.commands[0]).toMatchObject({
      legalName: "Example Private Limited",
      cin: null,
    });

    const invalidCin = createHarness();
    const response = await handleCreateReportRequest(
      jsonRequest({
        inputKind: "legal_name",
        legalName: "Example Private Limited",
        cin: "not-a-cin",
        confidentialAck: true,
      }),
      invalidCin.dependencies,
      TRACE_ID,
    );
    expect(response.status).toBe(422);
    expect(invalidCin.commands).toHaveLength(0);
  });

  it("AT-INTAKE-06 creates only a draft request and never passes entitlement data", async () => {
    const harness = createHarness();
    const response = await handleCreateReportRequest(
      jsonRequest(
        {
          inputKind: "legal_name",
          legalName: "Example Private Limited",
          confidentialAck: true,
        },
        { "Idempotency-Key": "intake-request-001" },
      ),
      harness.dependencies,
      TRACE_ID,
    );
    const body = (await response.json()) as {
      reportRequest: { state: string };
    };

    expect(body.reportRequest.state).toBe("draft");
    expect(Object.keys(harness.commands[0] ?? {})).toEqual([
      "userId",
      "inputKind",
      "url",
      "legalName",
      "cin",
      "idempotencyKey",
    ]);
  });

  it("SEC-01 rejects unauthenticated intake before persistence", async () => {
    const dependencies: IntakeDependencies = {
      async authenticate() {
        return null;
      },
      async createReportRequest() {
        throw new Error("must not be called");
      },
    };
    const response = await handleCreateReportRequest(
      jsonRequest({}),
      dependencies,
      TRACE_ID,
    );

    expect(response.status).toBe(401);
    expect(response.headers.get("X-Trace-Id")).toBe(TRACE_ID);
  });

  it("SEC-13 returns a stable rate-limit error and Retry-After", async () => {
    const harness = createHarness({
      kind: "rate_limited",
      retryAfterSeconds: 3600,
    });
    const response = await handleCreateReportRequest(
      jsonRequest({
        inputKind: "legal_name",
        legalName: "Example Limited",
        confidentialAck: true,
      }),
      harness.dependencies,
      TRACE_ID,
    );

    expect(response.status).toBe(429);
    expect(response.headers.get("Retry-After")).toBe("3600");
    expect(await errorCode(response)).toBe("RATE_LIMITED");
  });

  it("INTAKE-04 rejects non-JSON and oversized request bodies", async () => {
    const harness = createHarness();
    const wrongMediaType = await handleCreateReportRequest(
      new Request("https://mandate.example/api/report-requests", {
        method: "POST",
        headers: { "Content-Type": "text/plain" },
        body: "no",
      }),
      harness.dependencies,
      TRACE_ID,
    );
    expect(wrongMediaType.status).toBe(415);

    const oversized = await handleCreateReportRequest(
      jsonRequest({
        inputKind: "legal_name",
        legalName: "x".repeat(17 * 1024),
        confidentialAck: true,
      }),
      harness.dependencies,
      TRACE_ID,
    );
    expect(oversized.status).toBe(413);
    expect(harness.commands).toHaveLength(0);
  });
});
