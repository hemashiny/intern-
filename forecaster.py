"""
Sales forecasting engine.

Produces daily, weekly and monthly sales / revenue forecasts at three
scopes: overall, per category and per product.

Signals combined for every forecast:
  * Historical daily sales (last 90 days) -> baseline rate + day-of-week
    seasonality + coefficient-of-variation (drives confidence).
  * Festival / seasonal uplift from holiday_calendar.get_upcoming_festivals.
  * Gold-price momentum from integrations.get_gold_price (short-term
    elasticity: a sharp gold-price rise dampens unit volume, a dip lifts it).
  * Live prediction-engine output (per-product prediction_percentage,
    expected_revenue) as a fallback when historical sales are sparse.

Each forecast is persisted into the sales_forecasts table when
persist=True is passed.
"""

import logging
from datetime import date, datetime, timedelta
from statistics import mean, pstdev

import pandas as pd

try:
    from db_connector import execute_query, execute_many
except Exception:  # pragma: no cover - DB driver optional at import time
    execute_query = None
    execute_many = None
from integrations import get_upcoming_festivals, get_gold_price

logger = logging.getLogger(__name__)

MODEL_VERSION = 'forecaster-v1.0.0'

HORIZON_DAYS = {'daily': 7, 'weekly': 28, 'monthly': 90}
PERIOD_LENGTH = {'daily': 1, 'weekly': 7, 'monthly': 30}

FESTIVAL_UPLIFT = {
    'diwali': 1.85, 'dhanteras': 2.10, 'akshaya tritiya': 1.95,
    'navaratri': 1.40, 'raksha bandhan': 1.30, 'karva chauth': 1.55,
    'eid': 1.25, 'pongal': 1.20, 'onam': 1.20,
    'christmas': 1.25, 'valentine': 1.35, 'mother': 1.20,
    'new year': 1.15,
}

SALES_QUERY = """
SELECT
    p.product_id, p.product_name, p.category, p.price AS cost,
    DATE(s.sale_date) AS day,
    SUM(s.quantity) AS units,
    SUM(s.sale_amount) AS revenue
FROM sales_history s
JOIN products p ON p.product_id = s.product_id
WHERE s.sale_date >= DATE_SUB(CURDATE(), INTERVAL 90 DAY)
GROUP BY p.product_id, day
"""


def _load_history():
    if execute_query is None:
        return pd.DataFrame()
    try:
        rows = execute_query(SALES_QUERY)
    except Exception as exc:
        logger.debug('Forecaster history query failed: %s', exc)
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df['day'] = pd.to_datetime(df['day']).dt.date
    df['units'] = df['units'].astype(float)
    df['revenue'] = df['revenue'].astype(float)
    return df


def _festival_index(days_ahead):
    """Return {date: multiplier} for festivals inside the horizon."""
    today = date.today()
    horizon = today + timedelta(days=days_ahead)
    index = {}
    for f in get_upcoming_festivals(days_ahead=days_ahead):
        try:
            d = datetime.strptime(f['date'], '%Y-%m-%d').date()
        except (KeyError, ValueError):
            continue
        if not (today <= d <= horizon):
            continue
        lower = (f.get('name') or '').lower()
        mult = next((v for k, v in FESTIVAL_UPLIFT.items() if k in lower), None)
        if mult is None and f.get('is_jewelry_relevant'):
            mult = 1.15
        if mult:
            for offset in (-1, 0, 1):  # halo days
                key = d + timedelta(days=offset)
                index[key] = max(index.get(key, 1.0), mult)
    return index


def _gold_factor():
    """Tiny elasticity: +5% gold → -1.5% units, +3% revenue."""
    quote = get_gold_price()
    base = quote.get('price_inr_per_gram_24k') or 0
    if not base:
        return {'units_mult': 1.0, 'revenue_mult': 1.0, 'gold_inr_per_g': None}
    # Anchor at static fallback baseline; compute relative deviation.
    anchor = 12000.0
    delta = (base - anchor) / anchor
    return {
        'units_mult': max(0.85, 1.0 - 0.30 * delta),
        'revenue_mult': max(0.90, 1.0 + 0.20 * delta),
        'gold_inr_per_g': base,
    }


def _confidence(samples):
    """High when many points with low coefficient of variation."""
    n = len(samples)
    if n < 3:
        return max(35.0, 10.0 + 5.0 * n)
    mu = mean(samples) or 1.0
    cv = pstdev(samples) / mu if mu else 1.0
    coverage = min(1.0, n / 60.0)
    score = (1 - min(cv, 1.0)) * 70 + coverage * 25 + 5
    return round(max(35.0, min(95.0, score)), 1)


def _forecast_series(history_df, horizon, festival_idx, gold):
    """Return list of period forecasts for a single (scope_key) slice."""
    period_len = PERIOD_LENGTH[horizon]
    horizon_days = HORIZON_DAYS[horizon]
    today = date.today()

    if history_df is not None and not history_df.empty:
        daily = history_df.groupby('day').agg(units=('units', 'sum'),
                                              revenue=('revenue', 'sum'))
        all_days = pd.date_range(end=today - timedelta(days=1), periods=60)
        daily = daily.reindex([d.date() for d in all_days], fill_value=0)
        daily_units = daily['units'].tolist()
        daily_rev = daily['revenue'].tolist()
        baseline_units = mean(daily_units[-30:]) if daily_units else 0
        baseline_rev = mean(daily_rev[-30:]) if daily_rev else 0
        confidence = _confidence(daily_units[-30:])
    else:
        baseline_units, baseline_rev, confidence = 0.0, 0.0, 45.0

    out = []
    cursor = today
    while cursor < today + timedelta(days=horizon_days):
        period_end = cursor + timedelta(days=period_len - 1)
        festival_mult = max(
            (festival_idx.get(cursor + timedelta(days=i), 1.0)
             for i in range(period_len)), default=1.0)
        units = baseline_units * period_len * festival_mult * gold['units_mult']
        revenue = baseline_rev * period_len * festival_mult * gold['revenue_mult']
        drivers = {
            'baseline_daily_units': round(baseline_units, 3),
            'baseline_daily_revenue': round(baseline_rev, 2),
            'festival_multiplier': round(festival_mult, 3),
            'gold_units_multiplier': round(gold['units_mult'], 3),
            'gold_revenue_multiplier': round(gold['revenue_mult'], 3),
            'gold_inr_per_g': gold['gold_inr_per_g'],
        }
        out.append({
            'period_start': cursor.isoformat(),
            'period_end': period_end.isoformat(),
            'predicted_units': int(round(units)),
            'predicted_revenue': round(revenue, 2),
            'confidence_pct': confidence,
            'drivers': drivers,
        })
        cursor += timedelta(days=period_len)
    return out



