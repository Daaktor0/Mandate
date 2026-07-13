import { ResolveEntityResponseSchema } from "@mandate/shared-schemas";
import type { SupabaseClient } from "@supabase/supabase-js";

import type {
  EnqueueResolutionCommand,
  EnqueueResolutionResult,
  EntityResolutionDependencies,
  ResolutionUser,
} from "./types";

export function createSupabaseResolutionDependencies(
  client: SupabaseClient,
): EntityResolutionDependencies {
  return {
    async authenticate(): Promise<ResolutionUser | null> {
      const { data, error } = await client.auth.getUser();
      if (error !== null) {
        throw new Error("Supabase session validation failed");
      }
      return data.user === null ? null : Object.freeze({ id: data.user.id });
    },

    async enqueueResolution(
      command: EnqueueResolutionCommand,
    ): Promise<EnqueueResolutionResult> {
      const { data, error } = await client.rpc("enqueue_entity_resolution", {
        p_report_request_id: command.reportRequestId,
        p_idempotency_key: command.idempotencyKey,
        p_trace_id: command.traceId,
      });
      if (error !== null) {
        if (
          error.code === "P0002" &&
          error.message === "REPORT_REQUEST_NOT_FOUND"
        ) {
          return Object.freeze({ kind: "not_found" });
        }
        if (
          error.code === "P0001" &&
          error.message === "RESOLUTION_STATE_CONFLICT"
        ) {
          return Object.freeze({ kind: "state_conflict" });
        }
        if (
          error.code === "P0001" &&
          error.message === "RESOLUTION_RATE_LIMITED"
        ) {
          return Object.freeze({
            kind: "rate_limited",
            retryAfterSeconds: 3600,
          });
        }
        throw new Error("Supabase entity-resolution enqueue failed");
      }
      const parsed = ResolveEntityResponseSchema.parse(data);
      return Object.freeze({
        kind: "accepted",
        state: parsed.state,
      });
    },
  };
}
