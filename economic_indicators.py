"""
Macro-economic indicators that influence jewelry demand elasticity.

Sources (all keyless, all live):

1. **World Bank Open Data API** -- India CPI inflation (FP.CPI.TOTL.ZG),
   GDP growth (NY.GDP.MKTP.KD.ZG), and the official period-average
   USD->INR exchange rate (PA.NUS.FCRF).
2. **Frankfurter** -- secondary live FX feed (api.frankfurter.dev).
3. **FRED API** -- US 10-year treasury yield (DGS10) if FRED_API_KEY
   is provided as env var; otherwise skipped silently.

Inflation and FX trend feed the forecaster's elasticity multipliers
and surface on the Market Pulse card so the operator can see the
macro context behind each forecast.

Cached for 6 hours (World Bank publishes annually; FX hourly).
"""

import logging
import os
import time

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger(__name__)

WB_BASE = 'https://api.worldbank.org/v2/country/IN/indicator'
WB_CPI = f'{WB_BASE}/FP.CPI.TOTL.ZG?format=json&date=2019:2024'
WB_GDP = f'{WB_BASE}/NY.GDP.MKTP.KD.ZG?format=json&date=2019:2024'
WB_FX = f'{WB_BASE}/PA.NUS.FCRF?format=json&date=2019:2024'
FRANKFURTER_URL = 'https://api.frankfurter.dev/v1/latest?from=USD&to=INR,EUR,GBP,AED'
FRED_BASE = 'https://api.stlouisfed.org/fred/series/observations'

_CACHE = {'value': None, 'fetched_at': 0}
_CACHE_TTL_SECONDS = 60 * 60 * 6
_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Language': 'en-IN,en;q=0.9',
}


def _http_json(url, timeout=10):
    if requests is None:
        return None
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.debug('GET %s failed: %s', url, exc)
        return None


def _wb_latest(url):
    """World Bank returns [meta, [...rows...]]; pick the most recent non-null."""
    payload = _http_json(url)
    if not payload or not isinstance(payload, list) or len(payload) < 2:
        return None, None
    rows = payload[1] or []
    for row in rows:
        if row and row.get('value') is not None:
            try:
                return float(row['value']), str(row.get('date'))
            except (TypeError, ValueError):
                continue
    return None, None


def _frankfurter_fx():
    payload = _http_json(FRANKFURTER_URL, timeout=8)
    if not payload or not isinstance(payload.get('rates'), dict):
        return None
    return {
        'base': payload.get('base', 'USD'),
        'date': payload.get('date'),
        'rates': payload['rates'],
        'source': 'api.frankfurter.dev',
    }


def _fred_10y_treasury():
    """US 10-year treasury yield (gold proxy hedge signal). Opt-in via env."""
    key = os.getenv('FRED_API_KEY')
    if not key:
        return None
    url = (
        f'{FRED_BASE}?series_id=DGS10&api_key={key}'
        '&file_type=json&sort_order=desc&limit=1'
    )
    payload = _http_json(url, timeout=8)
    if not payload:
        return None
    obs = (payload.get('observations') or [None])[0]
    if not obs or obs.get('value') in (None, '.'):
        return None
    try:
        return {'value_pct': float(obs['value']), 'date': obs.get('date'),
                'source': 'fred.stlouisfed.org'}
    except (TypeError, ValueError):
        return None


def get_economic_indicators(force_refresh=False):
    """Aggregate live macro indicators relevant to jewelry demand."""
    now = time.time()
    if (
        not force_refresh
        and _CACHE['value'] is not None
        and now - _CACHE['fetched_at'] < _CACHE_TTL_SECONDS
    ):
        return _CACHE['value']

    cpi_val, cpi_year = _wb_latest(WB_CPI)
    gdp_val, gdp_year = _wb_latest(WB_GDP)
    fx_val, fx_year = _wb_latest(WB_FX)
    frankfurter = _frankfurter_fx()
    fred = _fred_10y_treasury()

    sources = ['api.worldbank.org']
    if frankfurter:
        sources.append('api.frankfurter.dev')
    if fred:
        sources.append('fred.stlouisfed.org')

    payload = {
        'sources': sources,
        'india_inflation': {
            'value_pct': round(cpi_val, 2) if cpi_val is not None else None,
            'year': cpi_year,
            'series': 'FP.CPI.TOTL.ZG',
        },
        'india_gdp_growth': {
            'value_pct': round(gdp_val, 2) if gdp_val is not None else None,
            'year': gdp_year,
            'series': 'NY.GDP.MKTP.KD.ZG',
        },
        'india_official_usd_inr': {
            'value': round(fx_val, 2) if fx_val is not None else None,
            'year': fx_year,
            'series': 'PA.NUS.FCRF',
        },
        'live_fx': frankfurter,
        'us_10y_treasury': fred,
    }

    _CACHE.update({'value': payload, 'fetched_at': now})
    return payload
