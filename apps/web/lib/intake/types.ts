import type { CreateReportRequestResponseReportRequest } from "@mandate/shared-schemas";

export type IntakeUser = Readonly<{ id: string }>;

export type CreateReportRequestCommand = Readonly<{
  userId: string;
  inputKind: "website" | "legal_name";
  url: string | null;
  legalName: string | null;
  cin: string | null;
  idempotencyKey: string | null;
}>;

export type CreateReportRequestResult =
  | Readonly<{
      kind: "created";
      reportRequest: CreateReportRequestResponseReportRequest;
    }>
  | Readonly<{ kind: "rate_limited"; retryAfterSeconds: number }>;

export interface IntakeDependencies {
  authenticate(): Promise<IntakeUser | null>;
  createReportRequest(
    command: CreateReportRequestCommand,
  ): Promise<CreateReportRequestResult>;
}