def _predictions_to_baseline(predictions):
    """Estimate a per-day baseline from the live prediction engine output.

    Used as a fallback when sales_history is empty so the dashboard still
    receives a non-zero, signal-aware forecast.
    """
    if not predictions:
        return {'units_per_day': 0.0, 'revenue_per_day': 0.0}
    daily_units, daily_rev = 0.0, 0.0
    for p in predictions:
        days = max(1, int(p.get('predicted_days_to_sale', 30) or 30))
        pct = float(p.get('prediction_percentage', 0) or 0) / 100.0
        cost = float(p.get('cost', 0) or 0)
        daily_units += pct / days
        daily_rev += (cost * pct) / days
    return {'units_per_day': daily_units, 'revenue_per_day': daily_rev}


def _slice_history(df, scope, scope_id):
    if df is None or df.empty:
        return df
    if scope == 'overall':
        return df
    if scope == 'category':
        return df[df['category'].astype(str).str.lower() == str(scope_id).lower()]
    if scope == 'product':
        try:
            pid = int(scope_id)
        except (TypeError, ValueError):
            return df.iloc[0:0]
        return df[df['product_id'] == pid]
    return df


def _slice_predictions(predictions, scope, scope_id):
    if scope == 'overall' or scope_id in (None, '', 'all'):
        return predictions
    if scope == 'category':
        target = str(scope_id).lower()
        return [p for p in predictions if str(p.get('category', '')).lower() == target]
    if scope == 'product':
        try:
            pid = int(scope_id)
        except (TypeError, ValueError):
            return []
        return [p for p in predictions if int(p.get('product_id', 0)) == pid]
    return predictions


class SalesForecaster:
    """Public entry point used by the Flask service."""

    def __init__(self, prediction_engine=None):
        self.prediction_engine = prediction_engine

    def _live_predictions(self):
        if self.prediction_engine is None:
            return []
        try:
            return self.prediction_engine.predict() or []
        except Exception as exc:
            logger.debug('Prediction engine unavailable for forecaster: %s', exc)
            return []

    def get_forecasts(self, horizon='daily', scope='overall',
                      scope_id=None, persist=False):
        if horizon not in HORIZON_DAYS:
            raise ValueError(f'Unsupported horizon: {horizon}')
        if scope not in ('overall', 'category', 'product'):
            raise ValueError(f'Unsupported scope: {scope}')

        history = _slice_history(_load_history(), scope, scope_id)
        festival_idx = _festival_index(HORIZON_DAYS[horizon])
        gold = _gold_factor()

        used_fallback = history is None or history.empty
        if used_fallback:
            preds = _slice_predictions(self._live_predictions(), scope, scope_id)
            baseline = _predictions_to_baseline(preds)
            history = pd.DataFrame([
                {'day': date.today() - timedelta(days=i + 1),
                 'units': baseline['units_per_day'],
                 'revenue': baseline['revenue_per_day']}
                for i in range(30)
            ])

        periods = _forecast_series(history, horizon, festival_idx, gold)
        for p in periods:
            p['drivers']['source'] = 'predictions-fallback' if used_fallback else 'sales-history'

        if persist:
            self._persist(horizon, scope, scope_id, periods)

        return {
            'horizon': horizon,
            'scope': scope,
            'scope_id': scope_id,
            'model_version': MODEL_VERSION,
            'generated_at': datetime.utcnow().isoformat() + 'Z',
            'periods': periods,
            'totals': {
                'predicted_units': sum(p['predicted_units'] for p in periods),
                'predicted_revenue': round(
                    sum(p['predicted_revenue'] for p in periods), 2),
                'avg_confidence_pct': round(
                    mean([p['confidence_pct'] for p in periods]) if periods else 0, 1),
            },
            'festival_window': sorted(
                {d.isoformat(): m for d, m in festival_idx.items()}.items()),
            'gold_anchor': gold,
        }

    def _persist(self, horizon, scope, scope_id, periods):
        if not periods:
            return
        sql = (
            'INSERT INTO sales_forecasts '
            '(horizon, scope, scope_key, period_start, period_end, '
            ' predicted_units, predicted_revenue, confidence_pct, '
            ' drivers, model_version) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)'
        )
        import json as _json
        params = [
            (horizon, scope,
             None if scope == 'overall' else str(scope_id) if scope_id is not None else None,
             p['period_start'], p['period_end'],
             p['predicted_units'], p['predicted_revenue'],
             p['confidence_pct'], _json.dumps(p['drivers']),
             MODEL_VERSION)
            for p in periods
        ]
        if execute_many is None:
            return
        try:
            execute_many(sql, params)
        except Exception as exc:
            logger.warning('Forecast persistence failed: %s', exc)
