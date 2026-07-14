"""
Training pipeline for jewelry sales prediction models.
Trains XGBoost and Random Forest regressors.
"""

import os
import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBRegressor

from feature_engineering import (
    fetch_product_features,
    compute_component_scores,
    compute_weighted_score,
)

MODEL_DIR = os.path.join(os.path.dirname(__file__), 'models')
os.makedirs(MODEL_DIR, exist_ok=True)

FEATURE_COLUMNS = [
    'total_views', 'unique_viewers', 'avg_view_duration',
    'total_clicks', 'unique_clickers', 'historical_sales',
    'days_since_last_sale', 'wishlist_count', 'cart_count',
    'repeated_views', 'cost', 'stock_quantity', 'category_encoded',
]


def build_training_data():
    """Build training dataset with synthetic labels for cold start."""
    df = fetch_product_features()
    if df.empty:
        raise RuntimeError('No product data available for training.')

    df = compute_component_scores(df)
    df = compute_weighted_score(df)

    encoder = LabelEncoder()
    df['category_encoded'] = encoder.fit_transform(df['category'].astype(str))
    joblib.dump(encoder, os.path.join(MODEL_DIR, 'category_encoder.pkl'))

    target_percentage = df['prediction_score'].clip(0, 100)
    target_days = target_percentage.apply(
        lambda p: 3 if p >= 90 else 7 if p >= 70 else 15 if p >= 50 else 30 if p >= 30 else 60
    )
    return df[FEATURE_COLUMNS], target_percentage, target_days


def train_xgboost(X_train, y_train):
    """Train XGBoost Regressor."""
    model = XGBRegressor(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.85,
        colsample_bytree=0.85,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    return model


def train_random_forest(X_train, y_train):
    """Train Random Forest Regressor."""
    model = RandomForestRegressor(
        n_estimators=200,
        max_depth=10,
        min_samples_split=2,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    return model


def evaluate_model(model, X_test, y_test, name):
    """Evaluate model performance."""
    preds = model.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    r2 = r2_score(y_test, preds)
    print(f"[{name}] MAE: {mae:.3f} | R2: {r2:.3f}")
    return mae, r2


def main():
    print('Building training dataset...')
    X, y_pct, y_days = build_training_data()
    print(f'Training samples: {len(X)}')

    test_size = 0.2 if len(X) >= 10 else 0.0

    if test_size > 0:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y_pct, test_size=test_size, random_state=42
        )
        _, _, y_days_train, y_days_test = train_test_split(
            X, y_days, test_size=test_size, random_state=42
        )
    else:
        X_train, X_test = X, X
        y_train, y_test = y_pct, y_pct
        y_days_train, y_days_test = y_days, y_days

    print('Training XGBoost (percentage)...')
    xgb_pct = train_xgboost(X_train, y_train)
    evaluate_model(xgb_pct, X_test, y_test, 'XGBoost-Percentage')

    print('Training Random Forest (percentage)...')
    rf_pct = train_random_forest(X_train, y_train)
    evaluate_model(rf_pct, X_test, y_test, 'RandomForest-Percentage')

    print('Training XGBoost (days to sale)...')
    xgb_days = train_xgboost(X_train, y_days_train)
    evaluate_model(xgb_days, X_test, y_days_test, 'XGBoost-Days')

    joblib.dump(xgb_pct, os.path.join(MODEL_DIR, 'xgb_percentage.pkl'))
    joblib.dump(rf_pct, os.path.join(MODEL_DIR, 'rf_percentage.pkl'))
    joblib.dump(xgb_days, os.path.join(MODEL_DIR, 'xgb_days.pkl'))
    joblib.dump(FEATURE_COLUMNS, os.path.join(MODEL_DIR, 'feature_columns.pkl'))

    print(f'Models saved to {MODEL_DIR}')


if __name__ == '__main__':
    main()
