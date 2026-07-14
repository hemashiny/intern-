"""
Alerts engine.

Scans live prediction output, latest market data and recent crawler runs
to surface actionable notifications for the business owner.  Every
generated alert carries a stable `dedupe_key` so re-running the engine
within a short window does not flood the DB with duplicates.

All DB calls are best-effort: alerts are still returned in-memory when
persistence fails, so the dashboard always works.
"""

import logging
from datetime import datetime, date

from integrations import (
    get_gold_price, get_silver_price, get_upcoming_festivals,
    snapshot_store,
)

logger = logging.getLogger(__name__)

ENGINE_VERSION = 'alerts-engine-v1.0.0'

GOLD_SPIKE_PCT = 1.5        # day-over-day % move that triggers an alert
SILVER_SPIKE_PCT = 2.5
FESTIVAL_LEAD_DAYS = 14
DEMAND_SPIKE_THRESHOLD = 90  # prediction_percentage above this = spike


def _alert(alert_type, severity, title, message, payload=None,
           dedupe_key=None):
    return {
        'alert_type': alert_type,
        'severity': severity,
        'title': title,
        'message': message,
        'payload': payload or {},
        'dedupe_key': dedupe_key or f'{alert_type}:{title}',
        'generated_at': datetime.utcnow().isoformat() + 'Z',
    }


def _metal_spike_alert(metal, threshold_pct):
    rows = snapshot_store.latest_metal_history(metal, limit=2)
    if len(rows) < 2:
        return None
    latest, previous = rows[0], rows[1]
    try:
        new = float(latest['price_inr_per_g'])
        old = float(previous['price_inr_per_g'])
    except (TypeError, ValueError):
        return None
    if old <= 0:
        return None
    pct = round(((new - old) / old) * 100.0, 2)
    if abs(pct) < threshold_pct:
        return None
    direction = 'surged' if pct > 0 else 'dropped'
    severity = 'critical' if abs(pct) >= threshold_pct * 2 else 'warning'
    return _alert(
        alert_type=f'{metal}_spike',
        severity=severity,
        title=f'{metal.title()} price {direction} {abs(pct)}%',
        message=(f'{metal.title()} moved from ₹{old:,.2f}/g to ₹{new:,.2f}/g '
                 f'({pct:+.2f}%).  Consider repricing or hedging.'),
        payload={'metal': metal, 'old': old, 'new': new, 'pct_change': pct,
                 'source': latest.get('source')},
        dedupe_key=f'{metal}_spike:{date.today().isoformat()}',
    )


def _stock_shortage_alerts(predictions):
    out = []
    for p in predictions:
        if not p.get('inventory_risk'):
            continue
        days = int(p.get('predicted_days_to_sale') or 30)
        stock = int(p.get('stock_quantity') or 0)
        severity = 'critical' if stock <= 2 else 'warning'
        out.append(_alert(
            'stock_shortage', severity,
            title=f"Low stock: {p['product_name']}",
            message=(f"{p['product_name']} ({p['item_no']}) likely sells out "
                     f"in ~{days} day(s); only {stock} unit(s) on hand."),
            payload={'product_id': p['product_id'], 'item_no': p['item_no'],
                     'category': p['category'], 'stock_quantity': stock,
                     'predicted_days_to_sale': days,
                     'prediction_percentage': p.get('prediction_percentage')},
            dedupe_key=f"stock_shortage:{p['product_id']}",
        ))
    return out


def _dead_stock_alerts(predictions):
    out = []
    for p in predictions:
        if not p.get('dead_stock_alert'):
            continue
        out.append(_alert(
            'dead_stock', 'warning',
            title=f"Dead stock: {p['product_name']}",
            message=(f"{p['product_name']} ({p['item_no']}) has stagnated "
                     'with low engagement.  Run a clearance offer or bundle.'),
            payload={'product_id': p['product_id'], 'item_no': p['item_no'],
                     'stock_quantity': p.get('stock_quantity'),
                     'historical_sales': p.get('historical_sales')},
            dedupe_key=f"dead_stock:{p['product_id']}",
        ))
    return out


def _demand_spike_alerts(predictions):
    out = []
    for p in predictions:
        pct = float(p.get('prediction_percentage') or 0)
        if pct < DEMAND_SPIKE_THRESHOLD:
            continue
        out.append(_alert(
            'demand_spike', 'info',
            title=f"High demand: {p['product_name']}",
            message=(f"{p['product_name']} ({p['item_no']}) is predicted to "
                     f"convert at {pct:.0f}%.  Promote prominently and "
                     'check stock cover.'),
            payload={'product_id': p['product_id'], 'item_no': p['item_no'],
                     'prediction_percentage': pct,
                     'stock_quantity': p.get('stock_quantity')},
            dedupe_key=f"demand_spike:{p['product_id']}:{date.today().isoformat()}",
        ))
    return out


