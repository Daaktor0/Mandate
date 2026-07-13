import type { SupabaseClient } from "@supabase/supabase-js";
import { describe, expect, it } from "vitest";

import { createSupabaseIntakeDependencies } from "../lib/intake/supabase-repository";
import type { CreateReportRequestCommand } from "../lib/intake/types";

const USER_ID = "11111111-1111-4111-8111-111111111111";
const REQUEST_ID = "22222222-2222-4222-8222-222222222222";
const NOW = "2026-07-13T20:30:00+00:00";

const COMMAND: CreateReportRequestCommand = {
  userId: USER_ID,
  inputKind: "legal_name",
  url: null,
  legalName: "Example Private Limited",
  cin: null,
  idempotencyKey: "intake-request-001",
};

function clientWith(options: {
  user?: { id: string } | null;
  authError?: { message: string } | null;
  rpcData?: unknown;
  rpcError?: { code: string; message: string } | null;
  onRpc?: (parameters: Record<string, unknown>) => void;
}): SupabaseClient {
  return {
    auth: {
      async getUser() {
        return {
          data: { user: options.user ?? null },
          error: options.authError ?? null,
        };
      },
    },
    async rpc(_name: string, parameters: Record<string, unknown>) {
      options.onRpc?.(parameters);
      return { data: options.rpcData ?? null, error: options.rpcError ?? null };
    },
  } as unknown as SupabaseClient;
}

describe("Supabase intake adapter", () => {
  it("SEC-01 trusts only the server-validated Supabase user", async () => {
    const dependencies = createSupabaseIntakeDependencies(
      clientWith({ user: { id: USER_ID } }),
    );

    await expect(dependencies.authenticate()).resolves.toEqual({ id: USER_ID });
  });

  it("INTAKE-01 sends only typed public-intake fields to the RLS RPC", async () => {
    let sent: Record<string, unknown> = {};
    const dependencies = createSupabaseIntakeDependencies(
      clientWith({
        user: { id: USER_ID },
        rpcData: {
          reportRequest: {
            id: REQUEST_ID,
            inputKind: "legal_name",
            url: null,
            legalName: "Example Private Limited",
            cin: null,
            confidentialAckAt: NOW,
            state: "draft",
            createdAt: NOW,
            updatedAt: NOW,
          },
        },
        onRpc(parameters) {
          sent = parameters;
        },
      }),
    );

    const result = await dependencies.createReportRequest(COMMAND);

    expect(result.kind).toBe("created");
    expect(sent).toEqual({
      p_input_kind: "legal_name",
      p_input_url: null,
      p_input_legal_name: "Example Private Limited",
      p_input_cin: null,
      p_confidential_ack: true,
      p_idempotency_key: "intake-request-001",
    });
    expect(sent).not.toHaveProperty("userId");
    expect(sent).not.toHaveProperty("entitlement");
  });

  it("SEC-13 maps only the stable database rate-limit signal", async () => {
    const rateLimited = createSupabaseIntakeDependencies(
      clientWith({
        rpcError: { code: "P0001", message: "INTAKE_RATE_LIMITED" },
      }),
    );
    await expect(rateLimited.createReportRequest(COMMAND)).resolves.toEqual({
      kind: "rate_limited",
      retryAfterSeconds: 3600,
    });

    const unknownFailure = createSupabaseIntakeDependencies(
      clientWith({ rpcError: { code: "P0001", message: "internal detail" } }),
    );
    await expect(unknownFailure.createReportRequest(COMMAND)).rejects.toThrow(
      "Supabase intake persistence failed",
    );
  });
});
