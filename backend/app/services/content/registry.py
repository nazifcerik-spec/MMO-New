"""Registry of content entity types managed by the generic content service (ADR-0008)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError


@dataclass(frozen=True, slots=True)
class Issue:
    level: Literal["error", "warning"]
    code: str
    message: str
    path: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"level": self.level, "code": self.code, "message": self.message, "path": self.path}


Validator = Callable[[AsyncSession, str, dict[str, Any]], Awaitable[list[Issue]]]


@dataclass(frozen=True)
class ContentType:
    entity_type: str
    model: Any  # a Base subclass using ContentMixin
    data_schema: type[BaseModel]
    l10n_prefix: str
    edit_permission: str = "content.edit"
    publish_permission: str = "content.publish"
    validators: tuple[Validator, ...] = ()
    public: bool = False
    # Optional custom (de)serialization for entities with child rows; default copies schema fields.
    serialize: Callable[[Any], dict[str, Any]] | None = None
    apply: Callable[[Any, dict[str, Any]], None] | None = None
    searchable_fields: tuple[str, ...] = field(default_factory=tuple)

    def to_data(self, row: Any) -> dict[str, Any]:
        if self.serialize:
            return self.serialize(row)
        raw = {name: getattr(row, name) for name in self.data_schema.model_fields}
        return self.data_schema.model_validate(raw).model_dump(mode="json")

    def apply_data(self, row: Any, data: dict[str, Any]) -> None:
        if self.apply:
            self.apply(row, data)
            return
        for name, value in data.items():
            setattr(row, name, value)


CONTENT_TYPES: dict[str, ContentType] = {}


def register(ct: ContentType) -> ContentType:
    CONTENT_TYPES[ct.entity_type] = ct
    return ct


def get_type(entity_type: str) -> ContentType:
    ct = CONTENT_TYPES.get(entity_type)
    if ct is None:
        raise NotFoundError(f"Unknown content type '{entity_type}'")
    return ct
