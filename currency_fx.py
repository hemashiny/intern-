"""
Currency exchange rate integration.

Primary live source: https://open.er-api.com/v6/latest/USD (free, no key).
Backup live source: https://api.exchangerate-api.com/v4/latest/USD (free).
Static fallback: USD->INR=83.5, EUR=0.92, GBP=0.79, JPY=157.0, AED=3.67.

Cached for 30 minutes in-process.
"""

import logging
import time

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger(__name__)

ER_API_URL = 'https://open.er-api.com/v6/latest/USD'
EXCHANGERATE_API_URL = 'https://api.exchangerate-api.com/v4/latest/USD'

DEFAULT_QUOTES = ('INR', 'EUR', 'GBP', 'JPY', 'AED', 'SGD')
_STATIC = {'INR': 83.5, 'EUR': 0.92, 'GBP': 0.79,
           'JPY': 157.0, 'AED': 3.67, 'SGD': 1.35}

_CACHE = {'value': None, 'fetched_at': 0}
_CACHE_TTL_SECONDS = 60 * 30


def _fetch_rates():
    """Return (rates_dict, source_url) or (None, None) on failure."""
    if requests is None:
        return None, None
    for url in (ER_API_URL, EXCHANGERATE_API_URL):
        try:
            resp = requests.get(url, timeout=6)
            resp.raise_for_status()
            data = resp.json()
            rates = data.get('rates') or data.get('conversion_rates')
            if isinstance(rates, dict) and rates.get('INR'):
                return rates, url
        except Exception as exc:
            logger.debug('FX fetch %s failed: %s', url, exc)
    return None, None


def _build_payload():
    rates, source = _fetch_rates()
    if rates is None:
        return {
            'base': 'USD',
            'source': 'static-fallback',
            'rates': dict(_STATIC),
            'usd_to_inr': _STATIC['INR'],
        }
    quotes = {q: float(rates[q]) for q in DEFAULT_QUOTES if q in rates}
    return {
        'base': 'USD',
        'source': source,
        'rates': quotes,
        'usd_to_inr': float(rates.get('INR') or _STATIC['INR']),
    }


def get_fx_rates(force_refresh=False):
    now = time.time()
    if (not force_refresh and _CACHE['value'] is not None
            and now - _CACHE['fetched_at'] < _CACHE_TTL_SECONDS):
        return _CACHE['value']
    payload = _build_payload()
    _CACHE.update({'value': payload, 'fetched_at': now})
    return payload


def get_usd_to_inr(force_refresh=False):
    """Convenience helper used by silver/gold modules."""
    payload = get_fx_rates(force_refresh=force_refresh)
    return float(payload.get('usd_to_inr') or _STATIC['INR']), payload.get('source')
