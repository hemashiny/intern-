"""
Flask microservice exposing prediction and recommendation APIs.
"""

import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

from predictor import PredictionEngine
from recommendation_engine import RecommendationEngine
from forecaster import SalesForecaster
from offer_engine import OfferEngine
from inventory_planner import InventoryPlanner
from alerts_engine import AlertsEngine
from db_connector import execute_query
from integrations import (
    get_gold_price,
    get_silver_price,
    get_fx_rates,
    get_upcoming_festivals,
    get_competitor_prices,
    get_trending_categories,
    get_ibja_rates,
    get_economic_indicators,
    snapshot_store,
)

load_dotenv()

app = Flask(__name__)
CORS(app)

prediction_engine = PredictionEngine()
recommendation_engine = RecommendationEngine()
sales_forecaster = SalesForecaster(prediction_engine=prediction_engine)
offer_engine = OfferEngine(prediction_engine=prediction_engine)
inventory_planner = InventoryPlanner(prediction_engine=prediction_engine)
alerts_engine = AlertsEngine(prediction_engine=prediction_engine)


def _serialize_prediction(row):
    """Format a prediction record for the API response."""
    image_url = row.get('image_url')
    thumbnail_url = row.get('thumbnail_url') or image_url
    return {
        'item_no': row['item_no'],
        'product_id': int(row['product_id']),
        'product_name': row['product_name'],
        'category': row['category'],
        'cost': float(row['cost']),
        'image_url': image_url,
        'thumbnail_url': thumbnail_url,
        'imageUrl': image_url,
        'thumbnailUrl': thumbnail_url,
        'weight_grams': row.get('weight_grams'),
        'purity': row.get('purity') or row.get('metal_purity'),
        'stock_quantity': int(row.get('stock_quantity', 0) or 0),
        'stock_status': row.get('stock_status', 'Healthy'),
        'total_views': int(row['total_views']),
        'total_clicks': int(row['total_clicks']),
        'historical_sales': int(row['historical_sales']),
        'wishlist_count': int(row.get('wishlist_count', 0)),
        'cart_count': int(row.get('cart_count', 0)),
        'trend_growth': round(float(row.get('trend_growth', 0) or 0), 3),
        'predicted_days_to_sale': int(row['predicted_days_to_sale']),
        'prediction_percentage': round(float(row['prediction_percentage']), 2),
        'expected_revenue': round(float(row.get('expected_revenue', 0) or 0), 2),
        'demand_status': row['demand_status'],
        'inventory_risk': bool(row.get('inventory_risk', False)),
        'dead_stock_alert': bool(row.get('dead_stock_alert', False)),
        'explanation': row.get('explanation', ''),
        'why_factors': row.get('why_factors', []),
        'business_action': row.get('business_action', ''),
        'recommendation_reason': row.get('recommendation_reason', ''),
    }


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'prediction'})


@app.route('/api/predictions', methods=['GET'])
def get_predictions():
    """Run predictions for all products."""
    persist = request.args.get('persist', 'false').lower() == 'true'
    try:
        predictions = prediction_engine.predict()
        if persist:
            prediction_engine.persist_predictions(predictions)
        results = [_serialize_prediction(p) for p in predictions]
        return jsonify({'success': True, 'count': len(results), 'data': results})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/predictions/<int:product_id>', methods=['GET'])
def get_prediction_for_product(product_id):
    """Get prediction for a single product."""
    predictions = prediction_engine.predict()
    match = next((p for p in predictions if int(p['product_id']) == product_id), None)
    if not match:
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    return jsonify({'success': True, 'data': _serialize_prediction(match)})


@app.route('/api/recommendations/<int:customer_id>', methods=['GET'])
def get_recommendations(customer_id):
    """Get personalized recommendations for a customer."""
    limit = int(request.args.get('limit', 10))
    try:
        recs = recommendation_engine.recommend(customer_id, limit=limit)
        return jsonify({'success': True, 'count': len(recs), 'data': recs})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/dashboard/kpis', methods=['GET'])
