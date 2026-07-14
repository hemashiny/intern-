"""
Persistence helpers for API snapshots, metal/FX history, crawler runs
and competitor catalogue updates.

All writes are best-effort: a database outage must never break the
live dashboard, so failures are logged and swallowed.
"""

import json
import logging
import time
from datetime import datetime

try:
    from db_connector import execute_query, execute_many
except Exception:  # pragma: no cover - import-time fallback only
    execute_query = None
    execute_many = None

logger = logging.getLogger(__name__)


def _safe(fn, *args, **kwargs):
    if execute_query is None:
        return None
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.warning('snapshot_store write failed: %s', exc)
        return None


def save_api_snapshot(source, provider, payload):
    """Persist a raw API response as a timestamped JSON blob."""
    sql = (
        'INSERT INTO api_snapshots (source, provider, payload) '
        'VALUES (%s, %s, %s)'
    )
    return _safe(
        execute_query, sql,
        (source, provider, json.dumps(payload, default=str)),
        fetch=False,
    )


def save_metal_price(metal, quote):
    """Persist a row in metal_price_history from a gold/silver quote dict."""
    sql = (
        'INSERT INTO metal_price_history '
        '(metal, price_usd_per_oz, price_inr_per_g, purity_karat, '
        ' usd_to_inr, source) VALUES (%s, %s, %s, %s, %s, %s)'
    )
    return _safe(
        execute_query, sql,
        (
            metal,
            quote.get('price_usd_per_oz'),
            quote.get('price_inr_per_gram_24k') or quote.get('price_inr_per_gram'),
            '24K' if metal == 'gold' else '999',
            quote.get('usd_to_inr_rate'),
            quote.get('source'),
        ),
        fetch=False,
    )


def save_fx_rate(base, quote, rate, source):
    sql = (
        'INSERT INTO fx_rate_history (base, quote, rate, source) '
        'VALUES (%s, %s, %s, %s)'
    )
    return _safe(execute_query, sql, (base, quote, rate, source), fetch=False)


def log_crawler_run(crawler, target, status, items_found=0,
                    items_saved=0, duration_ms=0, error_msg=None):
    sql = (
        'INSERT INTO crawler_runs '
        '(crawler, target, status, items_found, items_saved, '
        ' duration_ms, error_msg) VALUES (%s, %s, %s, %s, %s, %s, %s)'
    )
    return _safe(
        execute_query, sql,
        (crawler, target, status, items_found, items_saved,
         duration_ms, error_msg),
        fetch=False,
    )


def upsert_competitor_products(rows):
    """Insert or refresh normalised competitor product rows."""
    if not rows or execute_many is None:
        return 0
    sql = (
        'INSERT INTO competitor_products '
        '(competitor, source, category, product_name, product_url, '
        ' image_url, price_inr, discount_pct, weight_grams, purity, '
        ' rating, review_count, availability, observed_at) '
        'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) '
        'ON DUPLICATE KEY UPDATE '
        ' price_inr=VALUES(price_inr), discount_pct=VALUES(discount_pct), '
        ' rating=VALUES(rating), review_count=VALUES(review_count), '
        ' availability=VALUES(availability), image_url=VALUES(image_url), '
        ' observed_at=VALUES(observed_at)'
    )
    now = datetime.utcnow()
    params = [
        (
            r.get('competitor') or 'Unknown',
            r.get('source'),
            r.get('category'),
            (r.get('product') or '')[:500],
            (r.get('url') or '')[:1000],
            (r.get('image_url') or '')[:1000] if r.get('image_url') else None,
            r.get('price'),
            r.get('discount_pct'),
            r.get('weight_grams'),
            r.get('purity'),
            r.get('rating'),
            r.get('review_count'),
            r.get('availability'),
            now,
        )
        for r in rows if r.get('product') and r.get('url')
    ]
    if not params:
        return 0
    try:
        return execute_many(sql, params) or 0
    except Exception as exc:
        logger.warning('upsert_competitor_products failed: %s', exc)
        return 0


def save_alert(alert):
    """Persist an alert row.  Returns new alert_id or None on failure."""
    sql = (
        'INSERT INTO alerts '
        '(alert_type, severity, title, message, payload) '
        'VALUES (%s, %s, %s, %s, %s)'
    )
    return _safe(
        execute_query, sql,
        (
            alert.get('alert_type', 'info'),
            alert.get('severity', 'info'),
            (alert.get('title') or '')[:255],
            alert.get('message'),
            json.dumps(alert.get('payload') or {}, default=str),
        ),
        fetch=False,
    )


def fetch_alerts(limit=50, severity=None, alert_type=None,
                 acknowledged=None):
    """Read most recent alerts.  Returns [] when DB is unreachable."""
    if execute_query is None:
        return []
    clauses, params = [], []
    if severity:
        clauses.append('severity = %s')
        params.append(severity)
    if alert_type:
        clauses.append('alert_type = %s')
        params.append(alert_type)
    if acknowledged is not None:
        clauses.append('acknowledged = %s')
        params.append(1 if acknowledged else 0)
    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
    sql = (
        f'SELECT alert_id, alert_type, severity, title, message, payload, '
        f'acknowledged, created_at FROM alerts {where} '
        f'ORDER BY created_at DESC LIMIT %s'
    )
    params.append(int(limit))
    try:
        return execute_query(sql, tuple(params)) or []
    except Exception as exc:
        logger.warning('fetch_alerts failed: %s', exc)
        return []


def ack_alert(alert_id):
    sql = 'UPDATE alerts SET acknowledged = 1 WHERE alert_id = %s'
    return _safe(execute_query, sql, (int(alert_id),), fetch=False)


def latest_metal_history(metal, limit=2):
    """Return the most recent N metal_price_history rows for *metal*."""
    if execute_query is None:
        return []
    sql = (
        'SELECT recorded_at, price_inr_per_g, price_usd_per_oz, source '
        'FROM metal_price_history WHERE metal=%s '
        'ORDER BY recorded_at DESC LIMIT %s'
    )
    try:
        return execute_query(sql, (metal, int(limit))) or []
    except Exception as exc:
        logger.warning('latest_metal_history(%s) failed: %s', metal, exc)
        return []


def record_with_timing(fn, *args, **kwargs):
    """Run *fn* and return (result, elapsed_ms)."""
    started = time.time()
    result = fn(*args, **kwargs)
    return result, int((time.time() - started) * 1000)
