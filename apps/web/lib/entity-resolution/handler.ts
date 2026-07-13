import { ResolveEntityResponseSchema } from "@mandate/shared-schemas";

import type { EntityResolutionDependencies } from "./types";

const IDEMPOTENCY_KEY = /^[!-~]{1,128}$/;
const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type ResolutionErrorCode =
  | "INVALID_REQUEST"
  | "INVALID_REQUEST_STATE"
  | "RATE_LIMITED"
  | "REQUEST_NOT_FOUND"
  | "SERVICE_UNAVAILABLE"
  | "UNAUTHENTICATED";

function responseHeaders(traceId: string): Headers {
  return new Headers({
    "Cache-Control": "no-store",
    "Content-Type": "application/json",
    "X-Content-Type-Options": "nosniff",
    "X-Trace-Id": traceId,
  });
}

export function resolutionErrorResponse(
  status: number,
  code: ResolutionErrorCode,
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

function idempotencyKey(request: Request): string | null {
  const value = request.headers.get("Idempotency-Key");
  return value !== null && IDEMPOTENCY_KEY.test(value) ? value : null;
}

export async function handleResolveEntity(
  request: Request,
  reportRequestId: string,
  dependencies: EntityResolutionDependencies,
  traceId: string,
): Promise<Response> {
  try {
    if (!UUID.test(reportRequestId)) {
      return resolutionErrorResponse(
        404,
        "REQUEST_NOT_FOUND",
        "The Mandate Brief request was not found.",
        traceId,
      );
    }
    if (
      request.body !== null ||
      (request.headers.has("Idempotency-Key") &&
        idempotencyKey(request) === null)
    ) {
      return resolutionErrorResponse(
        422,
        "INVALID_REQUEST",
        "Entity resolution accepts no request body.",
        traceId,
      );
    }

    const user = await dependencies.authenticate();
    if (user === null) {
      return resolutionErrorResponse(
        401,
        "UNAUTHENTICATED",
        "Sign in to resolve a legal entity.",
        traceId,
      );
    }

    const result = await dependencies.enqueueResolution({
      reportRequestId,
      idempotencyKey: idempotencyKey(request),
      traceId,
    });
    if (result.kind === "not_found") {
      return resolutionErrorResponse(
        404,
        "REQUEST_NOT_FOUND",
        "The Mandate Brief request was not found.",
        traceId,
      );
    }
    if (result.kind === "state_conflict") {
      return resolutionErrorResponse(
        409,
        "INVALID_REQUEST_STATE",
        "The request cannot start entity resolution from its current state.",
        traceId,
      );
    }
    if (result.kind === "rate_limited") {
      return resolutionErrorResponse(
        429,
        "RATE_LIMITED",
        "Too many entity-resolution requests. Please try again later.",
        traceId,
        result.retryAfterSeconds,
      );
    }

    const payload = ResolveEntityResponseSchema.parse({ state: result.state });
    return Response.json(payload, {
      status: 202,
      headers: responseHeaders(traceId),
    });
  } catch {
    return resolutionErrorResponse(
      503,
      "SERVICE_UNAVAILABLE",
      "Entity resolution could not be started. Please try again.",
      traceId,
    );
  }
}
