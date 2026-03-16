"""Convert between ToolDefinitions and typed Python callables.

Two directions:

1. **ToolDefinition -> callable** (for framework integration):
   Every major agent framework (Agno, LangChain, CrewAI, LangGraph) accepts
   plain Python functions and introspects their signatures to build tool schemas.
   :func:`tool_to_callable` / :func:`tools_to_callables` handle this.

2. **callable -> ToolDefinition** (for ``@t.tool`` decorator):
   :func:`callable_to_tool` introspects a typed Python function and builds
   a ToolDefinition with JSON schema derived from type hints and docstring.

Usage::

    from tract.toolkit.callables import tools_to_callables, callable_to_tool

    # Direction 1: ToolDefinition -> callable
    callables = tools_to_callables(tool_definitions)

    # Direction 2: callable -> ToolDefinition
    def my_func(query: str, limit: int = 10) -> str:
        \"\"\"Search for items.\"\"\"
        ...
    tool_def = callable_to_tool(my_func)
"""

from __future__ import annotations

import inspect
from typing import Any

from tract.toolkit.models import ToolDefinition

# JSON Schema type string -> Python type
_SCHEMA_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}

# Python type -> JSON Schema type string (reverse of above)
_TYPE_SCHEMA_MAP: dict[type, str] = {v: k for k, v in _SCHEMA_TYPE_MAP.items()}

# String annotation -> JSON Schema type (for `from __future__ import annotations`)
_STR_ANNOTATION_MAP: dict[str, str] = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "dict": "object",
    "list": "array",
}


def tool_to_callable(tool_def: ToolDefinition) -> Any:
    """Convert a single ToolDefinition into a typed Python callable.

    The returned function has:
    - ``__name__`` set to the tool name
    - ``__doc__`` set to the tool description
    - ``__signature__`` with typed parameters derived from JSON schema
    - ``__annotations__`` matching the signature

    Args:
        tool_def: A ToolDefinition with name, description, parameters schema,
            and handler.

    Returns:
        A callable with proper type annotations for framework introspection.
    """
    schema_props = tool_def.parameters.get("properties", {})
    required = set(tool_def.parameters.get("required", []))

    # Build inspect.Parameter list from JSON schema
    params: list[inspect.Parameter] = []
    annotations: dict[str, Any] = {}

    for name, prop in schema_props.items():
        py_type = _schema_to_type(prop)
        annotations[name] = py_type

        if name in required:
            params.append(
                inspect.Parameter(
                    name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=py_type,
                )
            )
        else:
            default = _schema_default(prop)
            params.append(
                inspect.Parameter(
                    name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=default,
                    annotation=py_type,
                )
            )

    annotations["return"] = str
    sig = inspect.Signature(params, return_annotation=str)

    # Capture handler in closure
    handler = tool_def.handler

    def wrapper(*args: Any, **kwargs: Any) -> str:
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        result = handler(**bound.arguments)
        return str(result) if result is not None else ""

    wrapper.__name__ = tool_def.name
    wrapper.__qualname__ = tool_def.name
    wrapper.__doc__ = tool_def.description
    wrapper.__signature__ = sig  # type: ignore[attr-defined]  # inject inspect.Signature for tool schema
    wrapper.__annotations__ = annotations

    return wrapper


def tools_to_callables(tool_defs: list[ToolDefinition]) -> list[Any]:
    """Convert a list of ToolDefinitions into typed Python callables.

    Convenience wrapper around :func:`tool_to_callable`.

    Args:
        tool_defs: List of ToolDefinition objects.

    Returns:
        List of typed callables, one per tool definition.
    """
    return [tool_to_callable(td) for td in tool_defs]


def _schema_to_type(prop: dict) -> type:
    """Map a JSON Schema property dict to a Python type."""
    schema_type = prop.get("type", "string")

    # Handle array types like ["string", "null"]
    if isinstance(schema_type, list):
        non_null = [t for t in schema_type if t != "null"]
        if non_null:
            return _SCHEMA_TYPE_MAP.get(non_null[0], str)
        return str

    return _SCHEMA_TYPE_MAP.get(schema_type, str)


def _schema_default(prop: dict) -> Any:
    """Get a default value for an optional JSON Schema property."""
    if "default" in prop:
        return prop["default"]
    return None


# ---------------------------------------------------------------------------
# Direction 2: callable -> ToolDefinition
# ---------------------------------------------------------------------------

