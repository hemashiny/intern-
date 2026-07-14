"""
Gold price integration backed by a single live spot-price API.

Sources:

1. **Spot price** -- https://api.gold-api.com/price/XAU (free, no key, USD/oz).
2. **Live USD->INR FX** -- https://open.er-api.com/v6/latest/USD (free, no key)
   used to derive the INR/gram figure.
3. **Static fallback** if the network is unreachable.

The returned dictionary always contains both USD spot fields and INR/gram
fields; the INR values are derived from spot USD via the live FX rate.
Cached for 15 minutes.
"""

import os
import time
import logging

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger(__name__)

GOLD_API_URL = 'https://api.gold-api.com/price/XAU'
FX_URL = 'https://open.er-api.com/v6/latest/USD'

USD_TO_INR_DEFAULT = 83.5
GRAMS_PER_TROY_OUNCE = 31.1035

_CACHE = {'value': None, 'fetched_at': 0}
_CACHE_TTL_SECONDS = 60 * 15
_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-IN,en;q=0.9',
}


def _http_json(url, headers=None, timeout=6):
    if requests is None:
        return None
    try:
        resp = requests.get(url, headers={**_HEADERS, **(headers or {})}, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.debug('GET %s failed: %s', url, exc)
        return None


def _fetch_usd_to_inr():
    """Live USD->INR rate; env override wins, then live API, then default."""
    env = os.getenv('USD_TO_INR_RATE')
    if env:
        try:
            return float(env), 'env'
        except ValueError:
            pass
    payload = _http_json(FX_URL)
    if payload and isinstance(payload.get('rates'), dict):
        rate = payload['rates'].get('INR')
        if rate:
            try:
                return float(rate), FX_URL
            except (TypeError, ValueError):
                pass
    return USD_TO_INR_DEFAULT, 'static-default'


def _fetch_spot_usd_oz():
    """Fetch spot gold USD/oz from gold-api.com; return (usd_per_oz, source_url) or (None, None)."""
    payload = _http_json(GOLD_API_URL)
    if payload:
        try:
            price = float(payload.get('price') or 0)
            if price > 0:
                return price, GOLD_API_URL
        except (TypeError, ValueError):
            pass
    return None, None


def _static_fallback():
    return {
        'source': 'static-fallback',
        'sources': ['static-fallback'],
        'currency_base': 'USD',
        'price_usd_per_oz': 2350.0,
        'price_usd_per_gram': round(2350.0 / GRAMS_PER_TROY_OUNCE, 2),
        'price_inr_per_gram_24k': round(2350.0 / GRAMS_PER_TROY_OUNCE * USD_TO_INR_DEFAULT, 2),
        'price_inr_per_gram_22k': round(2350.0 / GRAMS_PER_TROY_OUNCE * USD_TO_INR_DEFAULT * 22 / 24, 2),
        'usd_to_inr_rate': USD_TO_INR_DEFAULT,
        'fx_source': 'static-default',
        'reference_url': GOLD_API_URL,
    }


def _build_quote():
    """Combine spot USD/oz + live FX into a single quote dictionary."""
    usd_to_inr, fx_source = _fetch_usd_to_inr()
    usd_oz, spot_source = _fetch_spot_usd_oz()

    if usd_oz is None:
        return _static_fallback()

    price_usd_gram = usd_oz / GRAMS_PER_TROY_OUNCE
    inr_24k = price_usd_gram * usd_to_inr
    inr_22k = inr_24k * (22 / 24)

    sources = [s for s in (spot_source, fx_source) if s]

    return {
        'source': GOLD_API_URL,
        'sources': sources,
        'currency_base': 'USD',
        'price_usd_per_oz': round(usd_oz, 2),
        'price_usd_per_gram': round(price_usd_gram, 2),
        'price_inr_per_gram_24k': round(inr_24k, 2),
        'price_inr_per_gram_22k': round(inr_22k, 2),
        'usd_to_inr_rate': round(usd_to_inr, 4),
        'fx_source': fx_source,
        'inr_rate_source': 'derived-from-usd',
        'reference_url': GOLD_API_URL,
    }


def get_gold_price(force_refresh=False):
    """Return the current gold price as a structured dictionary."""
    now = time.time()
    if (
        not force_refresh
        and _CACHE['value'] is not None
        and now - _CACHE['fetched_at'] < _CACHE_TTL_SECONDS
    ):
        return _CACHE['value']

    try:
        quote = _build_quote()
    except Exception as exc:
        logger.warning('Gold price assembly failed (%s); using fallback.', exc)
        quote = _static_fallback()

    _CACHE.update({'value': quote, 'fetched_at': now})
    return quote

