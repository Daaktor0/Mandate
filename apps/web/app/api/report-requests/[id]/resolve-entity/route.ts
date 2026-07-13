import { randomUUID } from "node:crypto";

import {
  handleResolveEntity,
  resolutionErrorResponse,
} from "../../../../../lib/entity-resolution/handler";
import { createSupabaseResolutionDependencies } from "../../../../../lib/entity-resolution/supabase-repository";
import { createRequestSupabaseClient } from "../../../../../lib/supabase/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type RouteContext = Readonly<{ params: Promise<{ id: string }> }>;

export async function POST(
  request: Request,
  context: RouteContext,
): Promise<Response> {
  const traceId = randomUUID();
  try {
    const [{ id }, client] = await Promise.all([
      context.params,
      createRequestSupabaseClient(),
    ]);
    return await handleResolveEntity(
      request,
      id,
      createSupabaseResolutionDependencies(client),
      traceId,
    );
  } catch {
    return resolutionErrorResponse(
      503,
      "SERVICE_UNAVAILABLE",
      "Entity resolution could not be started. Please try again.",
      traceId,
    );
  }
}
