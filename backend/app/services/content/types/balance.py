"""Balance configs: named JSON blobs, each validated by a registered schema. Engines read published values."""

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.game_engine.afk import AfkBalance
from app.game_engine.combat.models import CombatConfig
from app.game_engine.progression import ProgressionConfig
from app.models.content import BalanceConfig
from app.services.content.registry import ContentType, Issue, register


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Later phases register more schemas (progression, combat, risk profiles, ...).
BALANCE_SCHEMAS: dict[str, type[BaseModel]] = {
    "afk": AfkBalance,
    "progression": ProgressionConfig,
    "combat": CombatConfig,
}


class BalanceData(Strict):
    data: dict[str, Any]


async def _validate_balance(_db: AsyncSession, code: str, data: dict[str, Any]) -> list[Issue]:
    schema = BALANCE_SCHEMAS.get(code)
    if schema is None:
        return [Issue("error", "unknown_balance_config", f"No schema registered for balance config '{code}'")]
    try:
        schema.model_validate(data["data"])
    except ValidationError as exc:
        return [Issue("error", "schema", e["msg"], "data." + ".".join(str(p) for p in e["loc"])) for e in exc.errors()]
    return []


BALANCE_TYPE = register(
    ContentType(
        entity_type="balance_config",
        model=BalanceConfig,
        data_schema=BalanceData,
        l10n_prefix="balance",
        edit_permission="balance.edit",
        publish_permission="content.publish",
        validators=(_validate_balance,),
    )
)


async def get_published_balance[T: BaseModel](db: AsyncSession, code: str, schema: type[T]) -> T:
    row = (
        await db.execute(select(BalanceConfig).where(BalanceConfig.code == code, BalanceConfig.status == "published"))
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"Balance config '{code}' is not published")
    return schema.model_validate(row.data)
