"""
Offer recommendation engine.

Given the live prediction-engine output plus upcoming festivals, generates
a ranked list of offer suggestions per product across five offer types:

  * festival   - jewelry-relevant festival within the window
  * combo      - cross-sell bundle with a complementary category
  * clearance  - dead-stock / overstock liquidation
  * loyalty    - exclusive % off for repeat customers on hot items
  * flash      - 24-48h discount on healthy-stock items with medium demand

Offers are deterministic (no randomness) so the dashboard renders the
same recommendations across reloads.
"""

import logging
from datetime import date, datetime, timedelta

from integrations import get_upcoming_festivals

logger = logging.getLogger(__name__)

ENGINE_VERSION = 'offer-engine-v1.0.0'

# Category-pairing matrix used by the combo/bundle offer generator.
COMBO_PAIRS = {
    'ring': ['Earrings', 'Pendant', 'Necklace'],
    'necklace': ['Earrings', 'Bracelet', 'Bangles'],
    'earrings': ['Ring', 'Pendant'],
    'bracelet': ['Ring', 'Pendant', 'Necklace'],
    'pendant': ['Earrings', 'Chain'],
    'chain': ['Pendant', 'Bracelet'],
    'bangles': ['Necklace', 'Earrings'],
}

FESTIVAL_HINTS = {
    'diwali': ('Diwali Dhamaka', 18),
    'dhanteras': ('Dhanteras Gold Day', 15),
    'akshaya tritiya': ('Akshaya Tritiya Exclusive', 12),
    'navaratri': ('Navaratri Nine-Day Offer', 12),
    'raksha bandhan': ('Rakhi Gifting Special', 15),
    'karva chauth': ('Karva Chauth Suhag Set', 14),
    'valentine': ('Valentine Forever Bond', 17),
    'mother': ("Mother's Day Tribute", 12),
    'christmas': ('Christmas Sparkle', 10),
    'eid': ('Eid Mubarak Collection', 12),
    'new year': ('New Year Brilliance', 10),
    'pongal': ('Pongal Prosperity', 10),
    'onam': ('Onam Heritage Sale', 10),
}


def _festival_window(days_ahead=30):
    today = date.today()
    horizon = today + timedelta(days=days_ahead)
    upcoming = []
    for f in get_upcoming_festivals(days_ahead=days_ahead):
        try:
            d = datetime.strptime(f['date'], '%Y-%m-%d').date()
        except (KeyError, ValueError):
            continue
        if today <= d <= horizon and f.get('is_jewelry_relevant'):
            upcoming.append({
                'name': f['name'],
                'date': f['date'],
                'days_away': (d - today).days,
                'jewelry_impact': f.get('jewelry_impact'),
            })
    return sorted(upcoming, key=lambda x: x['days_away'])


def _festival_label(festival_name):
    lower = (festival_name or '').lower()
    for key, (label, pct) in FESTIVAL_HINTS.items():
        if key in lower:
            return label, pct
    return f'{festival_name} Special', 10


def _build_offer(prediction, offer_type, title, discount_pct, message,
                 valid_days, priority):
    cost = float(prediction.get('cost') or 0)
    discounted = round(cost * (1 - discount_pct / 100.0), 2)
    today = date.today()
    return {
        'product_id': prediction['product_id'],
        'item_no': prediction['item_no'],
        'product_name': prediction['product_name'],
        'category': prediction['category'],
        'image_url': prediction.get('image_url'),
        'offer_type': offer_type,
        'title': title,
        'message': message,
        'discount_pct': discount_pct,
        'original_price': cost,
        'offer_price': discounted,
        'valid_from': today.isoformat(),
        'valid_until': (today + timedelta(days=valid_days)).isoformat(),
        'priority_score': priority,
        'engine_version': ENGINE_VERSION,
    }


