import { randomUUID } from "node:crypto";

import { CreateReportRequestResponseSchema } from "@mandate/shared-schemas";

import { InvalidIntakeError, parseIntakeCommand } from "./contract";
import type { IntakeDependencies } from "./types";
import { UnsafeIntakeUrlError } from "./url-policy";

const MAX_BODY_BYTES = 16 * 1024;
const IDEMPOTENCY_KEY = /^[!-~]{1,128}$/;

type ErrorCode =
  | "INVALID_REQUEST"
  | "PAYLOAD_TOO_LARGE"
  | "RATE_LIMITED"
  | "SERVICE_UNAVAILABLE"
  | "UNAUTHENTICATED"
  | "UNSUPPORTED_MEDIA_TYPE";

function responseHeaders(traceId: string): Headers {
  return new Headers({
    "Cache-Control": "no-store",
    "Content-Type": "application/json",
    "X-Content-Type-Options": "nosniff",
    "X-Trace-Id": traceId,
  });
}

export function intakeErrorResponse(
  status: number,
  code: ErrorCode,
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
  const key = request.headers.get("Idempotency-Key");
  if (key === null) {
    return null;
  }
  if (!IDEMPOTENCY_KEY.test(key)) {
    throw new InvalidIntakeError();
  }
  return key;
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
    throw new InvalidIntakeError();
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new InvalidIntakeError();
  }
}

export async function handleCreateReportRequest(
  request: Request,
  dependencies: IntakeDependencies,
  traceId: string = randomUUID(),
): Promise<Response> {
  try {
    const user = await dependencies.authenticate();
    if (user === null) {
      return intakeErrorResponse(
        401,
        "UNAUTHENTICATED",
        "Sign in to create a Mandate Brief request.",
        traceId,
      );
    }

    const body = await readJsonBody(request);
    const command = parseIntakeCommand(
      body,
      user.id,
      readIdempotencyKey(request),
    );
    const result = await dependencies.createReportRequest(command);
    if (result.kind === "rate_limited") {
      return intakeErrorResponse(
        429,
        "RATE_LIMITED",
        "Too many intake requests. Please try again later.",
        traceId,
        result.retryAfterSeconds,
      );
    }

    const payload = CreateReportRequestResponseSchema.parse({
      reportRequest: result.reportRequest,
    });
    return Response.json(payload, {
      status: 201,
      headers: responseHeaders(traceId),
    });
  } catch (error) {
    if (
      error instanceof TypeError &&
      error.message === "unsupported_media_type"
    ) {
      return intakeErrorResponse(
        415,
        "UNSUPPORTED_MEDIA_TYPE",
        "Use application/json for this request.",
        traceId,
      );
    }
    if (error instanceof RangeError && error.message === "payload_too_large") {
      return intakeErrorResponse(
        413,
        "PAYLOAD_TOO_LARGE",
        "The intake request is too large.",
        traceId,
      );
    }
    if (
      error instanceof InvalidIntakeError ||
      error instanceof UnsafeIntakeUrlError
    ) {
      return intakeErrorResponse(
        422,
        "INVALID_REQUEST",
        error.message,
        traceId,
      );
    }
    return intakeErrorResponse(
      503,
      "SERVICE_UNAVAILABLE",
      "The request could not be created. Please try again.",
      traceId,
    );
  }
}
