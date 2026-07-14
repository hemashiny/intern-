"""External data integrations for the jewelry prediction platform."""

from .gold_price import get_gold_price
from .silver_price import get_silver_price
from .currency_fx import get_fx_rates, get_usd_to_inr
from .holiday_calendar import get_upcoming_festivals
from .competitor_crawler import get_competitor_prices
from .trend_monitor import get_trending_categories
from .ibja_rates import get_ibja_rates
from .economic_indicators import get_economic_indicators
from . import snapshot_store

__all__ = [
    'get_gold_price',
    'get_silver_price',
    'get_fx_rates',
    'get_usd_to_inr',
    'get_upcoming_festivals',
    'get_competitor_prices',
    'get_trending_categories',
    'get_ibja_rates',
    'get_economic_indicators',
    'snapshot_store',
]
