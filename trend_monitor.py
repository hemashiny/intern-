"""
Trend monitor for jewelry categories.

Layered live-data strategy:

1. **Google Trends** via the optional ``pytrends`` package -- best signal when
   available.
2. **Real Indian jewelry e-commerce** via the competitor crawler (BlueStone,
   CaratLane, Tanishq) -- product rating + discount drives an interest score
   that reflects actual buying behaviour in the Indian market.
3. **DummyJSON public REST API** as a generic catalogue fallback.
4. **Internal engagement** computed from the platform's own data -- last-resort
   fallback so the dashboard always renders.

Set ``TREND_KEYWORDS`` in the environment to override the Google Trends keyword
list, e.g. ``TREND_KEYWORDS="diamond ring,gold necklace,pearl earrings"``.
"""

import os
import time
import logging

try:
    import requests
except ImportError:
    requests = None

try:
    from pytrends.request import TrendReq
except ImportError:
    TrendReq = None

logger = logging.getLogger(__name__)

DEFAULT_KEYWORDS = [
    'diamond ring', 'gold necklace', 'gold bangle',
    'pearl earrings', 'rose gold ring', 'platinum band',
]
DUMMYJSON_URL = 'https://dummyjson.com/products/category/womens-jewellery'
CACHE_TTL_SECONDS = 6 * 60 * 60
_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; JewelryPredictor/1.0)',
    'Accept-Language': 'en-IN,en;q=0.9',
}

_cache = {'ts': 0, 'rows': []}


def _internal_trend_rows(internal_signals):
    rows = []
    for category, score in (internal_signals or {}).items():
        rows.append({
            'keyword': category,
            'category': category,
            'interest_score': round(float(score), 2),
            'growth_pct': round(float(score) - 50, 2),
            'source': 'internal-engagement',
        })
    rows.sort(key=lambda r: r['interest_score'], reverse=True)
    return rows


def _scrape_dummyjson_trends():
    if requests is None:
        return []
    try:
        resp = requests.get(DUMMYJSON_URL, headers=_HEADERS, timeout=8)
        resp.raise_for_status()
        items = resp.json().get('products', []) or []
    except Exception as exc:
        logger.debug('DummyJSON trends fetch failed: %s', exc)
        return []
    if not items:
        return []
    discounts = [float(i.get('discountPercentage') or 0) for i in items]
    mean_discount = sum(discounts) / len(discounts) if discounts else 0.0
    rows = []
    for item in items:
        rating = float(item.get('rating') or 0)
        discount = float(item.get('discountPercentage') or 0)
        interest = min(100.0, rating * 20.0 + discount)
        growth = round(discount - mean_discount, 2)
        rows.append({
            'keyword': item.get('title') or 'Jewelry item',
            'category': item.get('category') or 'Jewelry',
            'interest_score': round(interest, 2),
            'growth_pct': growth,
            'source': 'dummyjson.com',
            'url': f"https://dummyjson.com/products/{item.get('id')}",
        })
    rows.sort(key=lambda r: r['interest_score'], reverse=True)
    return rows


