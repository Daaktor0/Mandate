import {
  CreateReportRequestSchema,
  type CreateReportRequest,
} from "@mandate/shared-schemas";

import { canonicalizePublicWebsiteUrl } from "./url-policy";
import type { CreateReportRequestCommand } from "./types";

export const WEBSITE_ENTITY_CONFIRMATION_COPY =
  "We will identify the legal entity behind this website and ask you to confirm it before research continues.";

export class InvalidIntakeError extends Error {
  constructor() {
    super(
      "Submit either a public website URL or a legal company name, and confirm the notice.",
    );
    this.name = "InvalidIntakeError";
  }
}

function normalizeLegalName(value: string): string {
  const normalized = value.trim().replace(/\s+/g, " ");
  if (normalized.length === 0) {
    throw new InvalidIntakeError();
  }
  return normalized;
}

function parseGeneratedContract(value: unknown): CreateReportRequest {
  const result = CreateReportRequestSchema.safeParse(value);
  if (!result.success) {
    throw new InvalidIntakeError();
  }
  return result.data;
}

export function parseIntakeCommand(
  value: unknown,
  userId: string,
  idempotencyKey: string | null,
): CreateReportRequestCommand {
  const input = parseGeneratedContract(value);

  if (input.inputKind === "website") {
    if (input.url === undefined || input.legalName !== undefined) {
      throw new InvalidIntakeError();
    }
    return Object.freeze({
      userId,
      inputKind: input.inputKind,
      url: canonicalizePublicWebsiteUrl(input.url),
      legalName: null,
      cin: input.cin ?? null,
      idempotencyKey,
    });
  }

  if (input.legalName === undefined || input.url !== undefined) {
    throw new InvalidIntakeError();
  }
  return Object.freeze({
    userId,
    inputKind: input.inputKind,
    url: null,
    legalName: normalizeLegalName(input.legalName),
    cin: input.cin ?? null,
    idempotencyKey,
  });
}
