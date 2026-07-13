import {
  CreateReportRequestResponseReportRequestSchema,
  type CreateReportRequestResponseReportRequest,
} from "@mandate/shared-schemas";
import type { SupabaseClient } from "@supabase/supabase-js";

import type {
  CreateReportRequestCommand,
  CreateReportRequestResult,
  IntakeDependencies,
  IntakeUser,
} from "./types";

type RpcPayload = Readonly<{
  reportRequest?: Readonly<{
    id?: unknown;
    inputKind?: unknown;
    url?: unknown;
    legalName?: unknown;
    cin?: unknown;
    confidentialAckAt?: unknown;
    state?: unknown;
    createdAt?: unknown;
    updatedAt?: unknown;
  }>;
}>;

function parseRpcPayload(
  value: unknown,
): CreateReportRequestResponseReportRequest {
  if (
    typeof value !== "object" ||
    value === null ||
    !("reportRequest" in value)
  ) {
    throw new Error("invalid intake RPC response");
  }
  return CreateReportRequestResponseReportRequestSchema.parse(
    (value as RpcPayload).reportRequest,
  );
}

export function createSupabaseIntakeDependencies(
  client: SupabaseClient,
): IntakeDependencies {
  return {
    async authenticate(): Promise<IntakeUser | null> {
      const { data, error } = await client.auth.getUser();
      if (error !== null) {
        throw new Error("Supabase session validation failed");
      }
      return data.user === null ? null : Object.freeze({ id: data.user.id });
    },

    async createReportRequest(
      command: CreateReportRequestCommand,
    ): Promise<CreateReportRequestResult> {
      const { data, error } = await client.rpc("create_report_request", {
        p_input_kind: command.inputKind,
        p_input_url: command.url,
        p_input_legal_name: command.legalName,
        p_input_cin: command.cin,
        p_confidential_ack: true,
        p_idempotency_key: command.idempotencyKey,
      });
      if (error !== null) {
        if (error.code === "P0001" && error.message === "INTAKE_RATE_LIMITED") {
          return Object.freeze({
            kind: "rate_limited",
            retryAfterSeconds: 3600,
          });
        }
        throw new Error("Supabase intake persistence failed");
      }
      return Object.freeze({
        kind: "created",
        reportRequest: parseRpcPayload(data),
      });
    },
  };
}
