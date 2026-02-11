"""Custom SQLAlchemy TypeDecorator for Pydantic model serialization.

PydanticJSON bridges Pydantic models to SQLAlchemy JSON columns,
handling serialization (model_dump) and deserialization (model_validate)
transparently.
"""

from __future__ import annotations

from typing import Any, Type

from pydantic import BaseModel
from sqlalchemy import JSON, TypeDecorator
from sqlalchemy.engine import Dialect


class PydanticJSON(TypeDecorator):
    """Store Pydantic models as JSON in SQLite.

    Transparently converts between Pydantic model instances and
    JSON-serializable dicts for storage.
    """

    impl = JSON
    cache_ok = True

    def __init__(self, pydantic_type: Type[BaseModel]) -> None:
        super().__init__()
        self.pydantic_type = pydantic_type

    def process_bind_param(self, value: BaseModel | None, dialect: Dialect) -> dict | None:
        """Convert Pydantic model to dict for storage."""
        if value is None:
            return None
        return value.model_dump(mode="json")

    def process_result_value(self, value: dict | str | None, dialect: Dialect) -> BaseModel | None:
        """Convert stored dict/string back to Pydantic model."""
        if value is None:
            return None
        if isinstance(value, str):
            return self.pydantic_type.model_validate_json(value)
        return self.pydantic_type.model_validate(value)

    def coerce_compared_value(self, op: Any, value: Any) -> Any:
        """Ensure comparisons use the underlying JSON type."""
        return self.impl.coerce_compared_value(op, value)
