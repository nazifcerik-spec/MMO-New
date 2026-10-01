"""Pure economy rules: integer vendor prices, repair cost, market fee/tax and price bounds (ADR-0006)."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.game_engine.items import RARITY_ORDER


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VendorConfig(_S):
    buy_price_pct: int = Field(ge=100, le=100_000)
    sell_price_pct: int = Field(ge=0, le=100)
    stock_max_rarity: str = "fine"
    max_quantity: int = Field(ge=1, le=100_000)


class RepairConfig(_S):
    gold_per_point_base: int = Field(ge=0)
    gold_per_point_per_tier: int = Field(ge=0)
    quality_multiplier: dict[str, float] = {}


class MarketConfig(_S):
    tax_pct: float = Field(ge=0, le=50)
    listing_fee_pct: float = Field(ge=0, le=20)
    durations_h: tuple[int, ...] = Field(min_length=1)
    max_active_listings: int = Field(ge=1, le=500)
    min_unit_price: int = Field(ge=1)
    max_total_price: int = Field(ge=1, le=10**15)
    page_size: int = Field(ge=1, le=200)


class Flows(_S):
    sources: tuple[str, ...]
    sinks: tuple[str, ...]
    transfers: tuple[str, ...]


class EconomyConfig(_S):
    vendor: VendorConfig
    repair: RepairConfig
    market: MarketConfig
    flows: Flows

    @model_validator(mode="after")
    def _check(self) -> "EconomyConfig":
        if self.vendor.stock_max_rarity not in RARITY_ORDER:
            raise ValueError("unknown stock_max_rarity")
        both = (set(self.flows.sources) & set(self.flows.sinks)) | (set(self.flows.sinks) & set(self.flows.transfers))
        if both:
            raise ValueError(f"reasons classified twice: {sorted(both)}")
        return self


def vendor_buy_price(cfg: EconomyConfig, vendor_value: int, qty: int) -> int:
    return max(1, vendor_value * cfg.vendor.buy_price_pct // 100) * qty


def vendor_sell_price(cfg: EconomyConfig, vendor_value: int, qty: int) -> int:
    return vendor_value * cfg.vendor.sell_price_pct // 100 * qty


def repair_cost(cfg: EconomyConfig, missing_points: int, tier: int, quality: str | None) -> int:
    per = cfg.repair.gold_per_point_base + cfg.repair.gold_per_point_per_tier * tier
    mult = cfg.repair.quality_multiplier.get(quality or "common", 1.0)
    return int(max(0, missing_points) * per * mult + 0.5)


def listing_fee(cfg: EconomyConfig, total: int) -> int:
    return max(1, int(total * cfg.market.listing_fee_pct / 100)) if cfg.market.listing_fee_pct else 0


def market_tax(cfg: EconomyConfig, total: int) -> int:
    return int(total * cfg.market.tax_pct / 100)


def total_price(cfg: EconomyConfig, unit_price: int, qty: int) -> int:
    """Validated integer total; raises ValueError on non-positive, below-minimum or overflowing prices."""
    if not isinstance(unit_price, int) or not isinstance(qty, int) or qty < 1:
        raise ValueError("invalid price or quantity")
    if unit_price < cfg.market.min_unit_price:
        raise ValueError("price below minimum")
    total = unit_price * qty
    if total > cfg.market.max_total_price:
        raise ValueError("price above maximum")
    return total


def classify(cfg: EconomyConfig, reason: str, delta: int) -> str:
    if reason in cfg.flows.transfers:
        return "transfer"
    if reason in cfg.flows.sources:
        return "source"
    if reason in cfg.flows.sinks:
        return "sink"
    return "source" if delta > 0 else "sink"