def get_kpis():
    """Get KPI card data for dashboard."""
    try:
        predictions = prediction_engine.predict()
        if not predictions:
            return jsonify({'success': True, 'data': {}})

        fastest = min(predictions, key=lambda p: p['predicted_days_to_sale'])
        highest_pct = max(predictions, key=lambda p: p['prediction_percentage'])
        most_viewed = max(predictions, key=lambda p: p['total_views'])
        most_clicked = max(predictions, key=lambda p: p['total_clicks'])

        avg_days = sum(p['predicted_days_to_sale'] for p in predictions) / len(predictions)
        predicted_revenue = sum(
            float(p['cost']) * (float(p['prediction_percentage']) / 100.0)
            for p in predictions
        )

        return jsonify({
            'success': True,
            'data': {
                'fastest_selling_item': {
                    'item_no': fastest['item_no'],
                    'product_name': fastest['product_name'],
                    'days': int(fastest['predicted_days_to_sale']),
                },
                'highest_prediction': {
                    'item_no': highest_pct['item_no'],
                    'product_name': highest_pct['product_name'],
                    'percentage': round(float(highest_pct['prediction_percentage']), 2),
                },
                'most_viewed_product': {
                    'item_no': most_viewed['item_no'],
                    'product_name': most_viewed['product_name'],
                    'views': int(most_viewed['total_views']),
                },
                'most_clicked_product': {
                    'item_no': most_clicked['item_no'],
                    'product_name': most_clicked['product_name'],
                    'clicks': int(most_clicked['total_clicks']),
                },
                'average_days_to_sale': round(avg_days, 1),
                'predicted_revenue': round(predicted_revenue, 2),
            },
        })
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/products', methods=['GET'])
def list_products():
    """List all products."""
    rows = execute_query('SELECT * FROM products')
    for row in rows:
        if 'price' in row and row['price'] is not None:
            row['price'] = float(row['price'])
    return jsonify({'success': True, 'data': rows})


@app.route('/api/integrations/gold-price', methods=['GET'])
def gold_price_endpoint():
    refresh = request.args.get('refresh', 'false').lower() == 'true'
    quote = get_gold_price(force_refresh=refresh)
    if refresh:
        snapshot_store.save_api_snapshot('gold_price', quote.get('source') or 'mixed', quote)
        snapshot_store.save_metal_price('gold', quote)
    return jsonify({'success': True, 'data': quote})


@app.route('/api/integrations/silver-price', methods=['GET'])
def silver_price_endpoint():
    refresh = request.args.get('refresh', 'false').lower() == 'true'
    quote = get_silver_price(force_refresh=refresh)
    if refresh:
        snapshot_store.save_api_snapshot('silver_price', quote.get('source') or 'mixed', quote)
        snapshot_store.save_metal_price('silver', quote)
    return jsonify({'success': True, 'data': quote})


@app.route('/api/integrations/fx-rates', methods=['GET'])
def fx_rates_endpoint():
    refresh = request.args.get('refresh', 'false').lower() == 'true'
    payload = get_fx_rates(force_refresh=refresh)
    if refresh:
        snapshot_store.save_api_snapshot('fx', payload.get('source') or 'mixed', payload)
        for quote, rate in (payload.get('rates') or {}).items():
            snapshot_store.save_fx_rate('USD', quote, rate, payload.get('source'))
    return jsonify({'success': True, 'data': payload})


@app.route('/api/integrations/ibja-rates', methods=['GET'])
def ibja_rates_endpoint():
    refresh = request.args.get('refresh', 'false').lower() == 'true'
    payload = get_ibja_rates(force_refresh=refresh)
    if refresh:
        snapshot_store.save_api_snapshot('ibja', payload.get('source') or 'ibja', payload)
    return jsonify({'success': True, 'data': payload})


@app.route('/api/integrations/economic-indicators', methods=['GET'])
def economic_indicators_endpoint():
    refresh = request.args.get('refresh', 'false').lower() == 'true'
    payload = get_economic_indicators(force_refresh=refresh)
    if refresh:
        snapshot_store.save_api_snapshot('economic', 'worldbank+frankfurter', payload)
    return jsonify({'success': True, 'data': payload})


