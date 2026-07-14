"""
Silver price integration with layered live-data strategy.

Sources (combined in priority order, all live, no API keys required):

1. **GoodReturns crawler** -- https://www.goodreturns.in/silver-rates/
   for the live INR/gram silver rate in India.
2. **Spot price APIs** (USD/oz):
       * https://api.gold-api.com/price/XAG  (free, no key)
       * https://data-asg.goldprice.org/dbXRates/USD
3. **Live USD->INR FX** via the shared currency_fx module.
4. **Static fallback** if every network call fails.

Returns the same shape as gold_price.get_gold_price for symmetry with the
metal_price_history table.  Cached for 15 minutes.
"""

import logging
import re
import time

try:
    import requests
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

logger = logging.getLogger(__name__)

SILVER_API_URL = 'https://api.gold-api.com/price/XAG'
GOLDPRICE_ORG_URL = 'https://data-asg.goldprice.org/dbXRates/USD'
GOODRETURNS_SILVER_URL = 'https://www.goodreturns.in/silver-rates/'

GRAMS_PER_TROY_OUNCE = 31.1035
USD_TO_INR_DEFAULT = 83.5

_CACHE = {'value': None, 'fetched_at': 0}
_CACHE_TTL_SECONDS = 60 * 15
_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-IN,en;q=0.9',
}

_INR_PER_GRAM_RE = re.compile(
    r'(?:&#8377;|\u20b9|Rs\.?\s*)\s*([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.[0-9]+)?)'
    r'\s*per\s*gram',
    flags=re.IGNORECASE,
)


def _http_json(url, timeout=8):
    if requests is None:
        return None
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.debug('GET %s failed: %s', url, exc)
        return None


def _fetch_spot_usd_oz():
    data = _http_json(SILVER_API_URL)
    if data and data.get('price'):
        try:
            return float(data['price']), SILVER_API_URL
        except (TypeError, ValueError):
            pass
    data = _http_json(GOLDPRICE_ORG_URL)
    if data:
        for item in data.get('items', []) or []:
            if (item.get('xagPrice') or item.get('xagprice')):
                try:
                    return float(item.get('xagPrice') or item.get('xagprice')), GOLDPRICE_ORG_URL
                except (TypeError, ValueError):
                    continue
    return None, None


def _scrape_goodreturns():
    if requests is None or BeautifulSoup is None:
        return None
    try:
        resp = requests.get(GOODRETURNS_SILVER_URL, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
    except Exception as exc:
        logger.debug('GoodReturns silver fetch failed: %s', exc)
        return None
    matches = _INR_PER_GRAM_RE.findall(resp.text or '')
    for raw in matches:
        try:
            value = float(raw.replace(',', ''))
            if 30 <= value <= 5000:
                return value
        except ValueError:
            continue
    return None


def _static_fallback():
    return {
        'source': 'static-fallback',
        'price_usd_per_oz': 28.50,
        'price_usd_per_gram': round(28.50 / GRAMS_PER_TROY_OUNCE, 3),
        'price_inr_per_gram': round(28.50 / GRAMS_PER_TROY_OUNCE * USD_TO_INR_DEFAULT, 2),
        'price_inr_per_gram_24k': round(28.50 / GRAMS_PER_TROY_OUNCE * USD_TO_INR_DEFAULT, 2),
        'usd_to_inr_rate': USD_TO_INR_DEFAULT,
        'reference_url': SILVER_API_URL,
    }


def _build_quote():
    from .currency_fx import get_usd_to_inr  # local import to avoid cycles
    usd_oz, spot_source = _fetch_spot_usd_oz()
    inr_gram = _scrape_goodreturns()
    usd_to_inr, fx_source = get_usd_to_inr()

    if usd_oz is None and inr_gram is None:
        return _static_fallback()

    price_usd_gram = (usd_oz / GRAMS_PER_TROY_OUNCE) if usd_oz else None
    if inr_gram is None and price_usd_gram is not None:
        inr_gram = price_usd_gram * usd_to_inr
    if usd_oz is None and inr_gram is not None:
        price_usd_gram = inr_gram / usd_to_inr
        usd_oz = price_usd_gram * GRAMS_PER_TROY_OUNCE

    primary = GOODRETURNS_SILVER_URL if _scrape_goodreturns is not None and inr_gram else spot_source
    return {
        'source': primary,
        'price_usd_per_oz': round(usd_oz, 2) if usd_oz else None,
        'price_usd_per_gram': round(price_usd_gram, 3) if price_usd_gram else None,
        'price_inr_per_gram': round(inr_gram, 2) if inr_gram else None,
        'price_inr_per_gram_24k': round(inr_gram, 2) if inr_gram else None,
        'usd_to_inr_rate': round(usd_to_inr, 4),
        'fx_source': fx_source,
        'reference_url': primary or SILVER_API_URL,
    }


def get_silver_price(force_refresh=False):
    now = time.time()
    if (not force_refresh and _CACHE['value'] is not None
            and now - _CACHE['fetched_at'] < _CACHE_TTL_SECONDS):
        return _CACHE['value']
    try:
        quote = _build_quote()
    except Exception as exc:
        logger.warning('Silver price assembly failed: %s', exc)
        quote = _static_fallback()
    _CACHE.update({'value': quote, 'fetched_at': now})
    return quote