def _real_jewelry_trends(limit=30):
    """Derive trending jewelry signals from real Indian e-commerce catalogues.

    Uses the competitor crawler (BlueStone / CaratLane / Tanishq scraped via
    JSON-LD) so the keywords reflect actual listings on Indian jewelry sites.
    Interest = rating * 20 + discount; growth = discount delta vs catalogue mean.
    """
    try:
        from .competitor_crawler import get_competitor_prices
    except Exception as exc:
        logger.debug('competitor crawler import failed: %s', exc)
        return []
    try:
        items = get_competitor_prices(limit=limit) or []
    except Exception as exc:
        logger.debug('competitor crawler call failed: %s', exc)
        return []
    real = [i for i in items if (i.get('source') or '').endswith('.com')
            and i.get('source') not in ('dummyjson.com', 'fakestoreapi.com')]
    if not real:
        real = items
    if not real:
        return []
    discounts = [float(i.get('discount_pct') or 0) for i in real]
    mean_discount = sum(discounts) / len(discounts) if discounts else 0.0
    prices = [float(i.get('price') or 0) for i in real if i.get('price')]
    mean_price = sum(prices) / len(prices) if prices else 0.0
    rows = []
    for item in real:
        rating = float(item.get('rating') or 0)
        discount = float(item.get('discount_pct') or 0)
        review_count = float(item.get('review_count') or 0)
        review_boost = min(20.0, review_count / 5.0) if review_count else 0.0
        interest = min(100.0, rating * 18.0 + discount + review_boost)
        if interest <= 0 and item.get('price') and mean_price:
            interest = min(80.0, 40.0 + 20.0 * (mean_price / max(item['price'], 1)))
        growth = round(discount - mean_discount, 2) if discount else round(
            (mean_price - float(item.get('price') or mean_price)) / max(mean_price, 1) * 100, 2)
        rows.append({
            'keyword': item.get('product') or 'Listed item',
            'category': item.get('category') or 'Jewelry',
            'interest_score': round(interest, 2),
            'growth_pct': growth,
            'source': item.get('source') or 'competitor-crawler',
            'url': item.get('url'),
            'price_inr': item.get('price'),
            'competitor': item.get('competitor'),
        })
    rows.sort(key=lambda r: r['interest_score'], reverse=True)
    return rows


def _pytrends_rows(geo):
    if TrendReq is None:
        return []
    keywords_env = os.getenv('TREND_KEYWORDS')
    keywords = (
        [k.strip() for k in keywords_env.split(',') if k.strip()]
        if keywords_env else DEFAULT_KEYWORDS
    )
    try:
        pytrends = TrendReq(hl='en-US', tz=330)
        pytrends.build_payload(keywords, timeframe='today 3-m', geo=geo)
        interest = pytrends.interest_over_time()
        if interest.empty:
            return []
        rows = []
        for keyword in keywords:
            if keyword not in interest.columns:
                continue
            series = interest[keyword].astype(float)
            recent = series.tail(7).mean() if len(series) >= 7 else series.mean()
            earlier = series.head(7).mean() if len(series) >= 14 else series.mean()
            growth = ((recent - earlier) / earlier * 100.0) if earlier > 0 else 0.0
            rows.append({
                'keyword': keyword,
                'category': keyword,
                'interest_score': round(float(recent), 2),
                'growth_pct': round(float(growth), 2),
                'source': 'google-trends',
                'url': f'https://trends.google.com/trends/explore?q={keyword.replace(" ", "+")}&geo={geo}',
            })
        rows.sort(key=lambda r: r['interest_score'], reverse=True)
        return rows
    except Exception as exc:
        logger.warning('Google Trends fetch failed: %s', exc)
        return []


def _log_run(target, status, items_found, duration_ms, error_msg=None):
    try:
        from . import snapshot_store
        snapshot_store.log_crawler_run(
            crawler='trends', target=target, status=status,
            items_found=items_found, items_saved=items_found if status == 'ok' else 0,
            duration_ms=duration_ms, error_msg=error_msg,
        )
    except Exception:
        pass


def get_trending_categories(internal_signals=None, geo='IN', force_refresh=False):
    """Return trending jewelry keywords with interest scores."""
    if force_refresh or time.time() - _cache['ts'] > CACHE_TTL_SECONDS or not _cache['rows']:
        started = time.time()
        rows = _pytrends_rows(geo)
        sources_used = ['google-trends'] if rows else []

        real = _real_jewelry_trends()
        if real:
            seen = {r['keyword'].lower() for r in rows}
            rows.extend(r for r in real if r['keyword'].lower() not in seen)
            sources_used.append('competitor-crawler')

        scraped = _scrape_dummyjson_trends()
        if scraped:
            seen = {r['keyword'].lower() for r in rows}
            rows.extend(r for r in scraped if r['keyword'].lower() not in seen)
            sources_used.append('dummyjson.com')

        duration_ms = int((time.time() - started) * 1000)
        if rows:
            _cache['rows'] = rows
            _cache['ts'] = time.time()
            _log_run('+'.join(sources_used) or 'none', 'ok', len(rows), duration_ms)
        else:
            _log_run('all-sources', 'failed', 0, duration_ms, 'no live trend rows')

    if _cache['rows']:
        return list(_cache['rows'])
    return _internal_trend_rows(internal_signals)