@app.route('/api/integrations/market-pulse', methods=['GET'])
def market_pulse_endpoint():
    """Single aggregated snapshot: IBJA bullion + spot gold/silver + macro.

    Used by the Market Pulse UI card so the frontend issues one request
    instead of three. Refresh=true bypasses all sub-caches.
    """
    refresh = request.args.get('refresh', 'false').lower() == 'true'
    ibja = get_ibja_rates(force_refresh=refresh)
    spot_gold = get_gold_price(force_refresh=refresh)
    spot_silver = get_silver_price(force_refresh=refresh)
    macro = get_economic_indicators(force_refresh=refresh)
    return jsonify({'success': True, 'data': {
        'ibja': ibja,
        'spot_gold': spot_gold,
        'spot_silver': spot_silver,
        'macro': macro,
        'sources': [
            ibja.get('source'),
            spot_gold.get('source'),
            spot_silver.get('source'),
        ] + (macro.get('sources') or []),
    }})


@app.route('/api/admin/refresh', methods=['POST', 'GET'])
def admin_refresh():
    """Force-refresh all live integrations and persist a snapshot."""
    summary = {}
    gold = get_gold_price(force_refresh=True)
    snapshot_store.save_api_snapshot('gold_price', gold.get('source') or 'mixed', gold)
    snapshot_store.save_metal_price('gold', gold)
    summary['gold'] = gold.get('price_inr_per_gram_24k')

    silver = get_silver_price(force_refresh=True)
    snapshot_store.save_api_snapshot('silver_price', silver.get('source') or 'mixed', silver)
    snapshot_store.save_metal_price('silver', silver)
    summary['silver'] = silver.get('price_inr_per_gram')

    fx = get_fx_rates(force_refresh=True)
    snapshot_store.save_api_snapshot('fx', fx.get('source') or 'mixed', fx)
    for quote, rate in (fx.get('rates') or {}).items():
        snapshot_store.save_fx_rate('USD', quote, rate, fx.get('source'))
    summary['usd_inr'] = fx.get('usd_to_inr')

    competitors = get_competitor_prices(limit=50, force_refresh=True)
    summary['competitor_items'] = len(competitors)

    ibja = get_ibja_rates(force_refresh=True)
    snapshot_store.save_api_snapshot('ibja', ibja.get('source') or 'ibja', ibja)
    summary['ibja_gold_24k'] = ibja.get('gold_999_24k_inr_per_g')
    summary['ibja_silver'] = ibja.get('silver_999_inr_per_g')

    macro = get_economic_indicators(force_refresh=True)
    snapshot_store.save_api_snapshot('economic', 'worldbank+frankfurter', macro)
    summary['india_cpi_pct'] = (macro.get('india_inflation') or {}).get('value_pct')
    summary['india_gdp_pct'] = (macro.get('india_gdp_growth') or {}).get('value_pct')

    return jsonify({'success': True, 'data': summary, 'refreshed_at': __import__('datetime').datetime.utcnow().isoformat() + 'Z'})


@app.route('/api/admin/health', methods=['GET'])
def admin_health():
    """Lightweight system health view: latest snapshot + run summary."""
    try:
        gold = execute_query(
            'SELECT recorded_at, price_inr_per_g FROM metal_price_history '
            "WHERE metal='gold' ORDER BY recorded_at DESC LIMIT 1")
        silver = execute_query(
            'SELECT recorded_at, price_inr_per_g FROM metal_price_history '
            "WHERE metal='silver' ORDER BY recorded_at DESC LIMIT 1")
        last_crawls = execute_query(
            'SELECT crawler, status, items_saved, started_at '
            'FROM crawler_runs ORDER BY started_at DESC LIMIT 5')
        return jsonify({'success': True, 'data': {
            'gold_latest': gold[0] if gold else None,
            'silver_latest': silver[0] if silver else None,
            'recent_crawls': last_crawls or [],
        }})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/admin/dashboard', methods=['GET'])
