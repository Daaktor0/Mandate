import {
  ConfirmEntityRequestSchema,
  ConfirmEntityResponseSchema,
  EntityCandidateSchema,
} from "@mandate/shared-schemas";

import type {
  ConfirmEntityCommand,
  EntityConfirmationDependencies,
} from "./types";

const MAX_BODY_BYTES = 16 * 1024;
const IDEMPOTENCY_KEY = /^[!-~]{1,128}$/;
const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type ConfirmationErrorCode =
  | "IDEMPOTENCY_CONFLICT"
  | "INVALID_REQUEST"
  | "INVALID_REQUEST_STATE"
  | "PAYLOAD_TOO_LARGE"
  | "RATE_LIMITED"
  | "REQUEST_NOT_FOUND"
  | "SERVICE_UNAVAILABLE"
  | "UNAUTHENTICATED"
  | "UNSUPPORTED_MEDIA_TYPE";

class InvalidConfirmationError extends Error {
  constructor(message = "Choose a valid entity-confirmation action.") {
    super(message);
  }
}

function responseHeaders(traceId: string): Headers {
  return new Headers({
    "Cache-Control": "no-store",
    "Content-Type": "application/json",
    "X-Content-Type-Options": "nosniff",
    "X-Trace-Id": traceId,
  });
}

export function confirmationErrorResponse(
  status: number,
  code: ConfirmationErrorCode,
  message: string,
  traceId: string,
  retryAfterSeconds?: number,
): Response {
  const headers = responseHeaders(traceId);
  if (retryAfterSeconds !== undefined) {
    headers.set("Retry-After", retryAfterSeconds.toString());
  }
  return Response.json(
    { error: { code, message, traceId } },
    { status, headers },
  );
}

function readIdempotencyKey(request: Request): string | null {
  const value = request.headers.get("Idempotency-Key");
  if (value === null) {
    return null;
  }
  if (!IDEMPOTENCY_KEY.test(value)) {
    throw new InvalidConfirmationError("The idempotency key is invalid.");
  }
  return value;
}

async function readJsonBody(request: Request): Promise<unknown> {
  const mediaType = request.headers
    .get("Content-Type")
    ?.split(";", 1)[0]
    ?.trim()
    .toLowerCase();
  if (mediaType !== "application/json") {
    throw new TypeError("unsupported_media_type");
  }
  const declaredLength = request.headers.get("Content-Length");
  if (declaredLength !== null && Number(declaredLength) > MAX_BODY_BYTES) {
    throw new RangeError("payload_too_large");
  }

  const reader = request.body?.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let received = 0;
  let text = "";
  try {
    if (reader !== undefined) {
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) {
          break;
        }
        received += chunk.value.byteLength;
        if (received > MAX_BODY_BYTES) {
          void reader.cancel();
          throw new RangeError("payload_too_large");
        }
        text += decoder.decode(chunk.value, { stream: true });
      }
      text += decoder.decode();
    }
  } catch (error) {
    if (error instanceof RangeError) {
      throw error;
    }
    throw new InvalidConfirmationError();
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new InvalidConfirmationError();
  }
}

function parseDecision(body: unknown) {
  const parsed = ConfirmEntityRequestSchema.safeParse(body);
  if (!parsed.success) {
    throw new InvalidConfirmationError();
  }
  const decision = parsed.data;
  const related = decision.relatedEntityIds;
  if (new Set(related).size !== related.length) {
    throw new InvalidConfirmationError("A related entity can be included only once.");
  }

  if (decision.action === "confirm") {
    if (
      decision.candidateId === undefined ||
      decision.legalName !== undefined ||
      decision.cin !== undefined ||
      decision.state !== undefined
    ) {
      throw new InvalidConfirmationError();
    }
  } else if (decision.action === "none_of_these") {
    if (
      decision.candidateId !== undefined ||
      related.length !== 0 ||
      decision.legalName !== undefined ||
      decision.cin !== undefined ||
      decision.state !== undefined
    ) {
      throw new InvalidConfirmationError();
    }
  } else if (
    decision.candidateId !== undefined ||
    related.length !== 0 ||
    (decision.legalName === undefined && decision.cin === undefined)
  ) {
    throw new InvalidConfirmationError(
      "Enter a registered legal name or CIN before resolving again.",
    );
  }
  return decision;
}

