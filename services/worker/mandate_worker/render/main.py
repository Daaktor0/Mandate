"""Health-only control surface for the isolated renderer process.

The render job consumer is added in Phase 4. Keeping this process limited to the
shared internal health surface in Phase 0 proves the sandbox without accepting
render payloads or exposing a network route.
"""

from mandate_worker.main import create_app

app = create_app(service_name="mandate-renderer")
