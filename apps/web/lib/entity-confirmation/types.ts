import type {
  ConfirmEntityRequest,
  ConfirmEntityResponse,
  EntityCandidate,
} from "@mandate/shared-schemas";

export type ConfirmationUser = Readonly<{ id: string }>;

export type EntityCandidateState =
  | "draft"
  | "resolving_entity"
  | "awaiting_entity_confirmation"
  | "preliminary_research"
  | "failed_no_charge";

export type CandidateListResult =
  | Readonly<{
      kind: "found";
      state: EntityCandidateState;
      candidates: readonly EntityCandidate[];
    }>
  | Readonly<{ kind: "not_found" }>;

export type ConfirmEntityCommand = Readonly<{
  reportRequestId: string;
  decision: ConfirmEntityRequest;
  idempotencyKey: string | null;
  traceId: string;
}>;

export type ConfirmEntityResult =
  | Readonly<{ kind: "accepted"; response: ConfirmEntityResponse }>
  | Readonly<{ kind: "not_found" }>
  | Readonly<{ kind: "state_conflict" }>
  | Readonly<{ kind: "idempotency_conflict" }>
  | Readonly<{ kind: "invalid" }>
  | Readonly<{ kind: "rate_limited"; retryAfterSeconds: number }>;

export interface EntityConfirmationDependencies {
  authenticate(): Promise<ConfirmationUser | null>;
  loadCandidates(reportRequestId: string): Promise<CandidateListResult>;
  confirmEntity(command: ConfirmEntityCommand): Promise<ConfirmEntityResult>;
}
