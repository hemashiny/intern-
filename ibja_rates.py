"""
IBJA (Indian Bullion and Jewellers Association) rates crawler.

Scrapes https://ibjarates.com/ for the official India daily bullion
fixings: Gold 999 (24K), Gold 995, Gold 916 (22K), Gold 750 (18K),
Gold 585 (14K), Silver 999 and Platinum 999. IBJA publishes rates per
10 grams in INR (pre-GST, ex-duty). This module converts to per-gram
and exposes both AM and PM fixings when available.

Cached for 15 minutes; static fallback if scrape fails.
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

IBJA_URL = 'https://ibjarates.com/'

_CACHE = {'value': None, 'fetched_at': 0}
_CACHE_TTL_SECONDS = 60 * 15
_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-IN,en;q=0.9',
}

PURITY_LABELS = [
    ('silver', 'silver_999'),
    ('platinum', 'platinum_999'),
    ('999', 'gold_999_24k'),
    ('995', 'gold_995'),
    ('916', 'gold_916_22k'),
    ('750', 'gold_750_18k'),
    ('585', 'gold_585_14k'),
]

PER_KG_KEYS = {'silver_999'}


def _to_per_gram(value, purity_key):
    """IBJA quotes gold/platinum per 10g and silver per kg; normalize to per-gram INR."""
    try:
        divisor = 1000.0 if purity_key in PER_KG_KEYS else 10.0
        return round(float(value) / divisor, 2)
    except (TypeError, ValueError):
        return None


def _scrape_ibja():
    """Parse the first rate table on ibjarates.com."""
    if requests is None or BeautifulSoup is None:
        return None
    try:
        resp = requests.get(IBJA_URL, headers=_HEADERS, timeout=12)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning('IBJA fetch failed: %s', exc)
        return None

    soup = BeautifulSoup(resp.text, 'html.parser')
    table = soup.find('table')
    if not table:
        return None

    rates = {'am': {}, 'pm': {}}
    rows = table.find_all('tr')
    for row in rows:
        cells = [c.get_text(' ', strip=True) for c in row.find_all(['th', 'td'])]
        if len(cells) < 3:
            continue
        label = cells[0].lower()
        purity_key = None
        for key, mapped in PURITY_LABELS:
            if key in label:
                purity_key = mapped
                break
        if not purity_key:
            continue
        am = re.sub(r'[^0-9.]', '', cells[1]) if len(cells) > 1 else ''
        pm = re.sub(r'[^0-9.]', '', cells[2]) if len(cells) > 2 else ''
        if am:
            rates['am'][purity_key] = _to_per_gram(am, purity_key)
        if pm:
            rates['pm'][purity_key] = _to_per_gram(pm, purity_key)
    return rates if (rates['am'] or rates['pm']) else None


def _static_fallback():
    return {
        'source': 'static-fallback',
        'reference_url': IBJA_URL,
        'unit': 'inr_per_gram',
        'rates_am': {},
        'rates_pm': {},
        'gold_999_24k_inr_per_g': None,
        'gold_916_22k_inr_per_g': None,
        'silver_999_inr_per_g': None,
        'platinum_999_inr_per_g': None,
    }


def get_ibja_rates(force_refresh=False):
    """Return latest IBJA bullion fixings as a structured dictionary."""
    now = time.time()
    if (
        not force_refresh
        and _CACHE['value'] is not None
        and now - _CACHE['fetched_at'] < _CACHE_TTL_SECONDS
    ):
        return _CACHE['value']

    scraped = _scrape_ibja()
    if not scraped:
        quote = _static_fallback()
    else:
        latest = scraped['pm'] or scraped['am']
        quote = {
            'source': IBJA_URL,
            'reference_url': IBJA_URL,
            'unit': 'inr_per_gram',
            'rates_am': scraped['am'],
            'rates_pm': scraped['pm'],
            'gold_999_24k_inr_per_g': latest.get('gold_999_24k'),
            'gold_995_inr_per_g': latest.get('gold_995'),
            'gold_916_22k_inr_per_g': latest.get('gold_916_22k'),
            'gold_750_18k_inr_per_g': latest.get('gold_750_18k'),
            'gold_585_14k_inr_per_g': latest.get('gold_585_14k'),
            'silver_999_inr_per_g': latest.get('silver_999'),
            'platinum_999_inr_per_g': latest.get('platinum_999'),
        }

    _CACHE.update({'value': quote, 'fetched_at': now})
    return quote
