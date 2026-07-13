# Web application

This directory owns the Mandate web application, short-lived API route handlers and the admin interface (SYSTEM-SPEC C1, C2 and C14).

Long-running research and rendering must never execute in the web request path. No service-role or worker/provider secret may be exposed to browser bundles.
