export type ResolutionUser = Readonly<{ id: string }>;

export type EnqueueResolutionCommand = Readonly<{
  reportRequestId: string;
  idempotencyKey: string | null;
  traceId: string;
}>;

export type EnqueueResolutionResult =
  | Readonly<{ kind: "accepted"; state: "resolving_entity" }>
  | Readonly<{ kind: "not_found" }>
  | Readonly<{ kind: "state_conflict" }>
  | Readonly<{ kind: "rate_limited"; retryAfterSeconds: number }>;

export interface EntityResolutionDependencies {
  authenticate(): Promise<ResolutionUser | null>;
  enqueueResolution(
    command: EnqueueResolutionCommand,
  ): Promise<EnqueueResolutionResult>;
}
