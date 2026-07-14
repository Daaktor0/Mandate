import {
  ConfirmEntityResponseSchema,
  EntityCandidateSchema,
} from "@mandate/shared-schemas";
import type { SupabaseClient } from "@supabase/supabase-js";

import type {
  CandidateListResult,
  ConfirmEntityCommand,
  ConfirmEntityResult,
  ConfirmationUser,
  EntityCandidateState,
  EntityConfirmationDependencies,
} from "./types";

const CANDIDATE_STATES = new Set<EntityCandidateState>([
  "draft",
  "resolving_entity",
  "awaiting_entity_confirmation",
  "preliminary_research",
  "failed_no_charge",
]);

function candidateState(value: unknown): EntityCandidateState {
  if (typeof value !== "string" || !CANDIDATE_STATES.has(value as EntityCandidateState)) {
    throw new Error("Supabase returned an unsupported entity-confirmation state");
  }
  return value as EntityCandidateState;
}

export function createSupabaseEntityConfirmationDependencies(
  client: SupabaseClient,
): EntityConfirmationDependencies {
  return {
    async authenticate(): Promise<ConfirmationUser | null> {
      const { data, error } = await client.auth.getUser();
      if (error !== null) {
        throw new Error("Supabase session validation failed");
      }
      return data.user === null ? null : Object.freeze({ id: data.user.id });
    },

    async loadCandidates(reportRequestId: string): Promise<CandidateListResult> {
      const { data: request, error: requestError } = await client
        .from("report_requests")
        .select("state")
        .eq("id", reportRequestId)
        .maybeSingle();
      if (requestError !== null) {
        throw new Error("Supabase request-state lookup failed");
      }
      if (request === null) {
        return Object.freeze({ kind: "not_found" });
      }

      const state = candidateState(request.state);
      if (state !== "awaiting_entity_confirmation") {
        return Object.freeze({ kind: "found", state, candidates: [] });
      }

      const { data: rows, error: candidateError } = await client
        .from("entity_candidates")
        .select("candidate_payload")
        .eq("report_request_id", reportRequestId)
        .order("rank", { ascending: true });
      if (candidateError !== null) {
        throw new Error("Supabase candidate lookup failed");
      }
      const candidates = (rows ?? []).map((row) =>
        EntityCandidateSchema.parse(row.candidate_payload),
      );
      return Object.freeze({ kind: "found", state, candidates });
    },

    async confirmEntity(command: ConfirmEntityCommand): Promise<ConfirmEntityResult> {
      const { decision } = command;
      const { data, error } = await client.rpc("confirm_report_request_entity", {
        p_report_request_id: command.reportRequestId,
        p_action: decision.action,
        p_candidate_id: decision.candidateId ?? null,
        p_related_entity_ids: decision.relatedEntityIds,
        p_legal_name: decision.legalName ?? null,
        p_cin: decision.cin ?? null,
        p_state: decision.state ?? null,
        p_idempotency_key: command.idempotencyKey,
        p_trace_id: command.traceId,
      });
      if (error !== null) {
        if (
          error.code === "P0002" &&
          (error.message === "REPORT_REQUEST_NOT_FOUND" ||
            error.message === "ENTITY_CANDIDATE_NOT_FOUND")
        ) {
          return Object.freeze({ kind: "not_found" });
        }
        if (
          error.code === "P0001" &&
          error.message === "CONFIRMATION_STATE_CONFLICT"
        ) {
          return Object.freeze({ kind: "state_conflict" });
        }
        if (error.code === "P0001" && error.message === "IDEMPOTENCY_CONFLICT") {
          return Object.freeze({ kind: "idempotency_conflict" });
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
        if (error.code === "22023") {
          return Object.freeze({ kind: "invalid" });
        }
        throw new Error("Supabase entity-confirmation operation failed");
      }
      return Object.freeze({
        kind: "accepted",
        response: ConfirmEntityResponseSchema.parse(data),
      });
    },
  };
}
