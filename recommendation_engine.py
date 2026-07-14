"""
Customer recommendation engine.
Combines collaborative filtering with content-based and prediction signals.
"""

import pandas as pd
from db_connector import execute_query


CUSTOMER_HISTORY_QUERY = """
SELECT DISTINCT p.product_id, p.category
FROM products p
WHERE p.product_id IN (
    SELECT product_id FROM sales_history WHERE customer_id = %s
    UNION
    SELECT product_id FROM product_views WHERE customer_id = %s
    UNION
    SELECT product_id FROM product_clicks WHERE customer_id = %s
    UNION
    SELECT product_id FROM wishlist WHERE customer_id = %s
)
"""

VIEW_COUNT_QUERY = """
SELECT product_id, COUNT(*) AS view_count
FROM product_views
WHERE customer_id = %s
GROUP BY product_id
"""

SIMILAR_CUSTOMERS_QUERY = """
SELECT DISTINCT v2.product_id
FROM product_views v1
JOIN product_views v2 ON v1.customer_id = v2.customer_id
WHERE v1.product_id IN ({})
  AND v2.product_id NOT IN ({})
  AND v1.customer_id != %s
GROUP BY v2.product_id
ORDER BY COUNT(*) DESC
LIMIT 10
"""

LATEST_PREDICTIONS_QUERY = """
SELECT pr.*, p.item_no, p.product_name, p.category, p.price
FROM prediction_results pr
JOIN products p ON pr.product_id = p.product_id
INNER JOIN (
    SELECT product_id, MAX(created_at) AS latest
    FROM prediction_results
    GROUP BY product_id
) latest ON pr.product_id = latest.product_id AND pr.created_at = latest.latest
"""


class RecommendationEngine:
    """Generates personalized product recommendations."""

    def get_customer_history(self, customer_id):
        """Get all products a customer has interacted with."""
        rows = execute_query(
            CUSTOMER_HISTORY_QUERY,
            (customer_id, customer_id, customer_id, customer_id),
        )
        return pd.DataFrame(rows)

    def get_view_counts(self, customer_id):
        """Get per-product view counts for a customer."""
        rows = execute_query(VIEW_COUNT_QUERY, (customer_id,))
        return {r['product_id']: r['view_count'] for r in rows}

    def get_similar_customer_products(self, customer_id, product_ids):
        """Find products viewed by similar customers."""
        if not product_ids:
            return []
        placeholders = ','.join(['%s'] * len(product_ids))
        query = SIMILAR_CUSTOMERS_QUERY.format(placeholders, placeholders)
        params = tuple(product_ids) + tuple(product_ids) + (customer_id,)
        rows = execute_query(query, params)
        return [r['product_id'] for r in rows]

    def get_latest_predictions(self):
        """Get the latest prediction record per product."""
        rows = execute_query(LATEST_PREDICTIONS_QUERY)
        return pd.DataFrame(rows)

    def recommend(self, customer_id, limit=10):
        """Generate ranked recommendations for a customer."""
        history = self.get_customer_history(customer_id)
        predictions = self.get_latest_predictions()
        if predictions.empty:
            return []

        interacted_ids = set(history['product_id'].tolist()) if not history.empty else set()
        view_counts = self.get_view_counts(customer_id)
        preferred_categories = (
            set(history['category'].tolist()) if not history.empty else set()
        )
        similar_product_ids = set(
            self.get_similar_customer_products(customer_id, list(interacted_ids))
        )

        recommendations = []
        for _, row in predictions.iterrows():
            pid = row['product_id']
            score = float(row['prediction_percentage'])
            reasons = []

            if pid in view_counts and view_counts[pid] >= 2:
                score += 15
                reasons.append(f"Recommended because you viewed this item {view_counts[pid]} times")
            if row['category'] in preferred_categories and pid not in interacted_ids:
                score += 10
                reasons.append(f"Similar to {row['category']} items you liked")
            if pid in similar_product_ids:
                score += 8
                reasons.append('Customers with similar interests viewed this')
            if row['predicted_days_to_sale'] <= 3:
                score += 5
                reasons.append(f"Trending item predicted to sell within {row['predicted_days_to_sale']} days")
            if row['demand_status'] == 'Very High':
                score += 3
                reasons.append('High-demand product')

            if not reasons:
                continue

            recommendations.append({
                'product_id': int(pid),
                'item_no': row['item_no'],
                'product_name': row['product_name'],
                'category': row['category'],
                'price': float(row['price']),
                'prediction_percentage': float(row['prediction_percentage']),
                'predicted_days_to_sale': int(row['predicted_days_to_sale']),
                'demand_status': row['demand_status'],
                'recommendation_score': round(min(score, 100), 2),
                'reasons': reasons,
            })

        recommendations.sort(key=lambda x: x['recommendation_score'], reverse=True)
        return recommendations[:limit]
