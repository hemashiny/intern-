"""
Prediction service that loads trained models and generates predictions.
Combines ML predictions with rule-based scoring.
"""

import os
import joblib
import numpy as np
import pandas as pd

from feature_engineering import (
    fetch_product_features,
    compute_component_scores,
    compute_weighted_score,
    categorize_demand,
    estimate_days_to_sale,
    categorize_stock,
    detect_dead_stock,
    detect_inventory_risk,
    WEIGHTS,
)
from db_connector import execute_query, execute_many

MODEL_DIR = os.path.join(os.path.dirname(__file__), 'models')
MODEL_VERSION = 'v1.0.0'


class PredictionEngine:
    """Loads ML models and generates jewelry sales predictions."""

    def __init__(self):
        self.xgb_pct = None
        self.rf_pct = None
        self.xgb_days = None
        self.encoder = None
        self.feature_columns = None
        self._load_models()

    def _load_models(self):
        """Load all trained ML artifacts if available."""
        try:
            self.xgb_pct = joblib.load(os.path.join(MODEL_DIR, 'xgb_percentage.pkl'))
            self.rf_pct = joblib.load(os.path.join(MODEL_DIR, 'rf_percentage.pkl'))
            self.xgb_days = joblib.load(os.path.join(MODEL_DIR, 'xgb_days.pkl'))
            self.encoder = joblib.load(os.path.join(MODEL_DIR, 'category_encoder.pkl'))
            self.feature_columns = joblib.load(os.path.join(MODEL_DIR, 'feature_columns.pkl'))
        except (FileNotFoundError, OSError):
            print('ML models not found. Falling back to rule-based predictions.')

    def _encode_category(self, categories):
        """Encode category strings, handling unseen labels."""
        if self.encoder is None:
            return [0] * len(categories)
        known = set(self.encoder.classes_)
        return [
            self.encoder.transform([c])[0] if c in known else -1
            for c in categories
        ]

    def predict(self):
        """Generate predictions for all products."""
        df = fetch_product_features()
        if df.empty:
            return []

        df = compute_component_scores(df)
        df = compute_weighted_score(df)

        if self.xgb_pct is not None:
            df['category_encoded'] = self._encode_category(df['category'].astype(str).tolist())
            X = df[self.feature_columns]
            xgb_pred = self.xgb_pct.predict(X)
            rf_pred = self.rf_pct.predict(X)
            ensemble_pct = (xgb_pred + rf_pred) / 2.0
            ml_days = self.xgb_days.predict(X)
            df['prediction_percentage'] = np.clip(
                0.7 * ensemble_pct + 0.3 * df['prediction_score'], 0, 100
            )
            df['predicted_days_to_sale'] = np.clip(ml_days, 1, 180).astype(int)
        else:
            df['prediction_percentage'] = df['prediction_score'].clip(0, 100)
            df['predicted_days_to_sale'] = df.apply(
                lambda r: estimate_days_to_sale(r['prediction_percentage'], r['stock_quantity']),
                axis=1,
            )

        df['demand_status'] = df['prediction_percentage'].apply(categorize_demand)
        df['stock_status'] = df.apply(
            lambda r: categorize_stock(r['stock_quantity'], r['predicted_days_to_sale']),
            axis=1,
        )
        df['expected_revenue'] = (
            df['cost'].astype(float) * (df['prediction_percentage'].astype(float) / 100.0)
        ).round(2)
        df['inventory_risk'] = df.apply(detect_inventory_risk, axis=1)
        df['dead_stock_alert'] = df.apply(detect_dead_stock, axis=1)

        explanations = df.apply(self._build_explanation, axis=1)
        df['explanation'] = [e['summary'] for e in explanations]
        df['why_factors'] = [e['factors'] for e in explanations]
        df['business_action'] = [e['action'] for e in explanations]
        df['recommendation_reason'] = df['explanation']
        return df.to_dict(orient='records')

    @staticmethod
    def _build_explanation(row):
        """Produce explainable AI output: factors, summary and business action."""
        signals = [
            ('Sales history', row['sales_history_score'], WEIGHTS['sales_history_score']),
            ('Page views', row['view_score'], WEIGHTS['view_score']),
            ('Product clicks', row['click_score'], WEIGHTS['click_score']),
            ('Wishlist saves', row['wishlist_score'], WEIGHTS['wishlist_score']),
            ('Cart additions', row['cart_score'], WEIGHTS['cart_score']),
            ('Recent trend', row['trend_score'], WEIGHTS['trend_score']),
        ]
        factors = [
            {
                'name': name,
                'score': round(float(score), 1),
                'weight': weight,
                'contribution': round(float(score) * weight, 2),
            }
            for name, score, weight in signals
        ]
        factors.sort(key=lambda f: f['contribution'], reverse=True)

        top = [f['name'].lower() for f in factors[:2]]
        summary_bits = []
        if row['historical_sales'] > 50:
            summary_bits.append(f"{int(row['historical_sales'])} historical sales")
        if row['total_views'] > 200:
            summary_bits.append(f"{int(row['total_views'])} recent views")
        if row['wishlist_count'] > 0:
            summary_bits.append(f"{int(row['wishlist_count'])} wishlist saves")
        if row['cart_count'] > 0:
            summary_bits.append(f"{int(row['cart_count'])} cart additions")
        if row['trend_growth'] >= 0.2:
            summary_bits.append(f"+{int(row['trend_growth'] * 100)}% 30-day trend")

        if summary_bits:
            summary = 'Driven by ' + ', '.join(top) + '. ' + ', '.join(summary_bits) + '.'
        else:
            summary = f"Predicted from {top[0]} signal; engagement is still building."

        pct = row['prediction_percentage']
        stock = row['stock_status']
        if row['dead_stock_alert']:
            action = 'Move to clearance, bundle with a top seller, or feature in a discount campaign.'
        elif stock in ('Critical', 'Low') and pct >= 70:
            action = 'Reorder immediately and protect margins; demand will exceed stock within days.'
        elif stock == 'Out of Stock' and pct >= 50:
            action = 'Restock urgently and capture wishlist customers with a back-in-stock alert.'
        elif stock == 'Overstock' and pct < 50:
            action = 'Run a targeted promotion or move to the storefront window to accelerate sales.'
        elif pct >= 85:
            action = 'Promote on the homepage and increase inventory to ride the demand spike.'
        elif pct >= 60:
            action = 'Maintain current stock and add to recommended-for-you slots.'
        else:
            action = 'Hold inventory and monitor; not a priority for promotion this cycle.'

        return {'factors': factors, 'summary': summary, 'action': action}

    def persist_predictions(self, predictions):
        """Save predictions into prediction_results table."""
        if not predictions:
            return 0
        sql = """
            INSERT INTO prediction_results
                (product_id, prediction_score, prediction_percentage,
                 predicted_days_to_sale, demand_status,
                 sales_history_score, view_score, click_score, wishlist_score,
                 model_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        rows = [
            (
                int(p['product_id']),
                float(round(p['prediction_score'], 2)),
                float(round(p['prediction_percentage'], 2)),
                int(p['predicted_days_to_sale']),
                p['demand_status'],
                float(round(p['sales_history_score'], 2)),
                float(round(p['view_score'], 2)),
                float(round(p['click_score'], 2)),
                float(round(p['wishlist_score'], 2)),
                MODEL_VERSION,
            )
            for p in predictions
        ]
        return execute_many(sql, rows)
