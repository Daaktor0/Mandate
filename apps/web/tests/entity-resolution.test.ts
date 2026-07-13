import type { SupabaseClient } from "@supabase/supabase-js";
import { describe, expect, it } from "vitest";

import { handleResolveEntity } from "../lib/entity-resolution/handler";
import { createSupabaseResolutionDependencies } from "../lib/entity-resolution/supabase-repository";
import type {
  EnqueueResolutionCommand,
  EnqueueResolutionResult,
  EntityResolutionDependencies,
} from "../lib/entity-resolution/types";

const USER_ID = "11111111-1111-4111-8111-111111111111";
const REQUEST_ID = "22222222-2222-4222-8222-222222222222";
const TRACE_ID = "trace-resolution-test";

function request(headers: Record<string, string> = {}): Request {
  return new Request(
    `https://mandate.example/api/report-requests/${REQUEST_ID}/resolve-entity`,
    { method: "POST", headers },
  );
}

function harness(
  result: EnqueueResolutionResult = {
    kind: "accepted",
    state: "resolving_entity",
  },
) {
  const commands: EnqueueResolutionCommand[] = [];
  const dependencies: EntityResolutionDependencies = {
    async authenticate() {
      return { id: USER_ID };
    },
    async enqueueResolution(command) {
      commands.push(command);
      return result;
    },
  };
  return { commands, dependencies };
}

async function errorCode(response: Response): Promise<string> {
  const body = (await response.json()) as { error: { code: string } };
  return body.error.code;
}

describe("entity-resolution enqueue API", () => {
  it("ENTITY-03 accepts an identifier-only unpaid task and returns immediately", async () => {
    const test = harness();
    const response = await handleResolveEntity(
      request({ "Idempotency-Key": "resolve-001" }),
      REQUEST_ID,
      test.dependencies,
      TRACE_ID,
    );

    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({ state: "resolving_entity" });
    expect(response.headers.get("X-Trace-Id")).toBe(TRACE_ID);
    expect(test.commands).toEqual([
      {
        reportRequestId: REQUEST_ID,
        idempotencyKey: "resolve-001",
        traceId: TRACE_ID,
      },
    ]);
    expect(test.commands[0]).not.toHaveProperty("entitlement");
    expect(test.commands[0]).not.toHaveProperty("legalName");
  });

  it("INTAKE-04 rejects every request body instead of accepting narrative", async () => {
    const test = harness();
    const response = await handleResolveEntity(
      new Request("https://mandate.example/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description: "private transaction details" }),
      }),
      REQUEST_ID,
      test.dependencies,
      TRACE_ID,
    );

    expect(response.status).toBe(422);
    expect(await errorCode(response)).toBe("INVALID_REQUEST");
    expect(test.commands).toHaveLength(0);
  });

  it("SEC-01 rejects unauthenticated callers before persistence", async () => {
    const dependencies: EntityResolutionDependencies = {
      async authenticate() {
        return null;
      },
      async enqueueResolution() {
        throw new Error("must not run");
      },
    };

    const response = await handleResolveEntity(
      request(),
      REQUEST_ID,
      dependencies,
      TRACE_ID,
    );
    expect(response.status).toBe(401);
    expect(await errorCode(response)).toBe("UNAUTHENTICATED");
  });

  it.each([
    [{ kind: "not_found" } as const, 404, "REQUEST_NOT_FOUND"],
    [{ kind: "state_conflict" } as const, 409, "INVALID_REQUEST_STATE"],
    [
      { kind: "rate_limited", retryAfterSeconds: 3600 } as const,
      429,
      "RATE_LIMITED",
    ],
  ])("ENTITY-03 maps persistence outcome %j", async (result, status, code) => {
    const test = harness(result);
    const response = await handleResolveEntity(
      request(),
      REQUEST_ID,
      test.dependencies,
      TRACE_ID,
    );
    expect(response.status).toBe(status);
    expect(await errorCode(response)).toBe(code);
  });
});

function clientWith(options: {
  rpcData?: unknown;
  rpcError?: { code: string; message: string } | null;
  onRpc?: (name: string, parameters: Record<string, unknown>) => void;
}): SupabaseClient {
  return {
    auth: {
      async getUser() {
        return { data: { user: { id: USER_ID } }, error: null };
      },
    },
    async rpc(name: string, parameters: Record<string, unknown>) {
      options.onRpc?.(name, parameters);
      return { data: options.rpcData ?? null, error: options.rpcError ?? null };
    },
  } as unknown as SupabaseClient;
}

describe("Supabase entity-resolution adapter", () => {
  it("ENTITY-03 calls only the tenant-scoped enqueue RPC", async () => {
    let call: [string, Record<string, unknown>] | null = null;
    const dependencies = createSupabaseResolutionDependencies(
      clientWith({
        rpcData: { state: "resolving_entity" },
        onRpc(name, parameters) {
          call = [name, parameters];
        },
      }),
    );

    await expect(
      dependencies.enqueueResolution({
        reportRequestId: REQUEST_ID,
        idempotencyKey: "resolve-001",
        traceId: TRACE_ID,
      }),
    ).resolves.toEqual({ kind: "accepted", state: "resolving_entity" });
    expect(call).toEqual([
      "enqueue_entity_resolution",
      {
        p_report_request_id: REQUEST_ID,
        p_idempotency_key: "resolve-001",
        p_trace_id: TRACE_ID,
      },
    ]);
  });

  it.each([
    ["P0002", "REPORT_REQUEST_NOT_FOUND", { kind: "not_found" }],
    ["P0001", "RESOLUTION_STATE_CONFLICT", { kind: "state_conflict" }],
    [
      "P0001",
      "RESOLUTION_RATE_LIMITED",
      { kind: "rate_limited", retryAfterSeconds: 3600 },
    ],
  ])(
    "SEC-01 maps only stable database errors",
    async (code, message, expected) => {
      const dependencies = createSupabaseResolutionDependencies(
        clientWith({ rpcError: { code, message } }),
      );
      await expect(
        dependencies.enqueueResolution({
          reportRequestId: REQUEST_ID,
          idempotencyKey: null,
          traceId: TRACE_ID,
        }),
      ).resolves.toEqual(expected);
    },
  );
});
