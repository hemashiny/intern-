"""
Inventory planning engine.

Classifies every product into a velocity bucket (fast / steady / slow /
dead / out-of-stock), then computes the reorder quantity, restock-by
date and safety-stock level so the business owner can plan procurement.

Inputs come from the live prediction engine output, so the planner
inherits the demand signal, stock_status and dead_stock flag that the
weighted model already produced.

All durations are in days. Lead time defaults to 14 (typical wholesaler
turnaround for Indian jewelry supply chains) and can be overridden per
category via the LEAD_TIME_DAYS map.
"""

import logging
import math
from datetime import date, timedelta

logger = logging.getLogger(__name__)

PLANNER_VERSION = 'inventory-planner-v1.0.0'

LEAD_TIME_DAYS = {
    'ring': 14, 'necklace': 18, 'bracelet': 14, 'earrings': 10,
    'pendant': 12, 'chain': 12, 'bangles': 18,
}
DEFAULT_LEAD_TIME = 14
SAFETY_STOCK_DAYS = 7      # buffer beyond lead time
TARGET_COVER_DAYS = 30     # how many days of stock to keep on hand
MIN_REORDER_QTY = 3
DEAD_STOCK_DAYS = 90       # > this predicted_days_to_sale = dead


def _lead_time(category):
    return LEAD_TIME_DAYS.get(str(category or '').lower(), DEFAULT_LEAD_TIME)


def _velocity_bucket(prediction):
    if prediction.get('dead_stock_alert'):
        return 'dead'
    if (prediction.get('stock_quantity') or 0) <= 0:
        return 'out_of_stock'
    days = int(prediction.get('predicted_days_to_sale') or 999)
    if days <= 7:
        return 'fast'
    if days <= 21:
        return 'steady'
    if days <= DEAD_STOCK_DAYS:
        return 'slow'
    return 'dead'


def _daily_velocity(prediction):
    days = max(1, int(prediction.get('predicted_days_to_sale') or 30))
    return round(1.0 / days, 4)


def _plan_for_product(prediction):
    bucket = _velocity_bucket(prediction)
    stock = int(prediction.get('stock_quantity') or 0)
    velocity = _daily_velocity(prediction)
    lead_time = _lead_time(prediction.get('category'))
    cost = float(prediction.get('cost') or 0)

    safety_stock = max(1, math.ceil(velocity * SAFETY_STOCK_DAYS))
    reorder_point = math.ceil(velocity * lead_time) + safety_stock
    target_stock = max(MIN_REORDER_QTY,
                       math.ceil(velocity * TARGET_COVER_DAYS) + safety_stock)

    if bucket == 'dead':
        recommended_qty = 0
        action = 'Liquidate via clearance / bundle; do not reorder.'
    elif bucket == 'out_of_stock':
        recommended_qty = max(MIN_REORDER_QTY, target_stock)
        action = 'Restock urgently and notify wishlist customers.'
    elif bucket == 'slow':
        recommended_qty = 0
        action = 'Hold inventory; reassess in 30 days.'
    elif stock < reorder_point:
        recommended_qty = max(MIN_REORDER_QTY, target_stock - stock)
        action = ('Reorder soon; current stock will hit the reorder point '
                  'inside the supplier lead time.')
    else:
        recommended_qty = 0
        action = 'Stock is healthy; no procurement action required.'

    days_until_stockout = (
        math.floor(stock / velocity) if velocity > 0 else None
    )
    restock_by = None
    if days_until_stockout is not None and recommended_qty > 0:
        restock_by = (
            date.today()
            + timedelta(days=max(0, days_until_stockout - lead_time))
        ).isoformat()

    return {
        'product_id': prediction['product_id'],
        'item_no': prediction['item_no'],
        'product_name': prediction['product_name'],
        'category': prediction['category'],
        'image_url': prediction.get('image_url'),
        'stock_quantity': stock,
        'stock_status': prediction.get('stock_status'),
        'velocity_bucket': bucket,
        'daily_velocity': velocity,
        'predicted_days_to_sale': int(prediction.get('predicted_days_to_sale') or 0),
        'demand_status': prediction.get('demand_status'),
        'lead_time_days': lead_time,
        'safety_stock': safety_stock,
        'reorder_point': reorder_point,
        'target_stock': target_stock,
        'recommended_reorder_qty': recommended_qty,
        'days_until_stockout': days_until_stockout,
        'restock_by': restock_by,
        'estimated_reorder_cost': round(recommended_qty * cost, 2),
        'action': action,
        'planner_version': PLANNER_VERSION,
    }


class InventoryPlanner:
    """Public entry point for inventory planning."""

    def __init__(self, prediction_engine=None):
        self.prediction_engine = prediction_engine

    def _live_predictions(self):
        if self.prediction_engine is None:
            return []
        try:
            return self.prediction_engine.predict() or []
        except Exception as exc:
            logger.debug('Prediction engine unavailable for planner: %s', exc)
            return []

    def get_plan(self, bucket=None, category=None):
        plans = [_plan_for_product(p) for p in self._live_predictions()]
        if bucket:
            plans = [pl for pl in plans if pl['velocity_bucket'] == bucket]
        if category:
            plans = [pl for pl in plans
                     if str(pl['category']).lower() == str(category).lower()]
        plans.sort(key=lambda p: (p['recommended_reorder_qty'] == 0,
                                  -p['recommended_reorder_qty']))

        summary = {'fast': 0, 'steady': 0, 'slow': 0,
                   'dead': 0, 'out_of_stock': 0}
        total_cost, total_units = 0.0, 0
        for pl in plans:
            summary[pl['velocity_bucket']] = summary.get(pl['velocity_bucket'], 0) + 1
            total_cost += pl['estimated_reorder_cost']
            total_units += pl['recommended_reorder_qty']

        return {
            'planner_version': PLANNER_VERSION,
            'total_products': len(plans),
            'velocity_summary': summary,
            'reorder_units_total': total_units,
            'reorder_cost_total': round(total_cost, 2),
            'plans': plans,
        }

    def get_reorder_suggestions(self, limit=20):
        plan = self.get_plan()
        suggestions = [p for p in plan['plans']
                       if p['recommended_reorder_qty'] > 0][:limit]
        return {
            'planner_version': PLANNER_VERSION,
            'count': len(suggestions),
            'total_reorder_cost': round(
                sum(s['estimated_reorder_cost'] for s in suggestions), 2),
            'suggestions': suggestions,
        }
