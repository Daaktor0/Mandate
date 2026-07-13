#!/usr/bin/env python3
"""Generate strict Pydantic and zod contracts from Mandate JSON Schemas.

The generator intentionally supports the JSON Schema subset used by Mandate's
cross-runtime contracts. Unsupported keywords fail closed instead of being
silently ignored.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "packages" / "shared-schemas" / "schemas"
PYTHON_OUTPUT = ROOT / "packages" / "shared-schemas" / "python" / "mandate_schemas" / "generated.py"
TYPESCRIPT_OUTPUT = ROOT / "packages" / "shared-schemas" / "typescript" / "generated.ts"
SUPPORTED_OBJECT_KEYS = {
    "type",
    "title",
    "description",
    "properties",
    "required",
    "additionalProperties",
    "minProperties",
    "maxProperties",
}
SUPPORTED_PROPERTY_KEYS = {
    "type",
    "description",
    "enum",
    "const",
    "format",
    "pattern",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "items",
    "properties",
    "required",
    "additionalProperties",
    "default",
}
HOSTNAME_PATTERN = (
    r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


def pascal_case(value: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])", value)
    return "".join(part[:1].upper() + part[1:] for part in parts if part)


def snake_case(value: str) -> str:
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()


def enum_member(value: str) -> str:
    member = snake_case(value).upper()
    if not member or member[0].isdigit():
        member = f"VALUE_{member}"
    return member


def py_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def ts_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def nullable_types(schema: dict[str, Any]) -> tuple[list[str], bool]:
    raw = schema.get("type")
    if isinstance(raw, list):
        types = [item for item in raw if item != "null"]
        return types, "null" in raw
    if isinstance(raw, str):
        return [raw], False
    if "const" in schema:
        return [], False
    raise ValueError(f"Schema has no supported type: {schema}")


def validate_keywords(schema: dict[str, Any], *, root: bool = False) -> None:
    allowed = SUPPORTED_OBJECT_KEYS if root else SUPPORTED_PROPERTY_KEYS
    unsupported = set(schema) - allowed
    if unsupported:
        raise ValueError(f"Unsupported schema keywords: {sorted(unsupported)}")
    if schema.get("type") == "object" or "properties" in schema:
        if schema.get("additionalProperties") is not False:
            raise ValueError("Every generated object must set additionalProperties=false")
        for property_schema in schema.get("properties", {}).values():
            validate_keywords(property_schema)
    if schema.get("type") == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            raise ValueError("Array schemas must contain an object-valued items schema")
        validate_keywords(items)


@dataclass
class PyContext:
    enums: list[str]
    models: list[str]
    emitted_names: set[str]


@dataclass
class TsContext:
    declarations: list[str]
    emitted_names: set[str]


def python_field_type(schema: dict[str, Any], name: str, context: PyContext) -> str:
    if "const" in schema:
        value = schema["const"]
        return f"Literal[{value!r}]"

    types, nullable = nullable_types(schema)
    if len(types) != 1:
        raise ValueError(f"Exactly one non-null type is required for {name}: {types}")
    schema_type = types[0]

    enum_values = [value for value in schema.get("enum", []) if value is not None]
    if enum_values:
        enum_name = pascal_case(name)
        if enum_name not in context.emitted_names:
            context.emitted_names.add(enum_name)
            body = "\n".join(
                f"    {enum_member(str(value))} = {py_string(str(value))}" for value in enum_values
            )
            context.enums.append(f"class {enum_name}(StrEnum):\n{body}\n")
        result = enum_name
    elif schema_type == "string":
        format_name = schema.get("format")
        if not isinstance(format_name, str):
            format_name = ""
        result = {
            "uuid": "UUID",
            "uri": "AnyHttpUrl",
            "date-time": "datetime",
            "date": "date",
        }.get(format_name, "str")
    elif schema_type == "integer":
        result = "int"
    elif schema_type == "number":
        result = "float"
    elif schema_type == "boolean":
        result = "bool"
    elif schema_type == "array":
        item_type = python_field_type(schema["items"], f"{name}Item", context)
        result = f"list[{item_type}]"
    elif schema_type == "object":
        model_name = pascal_case(name)
        emit_python_model(model_name, schema, context)
        result = model_name
    else:
        raise ValueError(f"Unsupported Python schema type {schema_type!r} for {name}")

    return f"{result} | None" if nullable else result


def python_field_expression(
    property_name: str,
    schema: dict[str, Any],
    required: bool,
) -> str:
    args: list[str] = []
    snake = snake_case(property_name)
    if required:
        args.append("...")
    elif schema.get("default") == []:
        args.append("default_factory=list")
    elif "default" in schema:
        args.append(f"default={schema['default']!r}")
    else:
        args.append("default=None")

    if snake != property_name:
        args.append(f"alias={py_string(property_name)}")

    mapping = {
        "minimum": "ge",
        "maximum": "le",
        "minLength": "min_length",
        "maxLength": "max_length",
        "minItems": "min_length",
        "maxItems": "max_length",
    }
    for keyword, pydantic_name in mapping.items():
        if keyword in schema:
            args.append(f"{pydantic_name}={schema[keyword]!r}")
    if "pattern" in schema:
        args.append(f"pattern={py_string(schema['pattern'])}")
    elif schema.get("format") == "hostname":
        args.append(f"pattern={py_string(HOSTNAME_PATTERN)}")
        if "maxLength" not in schema:
            args.append("max_length=253")
    return f"Field({', '.join(args)})"


def emit_python_model(model_name: str, schema: dict[str, Any], context: PyContext) -> None:
    if model_name in context.emitted_names:
        return
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise ValueError(f"{model_name} has no properties")
    context.emitted_names.add(model_name)

    fields: list[tuple[str, str, str]] = []
    required = set(schema.get("required", []))
    for property_name, property_schema in properties.items():
        type_name = python_field_type(
            property_schema, f"{model_name}{pascal_case(property_name)}", context
        )
        if property_name not in required and "| None" not in type_name:
            type_name = f"{type_name} | None"
        fields.append(
            (
                snake_case(property_name),
                type_name,
                python_field_expression(property_name, property_schema, property_name in required),
            )
        )

    lines = [
        f"class {model_name}(BaseModel):",
        '    """Generated from the canonical Mandate JSON Schema."""',
        "",
        '    model_config = ConfigDict(extra="forbid", populate_by_name=True)',
        "",
    ]
    for field_name, type_name, expression in fields:
        lines.append(f"    {field_name}: {type_name} = {expression}")
    context.models.append("\n".join(lines) + "\n")


def generate_python(schemas: Iterable[dict[str, Any]]) -> str:
    context = PyContext(enums=[], models=[], emitted_names=set())
    for schema in schemas:
        emit_python_model(schema["title"], schema, context)

    header = (
        "# Generated by scripts/generate_schemas.py. DO NOT EDIT.\n"
        "from __future__ import annotations\n\n"
        "from datetime import date, datetime\n"
        "from enum import StrEnum\n"
        "from typing import Literal\n"
        "from uuid import UUID\n\n"
        "from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field\n\n"
    )
    all_names = sorted(context.emitted_names)
    footer = "\n__all__ = [\n" + "".join(f'    "{name}",\n' for name in all_names) + "]\n"
    return header + "\n".join(context.enums + context.models) + footer


def zod_string(schema: dict[str, Any]) -> str:
    result = "z.string()"
    fmt = schema.get("format")
    if fmt == "uuid":
        result += ".uuid()"
    elif fmt == "uri":
        result += ".url()"
    elif fmt == "date-time":
        result += ".datetime({ offset: true })"
    elif fmt == "date":
        result += ".date()"
    elif fmt == "hostname":
        result += f".regex(new RegExp({ts_string(HOSTNAME_PATTERN)}))"
        if "maxLength" not in schema:
            result += ".max(253)"
    if "minLength" in schema:
        result += f".min({schema['minLength']})"
    if "maxLength" in schema:
        result += f".max({schema['maxLength']})"
    if "pattern" in schema:
        result += f".regex(new RegExp({ts_string(schema['pattern'])}))"
    return result


def zod_expression(schema: dict[str, Any], name: str, context: TsContext) -> str:
    if "const" in schema:
        return f"z.literal({json.dumps(schema['const'])})"

    types, nullable = nullable_types(schema)
    if len(types) != 1:
        raise ValueError(f"Exactly one non-null type is required for {name}: {types}")
    schema_type = types[0]

    enum_values = [value for value in schema.get("enum", []) if value is not None]
    if enum_values:
        values = ", ".join(ts_string(str(value)) for value in enum_values)
        result = f"z.enum([{values}])"
    elif schema_type == "string":
        result = zod_string(schema)
    elif schema_type in {"integer", "number"}:
        result = "z.number()"
        if schema_type == "integer":
            result += ".int()"
        if "minimum" in schema:
            result += f".min({schema['minimum']})"
        if "maximum" in schema:
            result += f".max({schema['maximum']})"
    elif schema_type == "boolean":
        result = "z.boolean()"
    elif schema_type == "array":
        result = f"z.array({zod_expression(schema['items'], f'{name}Item', context)})"
        if "minItems" in schema:
            result += f".min({schema['minItems']})"
        if "maxItems" in schema:
            result += f".max({schema['maxItems']})"
    elif schema_type == "object":
        nested_name = pascal_case(name)
        emit_typescript_schema(nested_name, schema, context)
        result = f"{nested_name}Schema"
    else:
        raise ValueError(f"Unsupported zod schema type {schema_type!r} for {name}")

    return f"{result}.nullable()" if nullable else result


def emit_typescript_schema(schema_name: str, schema: dict[str, Any], context: TsContext) -> None:
    if schema_name in context.emitted_names:
        return
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise ValueError(f"{schema_name} has no properties")
    context.emitted_names.add(schema_name)

    required = set(schema.get("required", []))
    field_lines: list[str] = []
    for property_name, property_schema in properties.items():
        expression = zod_expression(
            property_schema,
            f"{schema_name}{pascal_case(property_name)}",
            context,
        )
        if property_name not in required:
            if property_schema.get("default") == []:
                expression += ".default([])"
            else:
                expression += ".optional()"
        field_lines.append(f"  {property_name}: {expression},")

    context.declarations.append(
        f"export const {schema_name}Schema = z\n"
        + "  .object({\n"
        + "\n".join(field_lines)
        + "\n  })\n"
        + "  .strict();\n"
        + f"export type {schema_name} = z.infer<typeof {schema_name}Schema>;\n"
    )


def generate_typescript(schemas: Iterable[dict[str, Any]]) -> str:
    context = TsContext(declarations=[], emitted_names=set())
    for schema in schemas:
        emit_typescript_schema(schema["title"], schema, context)
    header = (
        '// Generated by scripts/generate_schemas.py. DO NOT EDIT.\nimport { z } from "zod";\n\n'
    )
    return header + "\n".join(context.declarations)


def load_schemas() -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for path in sorted(SCHEMA_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        metadata_keys = {"$schema", "$id", "x-mandate-versioned"}
        validate_keywords(
            {key: value for key, value in document.items() if key not in metadata_keys},
            root=True,
        )
        if document.get("type") != "object":
            raise ValueError(f"{path.name} must be an object schema")
        if document.get("additionalProperties") is not False:
            raise ValueError(f"{path.name} must fail closed on unknown fields")
        versioned = document.get("x-mandate-versioned", True)
        if not isinstance(versioned, bool):
            raise ValueError(f"{path.name} x-mandate-versioned must be a boolean")
        if versioned and document.get("properties", {}).get("schemaVersion", {}).get("const") != 1:
            raise ValueError(f"{path.name} must pin schemaVersion=1")
        documents.append(document)
    if not documents:
        raise ValueError(f"No schemas found in {SCHEMA_DIR}")
    return documents


def write_or_check(path: Path, expected: str, check: bool) -> bool:
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if check:
        if current != expected:
            print(
                f"Generated artifact is stale: {path.relative_to(ROOT)}",
                file=sys.stderr,
            )
            return False
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(expected, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if generated artifacts differ from the canonical schemas.",
    )
    args = parser.parse_args()

    schemas = load_schemas()
    python_output = generate_python(schemas)
    typescript_output = generate_typescript(schemas)

    valid = all(
        (
            write_or_check(PYTHON_OUTPUT, python_output, args.check),
            write_or_check(TYPESCRIPT_OUTPUT, typescript_output, args.check),
        )
    )
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