def admin_dashboard():
    """Aggregated admin overview: alerts, market freshness, crawler health."""
    try:
        try:
            gold = execute_query(
                'SELECT recorded_at, price_inr_per_g, source '
                "FROM metal_price_history WHERE metal='gold' "
                'ORDER BY recorded_at DESC LIMIT 1')
            silver = execute_query(
                'SELECT recorded_at, price_inr_per_g, source '
                "FROM metal_price_history WHERE metal='silver' "
                'ORDER BY recorded_at DESC LIMIT 1')
            crawls = execute_query(
                'SELECT crawler, target, status, items_saved, started_at '
                'FROM crawler_runs ORDER BY started_at DESC LIMIT 10') or []
            snapshots = execute_query(
                'SELECT source, provider, fetched_at FROM api_snapshots '
                'ORDER BY fetched_at DESC LIMIT 5') or []
        except Exception:
            gold, silver, crawls, snapshots = [], [], [], []

        alerts_payload = alerts_engine.generate(persist=False)
        live_alerts = alerts_payload['alerts']
        severity_counts = {'critical': 0, 'warning': 0, 'info': 0}
        for a in live_alerts:
            severity_counts[a['severity']] = severity_counts.get(a['severity'], 0) + 1

        ok = sum(1 for c in crawls if c.get('status') == 'ok')
        failed = sum(1 for c in crawls if c.get('status') == 'failed')

        return jsonify({'success': True, 'data': {
            'alerts_summary': {
                'total': len(live_alerts),
                'by_severity': severity_counts,
                'by_type': alerts_payload['counts_by_type'],
            },
            'recent_alerts': live_alerts[:10],
            'market_freshness': {
                'gold_latest': gold[0] if gold else None,
                'silver_latest': silver[0] if silver else None,
            },
            'crawler_health': {
                'recent_runs': crawls,
                'ok_count': ok,
                'failed_count': failed,
            },
            'recent_snapshots': snapshots,
        }})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/alerts', methods=['GET'])
def alerts_endpoint():
    """Generate alerts live; optionally include the persisted history.

    Query params:
      persist        - true to write alerts to the alerts table
      severity       - critical | warning | info
      type           - alert_type filter
      include_history- true to also return last N persisted alerts
      limit          - cap on persisted history (default 50)
    """
    persist = request.args.get('persist', 'false').lower() == 'true'
    severity = request.args.get('severity')
    alert_type = request.args.get('type')
    include_history = request.args.get('include_history', 'false').lower() == 'true'
    limit = int(request.args.get('limit', 50))
    try:
        payload = alerts_engine.generate(persist=persist)
        alerts = payload['alerts']
        if severity:
            alerts = [a for a in alerts if a['severity'] == severity]
        if alert_type:
            alerts = [a for a in alerts if a['alert_type'] == alert_type]
        payload['alerts'] = alerts
        payload['total'] = len(alerts)
        if include_history:
            payload['history'] = alerts_engine.list_alerts(
                limit=limit, severity=severity, alert_type=alert_type)
        return jsonify({'success': True, 'data': payload})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/alerts/generate', methods=['POST'])
def alerts_generate():
    """Force generation + persistence of alerts."""
    try:
        payload = alerts_engine.generate(persist=True)
        return jsonify({'success': True, 'data': payload})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/alerts/<int:alert_id>/ack', methods=['POST'])
def alerts_ack(alert_id):
    try:
        result = alerts_engine.acknowledge(alert_id)
        return jsonify({'success': True, 'data': result})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/forecasts', methods=['GET'])
def forecasts_endpoint():
    """Daily / weekly / monthly sales forecast.

    Query params:
      horizon  - daily | weekly | monthly (default daily)
      scope    - overall | category | product (default overall)
      id       - category name or product_id when scope != overall
      persist  - true to write rows into sales_forecasts
    """
    horizon = request.args.get('horizon', 'daily').lower()
    scope = request.args.get('scope', 'overall').lower()
    scope_id = request.args.get('id')
    persist = request.args.get('persist', 'false').lower() == 'true'
    try:
        payload = sales_forecaster.get_forecasts(
            horizon=horizon, scope=scope,
            scope_id=scope_id, persist=persist)
        return jsonify({'success': True, 'data': payload})
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/forecasts/summary', methods=['GET'])
def forecasts_summary():
    """Bundled daily/weekly/monthly overall forecast for the dashboard."""
    try:
        bundle = {
            h: sales_forecaster.get_forecasts(horizon=h, scope='overall')
            for h in ('daily', 'weekly', 'monthly')
        }
        return jsonify({'success': True, 'data': bundle})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/offers', methods=['GET'])
def offers_endpoint():
    """Generate offer recommendations.

    Query params:
      type   - festival | combo | clearance | loyalty | flash (optional)
      limit  - max offers (default 50)
    """
    offer_type = request.args.get('type')
    limit = int(request.args.get('limit', 50))
    try:
        payload = offer_engine.generate(offer_type=offer_type, limit=limit)
        return jsonify({'success': True, 'data': payload})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/inventory-plan', methods=['GET'])
