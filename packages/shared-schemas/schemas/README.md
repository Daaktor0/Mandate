# shared-schemas/schemas

JSON Schema is the source of truth for cross-runtime contracts. The intake
slice adds `create-report-request.json` and
`create-report-request-response.json`. Conditional input rules and the SSRF
preflight policy are enforced by the API after generated-schema validation
because the fail-closed generator intentionally supports a smaller subset than
JSON Schema `oneOf`.
