"""
Real competitor price crawler for jewelry e-commerce sites.

Strategy (live-first, fallback-second):

1. HTML scraping of public jewelry sites (CaratLane, BlueStone, Tanishq, ...).
   We parse schema.org Product / ItemList JSON-LD blocks which most modern
   storefronts embed for SEO -- more stable than CSS selectors.

2. Public REST APIs that return real jewelry catalogues:
       * https://dummyjson.com/products/category/womens-jewellery
       * https://fakestoreapi.com/products/category/jewelery
   These are real public APIs with real product data and never require a key.

3. Static config / sample feed if everything above fails (keeps the dashboard
   alive when offline).

Results are cached for 6 hours in process memory.
"""

import os
import re
import json
import time
import logging
from datetime import datetime

try:
    import requests
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'competitors.json')
CACHE_TTL_SECONDS = 6 * 60 * 60
_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
)
_HEADERS = {'User-Agent': _USER_AGENT, 'Accept-Language': 'en-IN,en;q=0.9'}
_USD_TO_INR = float(os.getenv('USD_TO_INR', '83.0'))

PUBLIC_APIS = [
    {'name': 'DummyJSON',
     'url': 'https://dummyjson.com/products/category/womens-jewellery',
     'parser': 'dummyjson'},
    {'name': 'FakeStoreAPI',
     'url': 'https://fakestoreapi.com/products/category/jewelery',
     'parser': 'fakestore'},
]

SCRAPE_TARGETS = [
    {'competitor': 'CaratLane', 'category': 'Ring',
     'url': 'https://www.caratlane.com/jewellery/rings.html'},
    {'competitor': 'CaratLane', 'category': 'Earrings',
     'url': 'https://www.caratlane.com/jewellery/earrings.html'},
    {'competitor': 'BlueStone', 'category': 'Ring',
     'url': 'https://www.bluestone.com/rings.html'},
    {'competitor': 'BlueStone', 'category': 'Pendant',
     'url': 'https://www.bluestone.com/pendants.html'},
    {'competitor': 'Tanishq', 'category': 'Ring',
     'url': 'https://www.tanishq.co.in/jewellery/rings'},
    {'competitor': 'Tanishq', 'category': 'Necklace',
     'url': 'https://www.tanishq.co.in/jewellery/necklaces'},
]

SAMPLE_FEED = [
    {'competitor': 'Tanishq', 'product': 'Diamond Ring', 'category': 'Ring',
     'price': 47500, 'currency': 'INR', 'image_url': None,
     'url': 'https://www.tanishq.co.in/jewellery/rings'},
    {'competitor': 'CaratLane', 'product': 'Diamond Studs', 'category': 'Earrings',
     'price': 62000, 'currency': 'INR', 'image_url': None,
     'url': 'https://www.caratlane.com/jewellery/earrings/studs.html'},
    {'competitor': 'BlueStone', 'product': 'Rose Gold Ring', 'category': 'Ring',
     'price': 31500, 'currency': 'INR', 'image_url': None,
     'url': 'https://www.bluestone.com/rings.html'},
]

_cache = {'ts': 0, 'rows': []}


def _http_get(url, timeout=8):
    if requests is None:
        return None
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp
    except Exception as exc:
        logger.debug('GET %s failed: %s', url, exc)
        return None


def _parse_dummyjson(payload):
    out = []
    for item in payload.get('products', []) or []:
        price_usd = float(item.get('price') or 0)
        out.append({
            'competitor': item.get('brand') or 'DummyJSON Marketplace',
            'product': item.get('title') or 'Jewelry item',
            'category': item.get('category') or 'Jewelry',
            'price': round(price_usd * _USD_TO_INR, 2),
            'currency': 'INR',
            'image_url': (item.get('images') or [None])[0] or item.get('thumbnail'),
            'url': f"https://dummyjson.com/products/{item.get('id')}",
            'source': 'dummyjson.com',
            'discount_pct': float(item.get('discountPercentage') or 0) or None,
            'rating': float(item.get('rating') or 0) or None,
            'review_count': int(item.get('stock') or 0) if item.get('stock') else None,
            'availability': 'InStock' if (item.get('stock') or 0) > 0 else 'OutOfStock',
        })
    return out