def inventory_plan_endpoint():
    """Full inventory plan with velocity buckets and reorder math.

    Query params:
      bucket   - fast | steady | slow | dead | out_of_stock (optional)
      category - filter by category (optional)
    """
    bucket = request.args.get('bucket')
    category = request.args.get('category')
    try:
        payload = inventory_planner.get_plan(bucket=bucket, category=category)
        return jsonify({'success': True, 'data': payload})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/inventory/reorder-suggestions', methods=['GET'])
def reorder_suggestions_endpoint():
    """Compact list of products that need reordering now."""
    limit = int(request.args.get('limit', 20))
    try:
        payload = inventory_planner.get_reorder_suggestions(limit=limit)
        return jsonify({'success': True, 'data': payload})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/integrations/festivals', methods=['GET'])
def festivals_endpoint():
    days = int(request.args.get('days', 90))
    country = request.args.get('country')
    return jsonify({'success': True, 'data': get_upcoming_festivals(days_ahead=days, country=country)})


@app.route('/api/integrations/competitors', methods=['GET'])
def competitors_endpoint():
    category = request.args.get('category')
    limit = int(request.args.get('limit', 20))
    return jsonify({'success': True, 'data': get_competitor_prices(category=category, limit=limit)})


@app.route('/api/integrations/trends', methods=['GET'])
def trends_endpoint():
    return jsonify({'success': True, 'data': _trending_payload()})


def _trending_payload():
    """Build trend rows from predictions + external Google Trends signal."""
    predictions = prediction_engine.predict()
    by_category = {}
    for p in predictions:
        cat = p['category']
        score = float(p.get('trend_score', 0) or 0)
        by_category.setdefault(cat, []).append(score)
    internal = {cat: sum(scores) / len(scores) for cat, scores in by_category.items()}
    return get_trending_categories(internal_signals=internal)


@app.route('/api/business-insights', methods=['GET'])
def business_insights():
    """Aggregate dashboard for the jewelry business owner."""
    try:
        predictions = prediction_engine.predict()
        serialized = [_serialize_prediction(p) for p in predictions]

        inventory_alerts = [
            {
                'product_id': p['product_id'],
                'item_no': p['item_no'],
                'product_name': p['product_name'],
                'category': p['category'],
                'image_url': p['image_url'],
                'stock_quantity': p['stock_quantity'],
                'stock_status': p['stock_status'],
                'prediction_percentage': p['prediction_percentage'],
                'predicted_days_to_sale': p['predicted_days_to_sale'],
                'action': p['business_action'],
            }
            for p in serialized if p['inventory_risk']
        ]
        dead_stock = [
            {
                'product_id': p['product_id'],
                'item_no': p['item_no'],
                'product_name': p['product_name'],
                'category': p['category'],
                'image_url': p['image_url'],
                'stock_quantity': p['stock_quantity'],
                'historical_sales': p['historical_sales'],
                'total_views': p['total_views'],
                'expected_revenue': p['expected_revenue'],
                'action': p['business_action'],
            }
            for p in serialized if p['dead_stock_alert']
        ]
        top_movers = sorted(
            serialized, key=lambda x: x['prediction_percentage'], reverse=True
        )[:5]

        gold = get_gold_price()
        silver = get_silver_price()
        fx = get_fx_rates()
        festivals = get_upcoming_festivals(days_ahead=90)
        competitors = get_competitor_prices(limit=12)
        trends = _trending_payload()

        return jsonify({
            'success': True,
            'data': {
                'inventory_risk_alerts': inventory_alerts,
                'dead_stock_alerts': dead_stock,
                'top_movers': top_movers,
                'gold_price': gold,
                'silver_price': silver,
                'fx_rates': fx,
                'upcoming_festivals': festivals[:8],
                'competitor_pricing': competitors,
                'trending_jewelry': trends,
                'total_expected_revenue': round(
                    sum(p['expected_revenue'] for p in serialized), 2
                ),
            },
        })
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


if __name__ == '__main__':
    port = int(os.getenv('ML_SERVICE_PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