export async function handleGetEntityCandidates(
  reportRequestId: string,
  dependencies: EntityConfirmationDependencies,
  traceId: string,
): Promise<Response> {
  try {
    if (!UUID.test(reportRequestId)) {
      return confirmationErrorResponse(
        404,
        "REQUEST_NOT_FOUND",
        "The Mandate Brief request was not found.",
        traceId,
      );
    }
    const user = await dependencies.authenticate();
    if (user === null) {
      return confirmationErrorResponse(
        401,
        "UNAUTHENTICATED",
        "Sign in to review entity candidates.",
        traceId,
      );
    }
    const result = await dependencies.loadCandidates(reportRequestId);
    if (result.kind === "not_found") {
      return confirmationErrorResponse(
        404,
        "REQUEST_NOT_FOUND",
        "The Mandate Brief request was not found.",
        traceId,
      );
    }
    const candidates = EntityCandidateSchema.array().max(20).parse(result.candidates);
    return Response.json(
      { state: result.state, candidates },
      { status: 200, headers: responseHeaders(traceId) },
    );
  } catch {
    return confirmationErrorResponse(
      503,
      "SERVICE_UNAVAILABLE",
      "Entity candidates could not be loaded. Please try again.",
      traceId,
    );
  }
}

export async function handleConfirmEntity(
  request: Request,
  reportRequestId: string,
  dependencies: EntityConfirmationDependencies,
  traceId: string,
): Promise<Response> {
  try {
    if (!UUID.test(reportRequestId)) {
      return confirmationErrorResponse(
        404,
        "REQUEST_NOT_FOUND",
        "The Mandate Brief request was not found.",
        traceId,
      );
    }
    const user = await dependencies.authenticate();
    if (user === null) {
      return confirmationErrorResponse(
        401,
        "UNAUTHENTICATED",
        "Sign in to confirm a legal entity.",
        traceId,
      );
    }

    const decision = parseDecision(await readJsonBody(request));
    const command: ConfirmEntityCommand = {
      reportRequestId,
      decision,
      idempotencyKey: readIdempotencyKey(request),
      traceId,
    };
    const result = await dependencies.confirmEntity(command);
    if (result.kind === "not_found") {
      return confirmationErrorResponse(
        404,
        "REQUEST_NOT_FOUND",
        "The request or selected candidate was not found.",
        traceId,
      );
    }
    if (result.kind === "state_conflict") {
      return confirmationErrorResponse(
        409,
        "INVALID_REQUEST_STATE",
        "This request no longer requires entity confirmation.",
        traceId,
      );
    }
    if (result.kind === "idempotency_conflict") {
      return confirmationErrorResponse(
        409,
        "IDEMPOTENCY_CONFLICT",
        "That idempotency key was already used for a different decision.",
        traceId,
      );
    }
    if (result.kind === "rate_limited") {
      return confirmationErrorResponse(
        429,
        "RATE_LIMITED",
        "Too many entity-resolution requests. Please try again later.",
        traceId,
        result.retryAfterSeconds,
      );
    }
    if (result.kind === "invalid") {
      return confirmationErrorResponse(
        422,
        "INVALID_REQUEST",
        "The entity-confirmation decision is invalid.",
        traceId,
      );
    }

    const payload = ConfirmEntityResponseSchema.parse(result.response);
    return Response.json(payload, {
      status: decision.action === "none_of_these" ? 200 : 202,
      headers: responseHeaders(traceId),
    });
  } catch (error) {
    if (
      error instanceof TypeError &&
      error.message === "unsupported_media_type"
    ) {
      return confirmationErrorResponse(
        415,
        "UNSUPPORTED_MEDIA_TYPE",
        "Use application/json for this request.",
        traceId,
      );
    }
    if (error instanceof RangeError && error.message === "payload_too_large") {
      return confirmationErrorResponse(
        413,
        "PAYLOAD_TOO_LARGE",
        "The entity-confirmation request is too large.",
        traceId,
      );
    }
    if (error instanceof InvalidConfirmationError) {
      return confirmationErrorResponse(
        422,
        "INVALID_REQUEST",
        error.message,
        traceId,
      );
    }
    return confirmationErrorResponse(
      503,
      "SERVICE_UNAVAILABLE",
      "The entity-confirmation decision could not be saved. Please try again.",
      traceId,
    );
  }
}
