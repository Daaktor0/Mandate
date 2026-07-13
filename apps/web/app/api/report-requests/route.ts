import { randomUUID } from "node:crypto";

import {
  handleCreateReportRequest,
  intakeErrorResponse,
} from "../../../lib/intake/handler";
import { createSupabaseIntakeDependencies } from "../../../lib/intake/supabase-repository";
import { createRequestSupabaseClient } from "../../../lib/supabase/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: Request): Promise<Response> {
  const traceId = randomUUID();
  try {
    const client = await createRequestSupabaseClient();
    return await handleCreateReportRequest(
      request,
      createSupabaseIntakeDependencies(client),
      traceId,
    );
  } catch {
    return intakeErrorResponse(
      503,
      "SERVICE_UNAVAILABLE",
      "The request could not be created. Please try again.",
      traceId,
    );
  }
}
