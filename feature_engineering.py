"""
Feature engineering for jewelry sales prediction.
Aggregates raw data into ML-ready features.
"""

import pandas as pd
from db_connector import execute_query


FEATURE_QUERY = """
SELECT
    p.product_id,
    p.item_no,
    p.product_name,
    p.category,
    p.price AS cost,
    p.stock_quantity,
    p.image_url,
    COALESCE(view_stats.total_views, 0) AS total_views,
    COALESCE(view_stats.unique_viewers, 0) AS unique_viewers,
    COALESCE(view_stats.avg_view_duration, 0) AS avg_view_duration,
    COALESCE(view_stats.recent_views, 0) AS recent_views,
    COALESCE(view_stats.prior_views, 0) AS prior_views,
    COALESCE(click_stats.total_clicks, 0) AS total_clicks,
    COALESCE(click_stats.unique_clickers, 0) AS unique_clickers,
    COALESCE(click_stats.recent_clicks, 0) AS recent_clicks,
    COALESCE(click_stats.prior_clicks, 0) AS prior_clicks,
    COALESCE(sales_stats.total_sales, 0) AS historical_sales,
    COALESCE(sales_stats.total_revenue, 0) AS total_revenue,
    COALESCE(sales_stats.recent_sales, 0) AS recent_sales,
    COALESCE(sales_stats.prior_sales, 0) AS prior_sales,
    DATEDIFF(NOW(), COALESCE(sales_stats.last_sold_date, p.created_at)) AS days_since_last_sale,
    COALESCE(wishlist_stats.wishlist_count, 0) AS wishlist_count,
    COALESCE(cart_stats.cart_count, 0) AS cart_count,
    COALESCE(view_stats.repeated_views, 0) AS repeated_views
FROM products p
LEFT JOIN (
    SELECT
        product_id,
        COUNT(*) AS total_views,
        COUNT(DISTINCT customer_id) AS unique_viewers,
        AVG(view_duration_seconds) AS avg_view_duration,
        COUNT(*) - COUNT(DISTINCT customer_id) AS repeated_views,
        SUM(CASE WHEN view_date >= DATE_SUB(NOW(), INTERVAL 30 DAY) THEN 1 ELSE 0 END) AS recent_views,
        SUM(CASE WHEN view_date <  DATE_SUB(NOW(), INTERVAL 30 DAY) THEN 1 ELSE 0 END) AS prior_views
    FROM product_views
    WHERE view_date >= DATE_SUB(NOW(), INTERVAL 90 DAY)
    GROUP BY product_id
) view_stats ON p.product_id = view_stats.product_id
LEFT JOIN (
    SELECT
        product_id,
        COUNT(*) AS total_clicks,
        COUNT(DISTINCT customer_id) AS unique_clickers,
        SUM(CASE WHEN click_date >= DATE_SUB(NOW(), INTERVAL 30 DAY) THEN 1 ELSE 0 END) AS recent_clicks,
        SUM(CASE WHEN click_date <  DATE_SUB(NOW(), INTERVAL 30 DAY) THEN 1 ELSE 0 END) AS prior_clicks
    FROM product_clicks
    WHERE click_date >= DATE_SUB(NOW(), INTERVAL 90 DAY)
    GROUP BY product_id
) click_stats ON p.product_id = click_stats.product_id
LEFT JOIN (
    SELECT
        product_id,
        SUM(quantity) AS total_sales,
        SUM(sale_amount) AS total_revenue,
        MAX(sale_date) AS last_sold_date,
        SUM(CASE WHEN sale_date >= DATE_SUB(NOW(), INTERVAL 30 DAY) THEN quantity ELSE 0 END) AS recent_sales,
        SUM(CASE WHEN sale_date <  DATE_SUB(NOW(), INTERVAL 30 DAY) THEN quantity ELSE 0 END) AS prior_sales
    FROM sales_history
    GROUP BY product_id
) sales_stats ON p.product_id = sales_stats.product_id
LEFT JOIN (
    SELECT product_id, COUNT(*) AS wishlist_count
    FROM wishlist GROUP BY product_id
) wishlist_stats ON p.product_id = wishlist_stats.product_id
LEFT JOIN (
    SELECT product_id, COUNT(*) AS cart_count
    FROM cart GROUP BY product_id
) cart_stats ON p.product_id = cart_stats.product_id
"""


