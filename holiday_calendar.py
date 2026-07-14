"""
Holiday and festival integration.

Live-first, fallback-second strategy:

1. **CalendarLabs scrape** (https://www.calendarlabs.com/holidays/india/{year}/)
   for the authoritative Indian festival list -- Diwali, Dhanteras, Akshaya
   Tritiya, etc. -- which the legacy date.nager.at provider no longer ships
   for India (returns HTTP 204).
2. **date.nager.at REST API** for non-IN countries (still reliable globally).
3. **Static curated list** of jewelry-relevant Indian festivals as last resort.

Override the primary scrape URL with ``HOLIDAY_SCRAPE_URL`` (template that
accepts ``{year}``) or the API with ``HOLIDAY_API_URL``.
"""

import os
import re
import time
import logging
from datetime import date, datetime, timedelta

try:
    import requests
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

logger = logging.getLogger(__name__)

DEFAULT_COUNTRY = os.getenv('HOLIDAY_COUNTRY', 'IN')
DEFAULT_API_TEMPLATE = 'https://date.nager.at/api/v3/PublicHolidays/{year}/{country}'
DEFAULT_SCRAPE_TEMPLATE = 'https://www.calendarlabs.com/holidays/india/{year}'

JEWELRY_FESTIVAL_HINTS = {
    'diwali': 'Peak gold-buying period; stock signature collections.',
    'deepavali': 'Peak gold-buying period; stock signature collections.',
    'dhanteras': 'Traditional gold-buying day; ensure coin and small-ticket stock.',
    'akshaya tritiya': 'Auspicious for gold purchases; promote high-margin pieces.',
    'navaratri': 'Bridal and ethnic jewelry demand rises.',
    'durga puja': 'Bridal and ethnic jewelry demand rises.',
    'raksha bandhan': 'Gifting spike for bracelets and bangles.',
    'karva chauth': 'Bridal gold and diamond demand spikes.',
    'karwa chauth': 'Bridal gold and diamond demand spikes.',
    'eid': 'Festive gifting; promote bangles, chains and earrings.',
    'pongal': 'Regional gold gifting tradition.',
    'onam': 'Regional gold gifting tradition.',
    'gudi padwa': 'Auspicious new year; gold-purchase tradition in Maharashtra.',
    'ugadi': 'Auspicious new year; gold-purchase tradition in the Deccan.',
    'baisakhi': 'Harvest festival; jewelry gifting in Punjab and the North.',
    'christmas': 'Gifting spike for fine jewelry and diamond pendants.',
    'valentine': 'Diamond and couple-ring promotions perform well.',
    'dussehra': 'Auspicious for new purchases; gold-buying tradition.',
    'vijayadashami': 'Auspicious for new purchases; gold-buying tradition.',
    'makar sankranti': 'Festive gifting and gold purchase tradition.',
}

_CACHE = {'value': None, 'fetched_at': 0, 'year': None, 'country': None,
          'sources': []}
_CACHE_TTL_SECONDS = 60 * 60 * 6
_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-IN,en;q=0.9',
}

_DATE_RE = re.compile(
    r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s+(\d{4})',
    re.I,
)


def _fallback_holidays(today):
    """Static curated list of jewelry-relevant Indian festivals."""
    samples = [
        ('Akshaya Tritiya', date(today.year, 4, 30)),
        ('Eid-ul-Fitr', date(today.year, 3, 21)),
        ('Raksha Bandhan', date(today.year, 8, 9)),
        ('Onam', date(today.year, 9, 5)),
        ('Navaratri', date(today.year, 10, 2)),
        ('Dussehra', date(today.year, 10, 11)),
        ('Karva Chauth', date(today.year, 10, 20)),
        ('Dhanteras', date(today.year, 10, 29)),
        ('Diwali', date(today.year, 10, 31)),
        ('Christmas', date(today.year, 12, 25)),
    ]
    horizon = today + timedelta(days=400)
    rows = []
    for name, day in samples:
        if day < today:
            day = day.replace(year=today.year + 1)
        if day <= horizon:
            rows.append({'localName': name, 'name': name,
                         'date': day.isoformat(), 'source': 'static-fallback'})
    return rows


def _tag(name):
    lower = name.lower()
    for key, hint in JEWELRY_FESTIVAL_HINTS.items():
        if key in lower:
            return hint
    return None