def _festival_offers(predictions, festivals):
    if not festivals:
        return []
    target = festivals[0]
    label, pct = _festival_label(target['name'])
    offers = []
    eligible = [p for p in predictions if p.get('prediction_percentage', 0) >= 45
                and not p.get('dead_stock_alert')]
    eligible.sort(key=lambda p: p['prediction_percentage'], reverse=True)
    for p in eligible[:8]:
        msg = (f"{label}: {pct}% off ahead of {target['name']} "
               f"in {target['days_away']} days.")
        offers.append(_build_offer(
            p, 'festival', label, pct, msg,
            valid_days=max(7, target['days_away'] + 2),
            priority=85 + min(10, target['days_away'] // -1 if target['days_away'] == 0 else max(0, 10 - target['days_away'] // 3)),
        ))
    return offers


def _combo_offers(predictions):
    by_cat = {}
    for p in predictions:
        by_cat.setdefault(str(p.get('category', '')).lower(), []).append(p)
    offers = []
    hot = [p for p in predictions if p.get('prediction_percentage', 0) >= 70]
    hot.sort(key=lambda p: p['prediction_percentage'], reverse=True)
    seen = set()
    for anchor in hot[:6]:
        partners = COMBO_PAIRS.get(str(anchor['category']).lower(), [])
        for partner_cat in partners:
            pool = by_cat.get(partner_cat.lower(), [])
            if not pool:
                continue
            partner = max(pool, key=lambda p: p.get('prediction_percentage', 0))
            key = tuple(sorted([anchor['product_id'], partner['product_id']]))
            if key in seen or anchor['product_id'] == partner['product_id']:
                continue
            seen.add(key)
            pct = 8
            msg = (f"Bundle '{anchor['product_name']}' with "
                   f"'{partner['product_name']}' for {pct}% off the pair.")
            offer = _build_offer(anchor, 'combo',
                                 f"{anchor['category']} + {partner['category']} Combo",
                                 pct, msg, valid_days=21, priority=70)
            offer['bundle_with'] = {
                'product_id': partner['product_id'],
                'item_no': partner['item_no'],
                'product_name': partner['product_name'],
                'category': partner['category'],
            }
            offers.append(offer)
            break
    return offers



def _clearance_offers(predictions):
    offers = []
    for p in predictions:
        if not (p.get('dead_stock_alert') or
                (p.get('stock_status') == 'Overstock' and
                 p.get('prediction_percentage', 0) < 40)):
            continue
        pct = 35 if p.get('dead_stock_alert') else 22
        msg = ('Liquidate slow stock: clear inventory and recover capital '
               f"with {pct}% off.")
        offers.append(_build_offer(
            p, 'clearance', 'Clearance Sale', pct, msg,
            valid_days=30, priority=55))
    return offers


def _loyalty_offers(predictions):
    offers = []
    eligible = [p for p in predictions if p.get('prediction_percentage', 0) >= 80
                and not p.get('dead_stock_alert')]
    eligible.sort(key=lambda p: p['prediction_percentage'], reverse=True)
    for p in eligible[:5]:
        pct = 5
        msg = ('Loyalty member exclusive: extra 5% off plus early access '
               'to this top-demand piece.')
        offers.append(_build_offer(
            p, 'loyalty', 'Loyalty Member Reward', pct, msg,
            valid_days=14, priority=65))
    return offers


def _flash_offers(predictions):
    offers = []
    eligible = [
        p for p in predictions
        if 45 <= p.get('prediction_percentage', 0) < 70
        and p.get('stock_status') in ('Healthy', 'Overstock')
        and not p.get('dead_stock_alert')
    ]
    eligible.sort(key=lambda p: p.get('stock_quantity', 0), reverse=True)
    for p in eligible[:6]:
        pct = 15
        msg = ('48-hour flash sale to convert browsers into buyers on a '
               'healthy-stock item.')
        offers.append(_build_offer(
            p, 'flash', '48h Flash Sale', pct, msg,
            valid_days=2, priority=60))
    return offers


class OfferEngine:
    """Public entry point for generating offer recommendations."""

    def __init__(self, prediction_engine=None):
        self.prediction_engine = prediction_engine

    def _live_predictions(self):
        if self.prediction_engine is None:
            return []
        try:
            return self.prediction_engine.predict() or []
        except Exception as exc:
            logger.debug('Prediction engine unavailable for offers: %s', exc)
            return []

    def generate(self, offer_type=None, limit=50):
        predictions = self._live_predictions()
        festivals = _festival_window(days_ahead=30)

        builders = {
            'festival': lambda: _festival_offers(predictions, festivals),
            'combo': lambda: _combo_offers(predictions),
            'clearance': lambda: _clearance_offers(predictions),
            'loyalty': lambda: _loyalty_offers(predictions),
            'flash': lambda: _flash_offers(predictions),
        }

        if offer_type and offer_type in builders:
            offers = builders[offer_type]()
        else:
            offers = []
            for build in builders.values():
                offers.extend(build())

        offers.sort(key=lambda o: o['priority_score'], reverse=True)
        offers = offers[:limit]

        counts = {}
        for o in offers:
            counts[o['offer_type']] = counts.get(o['offer_type'], 0) + 1

        return {
            'engine_version': ENGINE_VERSION,
            'generated_at': datetime.utcnow().isoformat() + 'Z',
            'total': len(offers),
            'counts_by_type': counts,
            'upcoming_festivals': festivals[:4],
            'offers': offers,
        }
