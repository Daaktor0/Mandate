import { randomUUID } from "node:crypto";

import {
  confirmationErrorResponse,
  handleGetEntityCandidates,
} from "../../../../../lib/entity-confirmation/handler";
import { createSupabaseEntityConfirmationDependencies } from "../../../../../lib/entity-confirmation/supabase-repository";
import { createRequestSupabaseClient } from "../../../../../lib/supabase/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type RouteContext = Readonly<{ params: Promise<{ id: string }> }>;

export async function GET(
  _request: Request,
  context: RouteContext,
): Promise<Response> {
  const traceId = randomUUID();
  try {
    const [{ id }, client] = await Promise.all([
      context.params,
      createRequestSupabaseClient(),
    ]);
    return await handleGetEntityCandidates(
      id,
      createSupabaseEntityConfirmationDependencies(client),
      traceId,
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
