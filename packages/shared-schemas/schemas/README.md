# shared-schemas/schemas

JSON Schema is the source of truth for cross-runtime contracts. The intake
slice adds create-request contracts; entity resolution adds the identifier-only
`light-task-message.json` and `resolve-entity-response.json`. Conditional input rules and the SSRF
preflight policy are enforced by the API after generated-schema validation
because the fail-closed generator intentionally supports a smaller subset than
JSON Schema `oneOf`.
