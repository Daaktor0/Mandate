# Shared schemas

JSON Schema files in `schemas/` are the source of truth for objects that cross the web/worker boundary. `scripts/generate_schemas.py` produces strict Pydantic v2 models in `python/mandate_schemas/generated.py` and zod validators/types in `typescript/generated.ts`.

Every cross-process payload is versioned with `schemaVersion`; short HTTP response envelopes may opt out explicitly with `x-mandate-versioned: false`. Every object rejects unknown fields and is checked for generation drift in CI. Generated files are committed for reviewability and must never be edited directly.