def fetch_product_features():
    """Fetch aggregated features for all products."""
    rows = execute_query(FEATURE_QUERY)
    return pd.DataFrame(rows)


def normalize_score(series, max_val=None):
    """Normalize a series to a 0-100 scale."""
    if max_val is None:
        max_val = series.max() if len(series) > 0 else 1
    if max_val == 0:
        return pd.Series([0] * len(series), index=series.index)
    return (series / max_val * 100).clip(0, 100)


def compute_component_scores(df):
    """Compute individual component scores for prediction."""
    df = df.copy()
    df['sales_history_score'] = normalize_score(df['historical_sales'])
    df['view_score'] = normalize_score(df['total_views'])
    df['click_score'] = normalize_score(df['total_clicks'])
    df['wishlist_score'] = normalize_score(df['wishlist_count'])
    df['cart_score'] = normalize_score(df['cart_count'])

    for col in ('recent_views', 'prior_views', 'recent_clicks',
                'prior_clicks', 'recent_sales', 'prior_sales'):
        if col not in df.columns:
            df[col] = 0

    recent = df['recent_views'] + df['recent_clicks'] + df['recent_sales'] * 3
    prior = df['prior_views'] + df['prior_clicks'] + df['prior_sales'] * 3
    denom = prior.where(prior > 0, 1)
    df['trend_growth'] = ((recent - prior) / denom).clip(-1, 3)
    df['trend_score'] = ((df['trend_growth'] + 1) / 4 * 100).clip(0, 100)
    return df


WEIGHTS = {
    'sales_history_score': 0.40,
    'view_score': 0.18,
    'click_score': 0.12,
    'wishlist_score': 0.10,
    'cart_score': 0.10,
    'trend_score': 0.10,
}


def compute_weighted_score(df):
    """Compute weighted prediction score using business rules."""
    df = df.copy()
    df['prediction_score'] = sum(df[col] * w for col, w in WEIGHTS.items())
    df['prediction_score'] = df['prediction_score'].clip(0, 100)
    return df


def categorize_demand(percentage):
    """Map prediction percentage to demand category."""
    if percentage >= 90:
        return 'Very High'
    if percentage >= 70:
        return 'High'
    if percentage >= 50:
        return 'Medium'
    return 'Low'


def estimate_days_to_sale(percentage, stock_quantity=1):
    """Estimate days to sale based on prediction percentage."""
    if percentage >= 90:
        base_days = 3
    elif percentage >= 70:
        base_days = 7
    elif percentage >= 50:
        base_days = 15
    elif percentage >= 30:
        base_days = 30
    else:
        base_days = 60
    stock_factor = max(1.0, stock_quantity / 10)
    return int(base_days * stock_factor)


def categorize_stock(stock_quantity, predicted_days):
    """Classify stock posture from quantity and predicted velocity."""
    if stock_quantity <= 0:
        return 'Out of Stock'
    if stock_quantity <= 3 and predicted_days <= 10:
        return 'Critical'
    if stock_quantity <= 5:
        return 'Low'
    if stock_quantity >= 30 and predicted_days >= 30:
        return 'Overstock'
    return 'Healthy'


def detect_dead_stock(row):
    """Return True when an item is at risk of becoming dead stock."""
    return (
        row.get('historical_sales', 0) <= 1
        and row.get('total_views', 0) < 50
        and row.get('days_since_last_sale', 0) >= 90
        and row.get('stock_quantity', 0) > 0
    )


def detect_inventory_risk(row):
    """Return True when high demand will likely exhaust limited stock."""
    return (
        row.get('stock_quantity', 0) > 0
        and row.get('stock_quantity', 0) <= 5
        and row.get('prediction_percentage', 0) >= 70
    )