def _festival_alerts():
    out = []
    festivals = get_upcoming_festivals(days_ahead=FESTIVAL_LEAD_DAYS) or []
    today = date.today()
    for fest in festivals:
        if not fest.get('is_jewelry_relevant'):
            continue
        try:
            fdate = datetime.strptime(fest['date'], '%Y-%m-%d').date()
        except Exception:
            continue
        days_to_go = (fdate - today).days
        if days_to_go < 0 or days_to_go > FESTIVAL_LEAD_DAYS:
            continue
        uplift = fest.get('jewelry_uplift_pct') or 25
        out.append(_alert(
            'festival_window', 'info',
            title=f"{fest['name']} in {days_to_go} day(s)",
            message=(f"{fest['name']} on {fest['date']} typically lifts "
                     f"jewelry demand ~{uplift}%.  Prepare festival offers "
                     'and ensure stock cover.'),
            payload={'festival': fest['name'], 'date': fest['date'],
                     'days_to_go': days_to_go, 'uplift_pct': uplift},
            dedupe_key=f"festival_window:{fest['name']}:{fest['date']}",
        ))
    return out



def _crawler_failure_alerts():
    """Surface crawler runs that failed in the last 24h."""
    if snapshot_store.execute_query is None:
        return []
    try:
        rows = snapshot_store.execute_query(
            "SELECT crawler, target, status, error_msg, started_at "
            "FROM crawler_runs WHERE status='failed' "
            "AND started_at >= (NOW() - INTERVAL 1 DAY) "
            "ORDER BY started_at DESC LIMIT 10"
        ) or []
    except Exception as exc:
        logger.debug('crawler failure scan failed: %s', exc)
        return []
    out = []
    for r in rows:
        out.append(_alert(
            'crawler_failure', 'warning',
            title=f"Crawler failed: {r['crawler']}",
            message=(f"{r['crawler']} run targeting {r.get('target') or 'n/a'} "
                     f"failed: {(r.get('error_msg') or 'unknown error')[:200]}"),
            payload={'crawler': r['crawler'], 'target': r.get('target'),
                     'started_at': str(r.get('started_at'))},
            dedupe_key=f"crawler_failure:{r['crawler']}:{r.get('started_at')}",
        ))
    return out


class AlertsEngine:
    """Generate, persist and read alerts."""

    def __init__(self, prediction_engine=None):
        self.prediction_engine = prediction_engine

    def _predictions(self):
        if self.prediction_engine is None:
            return []
        try:
            return self.prediction_engine.predict() or []
        except Exception as exc:
            logger.debug('predictions unavailable for alerts: %s', exc)
            return []

    def generate(self, persist=False):
        alerts = []
        predictions = self._predictions()

        gold = _metal_spike_alert('gold', GOLD_SPIKE_PCT)
        if gold:
            alerts.append(gold)
        silver = _metal_spike_alert('silver', SILVER_SPIKE_PCT)
        if silver:
            alerts.append(silver)

        alerts.extend(_stock_shortage_alerts(predictions))
        alerts.extend(_dead_stock_alerts(predictions))
        alerts.extend(_demand_spike_alerts(predictions))
        alerts.extend(_festival_alerts())
        alerts.extend(_crawler_failure_alerts())

        severity_rank = {'critical': 0, 'warning': 1, 'info': 2}
        alerts.sort(key=lambda a: severity_rank.get(a['severity'], 9))

        saved = 0
        if persist:
            for a in alerts:
                if snapshot_store.save_alert(a) is not None:
                    saved += 1

        counts = {}
        for a in alerts:
            counts[a['alert_type']] = counts.get(a['alert_type'], 0) + 1

        return {
            'engine_version': ENGINE_VERSION,
            'generated_at': datetime.utcnow().isoformat() + 'Z',
            'total': len(alerts),
            'persisted': saved,
            'counts_by_type': counts,
            'alerts': alerts,
        }

    def list_alerts(self, limit=50, severity=None, alert_type=None,
                    acknowledged=None):
        return snapshot_store.fetch_alerts(
            limit=limit, severity=severity,
            alert_type=alert_type, acknowledged=acknowledged)

    def acknowledge(self, alert_id):
        snapshot_store.ack_alert(alert_id)
        return {'alert_id': alert_id, 'acknowledged': True}
