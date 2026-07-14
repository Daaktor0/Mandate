import { notFound } from "next/navigation";

import { EntityConfirmationView } from "../../../../components/entity-confirmation-view";
import { createSupabaseEntityConfirmationDependencies } from "../../../../lib/entity-confirmation/supabase-repository";
import { createRequestSupabaseClient } from "../../../../lib/supabase/server";

type PageProps = Readonly<{ params: Promise<{ id: string }> }>;

const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export default async function EntityConfirmationPage({ params }: PageProps) {
  const { id } = await params;
  if (!UUID.test(id)) {
    notFound();
  }

  const client = await createRequestSupabaseClient();
  const dependencies = createSupabaseEntityConfirmationDependencies(client);
  const user = await dependencies.authenticate();
  if (user === null) {
    return (
      <main className="confirmation-shell">
        <section className="confirmation-panel">
          <p className="eyebrow">Authentication required</p>
          <h1>Sign in to confirm the legal entity</h1>
          <p>
            Entity candidates are private to the lawyer who created the Mandate
            Brief request.
          </p>
        </section>
      </main>
    );
  }

  const result = await dependencies.loadCandidates(id);
  if (result.kind === "not_found") {
    notFound();
  }
  return (
    <EntityConfirmationView
      reportRequestId={id}
      initialState={result.state}
      initialCandidates={[...result.candidates]}
    />
  );
}