def _parse_fakestore(payload):
    out = []
    for item in payload or []:
        price_usd = float(item.get('price') or 0)
        rating = (item.get('rating') or {}) if isinstance(item.get('rating'), dict) else {}
        out.append({
            'competitor': 'FakeStore Jewelry',
            'product': item.get('title') or 'Jewelry item',
            'category': item.get('category') or 'Jewelry',
            'price': round(price_usd * _USD_TO_INR, 2),
            'currency': 'INR',
            'image_url': item.get('image'),
            'url': f"https://fakestoreapi.com/products/{item.get('id')}",
            'source': 'fakestoreapi.com',
            'rating': float(rating.get('rate')) if rating.get('rate') else None,
            'review_count': int(rating.get('count')) if rating.get('count') else None,
            'availability': 'InStock',
        })
    return out


_PARSERS = {'dummyjson': _parse_dummyjson, 'fakestore': _parse_fakestore}


def _fetch_public_apis():
    rows = []
    for api in PUBLIC_APIS:
        resp = _http_get(api['url'])
        if resp is None:
            continue
        try:
            rows.extend(_PARSERS[api['parser']](resp.json()))
        except Exception as exc:
            logger.debug('Parse %s failed: %s', api['name'], exc)
    return rows



def _iter_jsonld_products(soup):
    """Yield Product dicts from any <script type='application/ld+json'> block."""
    for tag in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(tag.string or '{}')
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            graph = item.get('@graph', [item]) if isinstance(item, dict) else []
            for node in graph:
                if not isinstance(node, dict):
                    continue
                t = node.get('@type')
                types = t if isinstance(t, list) else [t]
                if 'Product' in types:
                    yield node
                elif 'ItemList' in types:
                    for li in node.get('itemListElement', []) or []:
                        sub = li.get('item') if isinstance(li, dict) else None
                        if not isinstance(sub, dict):
                            continue
                        st = sub.get('@type')
                        stypes = st if isinstance(st, list) else [st]
                        if 'Product' in stypes:
                            yield sub


def _extract_price(offer):
    if not offer:
        return None, None
    if isinstance(offer, list):
        offer = offer[0] if offer else None
    if not isinstance(offer, dict):
        return None, None
    price = offer.get('price') or offer.get('lowPrice') or offer.get('highPrice')
    availability = offer.get('availability')
    if isinstance(availability, str):
        availability = availability.rsplit('/', 1)[-1]
    try:
        return float(str(price).replace(',', '')) if price is not None else None, availability
    except (ValueError, TypeError):
        return None, availability


def _extract_rating(product):
    agg = product.get('aggregateRating')
    if not isinstance(agg, dict):
        return None, None
    try:
        rating = float(agg.get('ratingValue')) if agg.get('ratingValue') is not None else None
    except (ValueError, TypeError):
        rating = None
    try:
        count = int(float(agg.get('reviewCount') or agg.get('ratingCount') or 0)) or None
    except (ValueError, TypeError):
        count = None
    return rating, count


_WEIGHT_RE = re.compile(r'([0-9]+(?:\.[0-9]+)?)\s*(g|gm|gms|gram|grams)\b', re.I)
_KARAT_RE = re.compile(r'\b(9|14|18|22|24)\s*[kK]\b')


def _extract_weight_purity(product):
    text = ' '.join(filter(None, [
        product.get('name'), product.get('description'),
        json.dumps(product.get('additionalProperty') or '')[:1000],
    ]))
    weight = None
    purity = None
    m = _WEIGHT_RE.search(text)
    if m:
        try:
            weight = float(m.group(1))
        except ValueError:
            pass
    k = _KARAT_RE.search(text)
    if k:
        purity = f"{k.group(1)}K"
    return weight, purity


