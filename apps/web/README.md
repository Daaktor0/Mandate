# Web application

This directory owns the Mandate web application, short-lived API route handlers and the admin interface (SYSTEM-SPEC C1, C2 and C14).

Long-running research and rendering must never execute in the web request path. No service-role or worker/provider secret may be exposed to browser bundles.

The web app does not directly write the Phase 2 evidence, claims, checkpoint, agent-run
or provider-cost tables. Future API routes must use the authenticated owner boundary
or a narrowly scoped server-side operation; the migration currently leaves these
tables service-role-only until those policies and routes are reviewed. No browser
route may forward prompts, raw fetched bodies, letterhead, billing data or confidential
matter narrative to the worker or a provider.