def callable_to_tool(
    fn: Any,
    *,
    name: str | None = None,
    description: str | None = None,
) -> ToolDefinition:
    """Build a ToolDefinition from a typed Python callable.

    Introspects the function's signature, type hints, and docstring to
    produce a JSON schema and bind the handler.

    Args:
        fn: A callable with type-annotated parameters.
        name: Override the tool name (defaults to ``fn.__name__``).
        description: Override the description (defaults to the first line
            of ``fn.__doc__``, or the function name if no docstring).

    Returns:
        A ToolDefinition ready for use in the agent loop.

    Raises:
        TypeError: If *fn* is not callable.
    """
    if not callable(fn):
        raise TypeError(f"Expected a callable, got {type(fn).__name__}")

    tool_name = name or getattr(fn, "__name__", "unknown_tool")

    # Description: explicit override > docstring first line > fallback
    if description is not None:
        tool_desc = description
    elif fn.__doc__:
        tool_desc = fn.__doc__.strip().split("\n")[0]
    else:
        tool_desc = tool_name

    # Parse per-parameter descriptions from docstring (Google-style)
    param_descriptions = _parse_param_docs(fn.__doc__ or "")

    # Resolve type hints (handles `from __future__ import annotations`)
    try:
        resolved_hints = _get_type_hints(fn)
    except Exception:
        resolved_hints = {}

    # Build JSON schema from signature
    sig = inspect.signature(fn)
    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        # Resolve type: prefer get_type_hints, fall back to signature annotation
        annotation = resolved_hints.get(param_name, param.annotation)
        if annotation is inspect.Parameter.empty:
            schema_result: str | dict[str, Any] = "string"
        else:
            schema_result = _type_to_schema(annotation)

        # _type_to_schema returns either a type string or a full schema dict
        if isinstance(schema_result, dict):
            prop: dict[str, Any] = dict(schema_result)
        else:
            prop = {"type": schema_result}

        # Add description from docstring if available
        if param_name in param_descriptions:
            prop["description"] = param_descriptions[param_name]

        # Default value
        if param.default is not inspect.Parameter.empty:
            prop["default"] = param.default
        else:
            required.append(param_name)

        properties[param_name] = prop

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required

    return ToolDefinition(
        name=tool_name,
        description=tool_desc,
        parameters=schema,
        handler=fn,
    )


def _get_type_hints(fn: Any) -> dict[str, Any]:
    """Resolve type hints, handling ``from __future__ import annotations``."""
    import typing
    try:
        return typing.get_type_hints(fn)
    except Exception:
        # Fallback: return empty dict, caller uses signature annotations
        return {}


def _type_to_schema(annotation: Any) -> str | dict[str, Any]:
    """Map a Python type annotation to a JSON Schema type or schema dict.

    Handles:
    - Primitive types: ``str``, ``int``, ``float``, ``bool``, ``dict``, ``list``
    - Generic lists: ``list[str]`` → ``{"type": "array", "items": {"type": "string"}}``
    - Optional: ``Optional[str]``, ``str | None`` → ``"string"`` (nullable not
      added since most LLM APIs ignore it)
    - Literal: ``Literal["a", "b"]`` → ``{"type": "string", "enum": ["a", "b"]}``
    - Pydantic BaseModel subclasses → full JSON schema via ``model_json_schema()``
    - Stringified annotations from ``from __future__ import annotations``
    """
    import typing

    # Direct type match (primitives)
    result = _TYPE_SCHEMA_MAP.get(annotation)
    if result is not None:
        return result

    # String annotation (from __future__ import annotations)
    if isinstance(annotation, str):
        return _STR_ANNOTATION_MAP.get(annotation, "string")

    # Get the origin type for generic annotations (list[str] -> list, etc.)
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    # Handle Literal["a", "b"] -> {"type": "string", "enum": ["a", "b"]}
    if origin is typing.Literal:
        # Infer type from the first value
        if args and isinstance(args[0], int):
            return {"type": "integer", "enum": list(args)}
        return {"type": "string", "enum": list(args)}

    # Handle Optional[T] / Union[T, None] / T | None
    if origin is typing.Union:
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _type_to_schema(non_none[0])
        return "string"

    # Handle list[T] -> {"type": "array", "items": {...}}
    if origin is list:
        if args:
            items_schema = _type_to_schema(args[0])
            if isinstance(items_schema, dict):
                return {"type": "array", "items": items_schema}
            return {"type": "array", "items": {"type": items_schema}}
        return "array"

    # Handle dict[K, V] -> {"type": "object"}
    if origin is dict:
        return "object"

    # Handle Pydantic BaseModel subclasses
    try:
        from pydantic import BaseModel
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            schema = annotation.model_json_schema()
            # Strip the $defs key for cleaner inline schemas
            schema.pop("$defs", None)
            return schema
    except (ImportError, TypeError):
        pass

    return "string"


def _parse_param_docs(docstring: str) -> dict[str, str]:
    """Extract parameter descriptions from a Google-style docstring.

    Looks for an ``Args:`` section and parses lines like::

        param_name: Description text here.
        param_name (type): Description text here.

    Returns:
        Mapping of parameter name to description string.
    """
    result: dict[str, str] = {}
    if not docstring:
        return result

    lines = docstring.split("\n")
    in_args = False
    current_param: str | None = None
    current_desc: list[str] = []
    args_indent: int | None = None

    for line in lines:
        stripped = line.strip()

        if stripped.lower().startswith("args:"):
            in_args = True
            args_indent = len(line) - len(line.lstrip())
            continue

        if not in_args:
            continue

        # Detect end of Args section (new section header at same or lesser indent)
        if stripped and not line[0].isspace():
            break
        if stripped.endswith(":") and not stripped.startswith("-"):
            line_indent = len(line) - len(line.lstrip())
            if args_indent is not None and line_indent <= args_indent:
                break

        # Parse parameter line: "  name: desc" or "  name (type): desc"
        if stripped and ":" in stripped:
            # Check if this looks like a param definition (not a continuation)
            before_colon = stripped.split(":")[0].strip()
            # Remove optional (type) annotation
            param_candidate = before_colon.split("(")[0].strip()
            if param_candidate.isidentifier():
                # Save previous param
                if current_param is not None:
                    result[current_param] = " ".join(current_desc).strip()
                current_param = param_candidate
                current_desc = [stripped.split(":", 1)[1].strip()]
                continue

        # Continuation line
        if current_param is not None and stripped:
            current_desc.append(stripped)

    # Save last param
    if current_param is not None:
        result[current_param] = " ".join(current_desc).strip()

    return result