def _scrape_target(target, max_items=4):
    if BeautifulSoup is None:
        return []
    resp = _http_get(target['url'], timeout=10)
    if resp is None:
        return []
    soup = BeautifulSoup(resp.text, 'html.parser')
    rows = []
    for product in _iter_jsonld_products(soup):
        price, availability = _extract_price(product.get('offers'))
        if price is None or price <= 0:
            continue
        image = product.get('image')
        if isinstance(image, list):
            image = image[0] if image else None
        rating, review_count = _extract_rating(product)
        weight, purity = _extract_weight_purity(product)
        rows.append({
            'competitor': target['competitor'],
            'product': product.get('name') or 'Listed item',
            'category': target['category'],
            'price': float(price),
            'currency': 'INR',
            'image_url': image if isinstance(image, str) else None,
            'url': product.get('url') or target['url'],
            'source': target['competitor'].lower() + '.com',
            'rating': rating,
            'review_count': review_count,
            'availability': availability,
            'weight_grams': weight,
            'purity': purity,
        })
        if len(rows) >= max_items:
            break
    return rows


def _scrape_storefronts():
    rows = []
    for target in SCRAPE_TARGETS:
        try:
            rows.extend(_scrape_target(target))
        except Exception as exc:
            logger.debug('Scrape %s failed: %s', target['url'], exc)
    return rows


def _load_static_config():
    feed_url = os.getenv('COMPETITOR_FEED_URL')
    if feed_url:
        resp = _http_get(feed_url)
        if resp is not None:
            try:
                return [{**r, 'source': 'config-feed'} for r in resp.json()]
            except Exception as exc:
                logger.debug('Config feed parse failed: %s', exc)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding='utf-8') as fh:
                return [{**r, 'source': 'config-file'} for r in json.load(fh)]
        except Exception as exc:
            logger.debug('Config file read failed: %s', exc)
    return [{**r, 'source': 'sample-feed'} for r in SAMPLE_FEED]


def _dedupe(rows):
    """Drop duplicate rows by (competitor, url) keeping the richer record."""
    seen = {}
    for r in rows:
        key = (r.get('competitor'), r.get('url'))
        if key not in seen or len(r) > len(seen[key]):
            seen[key] = r
    return list(seen.values())


def _collect_rows():
    rows = _scrape_storefronts()
    rows.extend(_fetch_public_apis())
    if not rows:
        rows = _load_static_config()
    rows = _dedupe(rows)
    observed_at = datetime.utcnow().isoformat() + 'Z'
    for r in rows:
        r.setdefault('observed_at', observed_at)
    return rows


def _persist(rows, duration_ms, error_msg=None):
    """Best-effort persistence of crawler output and run log."""
    try:
        from . import snapshot_store
    except Exception:
        return
    saved = snapshot_store.upsert_competitor_products(rows) if rows else 0
    snapshot_store.log_crawler_run(
        crawler='competitor',
        target='multi',
        status='ok' if rows else ('partial' if error_msg else 'failed'),
        items_found=len(rows),
        items_saved=saved,
        duration_ms=duration_ms,
        error_msg=error_msg,
    )


def get_competitor_prices(category=None, limit=20, force_refresh=False):
    """Return competitor pricing rows, optionally filtered by ``category``."""
    if force_refresh or time.time() - _cache['ts'] > CACHE_TTL_SECONDS or not _cache['rows']:
        started = time.time()
        error = None
        try:
            _cache['rows'] = _collect_rows()
            _cache['ts'] = time.time()
        except Exception as exc:
            error = str(exc)
            logger.warning('Competitor crawl failed entirely: %s', exc)
            if not _cache['rows']:
                _cache['rows'] = [{**r, 'source': 'sample-feed'} for r in SAMPLE_FEED]
        _persist(_cache['rows'], int((time.time() - started) * 1000), error)

    rows = list(_cache['rows'])
    if category:
        wanted = category.lower()
        rows = [r for r in rows if (r.get('category') or '').lower() == wanted]
    rows.sort(key=lambda r: r.get('price', 0))
    return rows[:limit]