def _scrape_calendarlabs(year):
    """Scrape the public Indian holiday table for ``year``."""
    if requests is None or BeautifulSoup is None:
        return []
    template = os.getenv('HOLIDAY_SCRAPE_URL', DEFAULT_SCRAPE_TEMPLATE)
    url = template.format(year=year)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=12)
        resp.raise_for_status()
    except Exception as exc:
        logger.debug('CalendarLabs fetch failed for %s: %s', year, exc)
        return []
    soup = BeautifulSoup(resp.text, 'html.parser')
    tables = soup.select('table.hlist_tab')
    if not tables:
        return []
    rows = []
    for tr in tables[0].find_all('tr'):
        cells = tr.find_all(['td', 'th'])
        if len(cells) < 3:
            continue
        date_text = cells[1].get_text(' ', strip=True)
        name = cells[2].get_text(' ', strip=True)
        if not name or len(name) > 200:
            continue
        m = _DATE_RE.search(date_text)
        if not m:
            continue
        try:
            day = datetime.strptime(
                f'{m.group(1)[:3].title()} {int(m.group(2))} {m.group(3)}',
                '%b %d %Y',
            ).date()
        except ValueError:
            continue
        rows.append({'localName': name, 'name': name,
                     'date': day.isoformat(), 'source': url})
    return rows


def _fetch_nager(year, country):
    """Fetch the global holiday API for non-IN countries."""
    if requests is None:
        return []
    template = os.getenv('HOLIDAY_API_URL', DEFAULT_API_TEMPLATE)
    try:
        url = template.format(year=year, country=country)
        resp = requests.get(url, headers=_HEADERS, timeout=8)
        if resp.status_code == 204 or not (resp.text or '').strip():
            return []
        resp.raise_for_status()
        return [{**h, 'source': url} for h in (resp.json() or [])]
    except Exception as exc:
        logger.debug('Holiday API fetch failed for %s/%s: %s', year, country, exc)
        return []



def _persist(target, status, items_found, duration_ms, error_msg=None):
    try:
        from . import snapshot_store
        snapshot_store.log_crawler_run(
            crawler='holiday',
            target=target,
            status=status,
            items_found=items_found,
            items_saved=items_found if status == 'ok' else 0,
            duration_ms=duration_ms,
            error_msg=error_msg,
        )
    except Exception:
        pass


def _collect_holidays(today, country):
    """Combine live sources for the current and following year."""
    rows, sources, error = [], [], None
    started = time.time()
    for year in (today.year, today.year + 1):
        try:
            if country.upper() == 'IN':
                scraped = _scrape_calendarlabs(year)
                if scraped:
                    rows.extend(scraped)
                    sources.append(scraped[0]['source'])
                    continue
            api_rows = _fetch_nager(year, country)
            if api_rows:
                rows.extend(api_rows)
                sources.append(api_rows[0]['source'])
        except Exception as exc:
            error = str(exc)
            logger.warning('Holiday collection failed for %s: %s', year, exc)
    duration_ms = int((time.time() - started) * 1000)
    if rows:
        _persist('calendarlabs+nager' if country.upper() == 'IN' else 'nager',
                 'ok', len(rows), duration_ms, error)
        return rows, sources
    _persist(country, 'failed', 0, duration_ms, error or 'no rows')
    fallback = _fallback_holidays(today)
    return fallback, ['static-fallback']


def get_upcoming_festivals(days_ahead=90, country=None, force_refresh=False):
    """Return upcoming festivals within ``days_ahead`` days for ``country``."""
    today = date.today()
    horizon = today + timedelta(days=days_ahead)
    country = (country or DEFAULT_COUNTRY).upper()

    now = time.time()
    fresh = (
        not force_refresh
        and _CACHE['value'] is not None
        and _CACHE['year'] == today.year
        and _CACHE['country'] == country
        and now - _CACHE['fetched_at'] < _CACHE_TTL_SECONDS
    )
    if fresh:
        holidays = _CACHE['value']
        sources = _CACHE['sources']
    else:
        holidays, sources = _collect_holidays(today, country)
        _CACHE.update({'value': holidays, 'fetched_at': now,
                       'year': today.year, 'country': country,
                       'sources': sources})

    seen, enriched = set(), []
    for h in holidays:
        try:
            d = datetime.strptime(h['date'], '%Y-%m-%d').date()
        except (KeyError, ValueError):
            continue
        if not (today <= d <= horizon):
            continue
        name = h.get('localName') or h.get('name') or 'Holiday'
        key = (d.isoformat(), name.lower())
        if key in seen:
            continue
        seen.add(key)
        enriched.append({
            'name': name,
            'date': d.isoformat(),
            'days_away': (d - today).days,
            'jewelry_impact': _tag(name),
            'is_jewelry_relevant': _tag(name) is not None,
            'source': h.get('source'),
        })
    enriched.sort(key=lambda x: x['days_away'])
    return enriched

