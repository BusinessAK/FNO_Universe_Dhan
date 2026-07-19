import duckdb
import pandas as pd
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, classification_report, roc_auc_score, average_precision_score
from sklearn.model_selection import TimeSeriesSplit, RandomizedSearchCV
from sklearn.calibration import CalibratedClassifierCV
import os
import joblib
import json
import datetime

def create_training_data():
    conn = duckdb.connect('data/compiled/vanguard.duckdb')
    
    query = """
        SELECT 
            s.date, 
            s.symbol, 
            s.spot_close, 
            s.spot_change_pct, 
            s.ifs_score, 
            s.net_inv_shift, 
            s.gex_shift, 
            s.iv_shift, 
            s.call_wall, 
            s.put_wall,
            b.bullish_pct,
            b.bearish_pct,
            b.compression_pct,
            b.expansion_pct
        FROM daily_market_structure s
        JOIN daily_market_breadth b ON s.date = b.date
        ORDER BY s.date, s.symbol
    """
    df = conn.execute(query).fetchdf()
    conn.close()

    features = []
    labels = []
    dates = []

    # Process per symbol to get T+3 target
    for symbol, group in df.groupby('symbol'):
        group = group.sort_values('date').reset_index(drop=True)
        for i in range(len(group) - 3):
            row_t = group.iloc[i]
            
            if row_t['call_wall'] == 0 or row_t['put_wall'] == 0 or row_t['spot_close'] == 0:
                continue

            dist_to_cw = (row_t['call_wall'] - row_t['spot_close']) / row_t['spot_close'] * 100
            dist_to_pw = (row_t['spot_close'] - row_t['put_wall']) / row_t['spot_close'] * 100
            
            f = {
                'macro_bullish_pct': float(row_t['bullish_pct']),
                'macro_bearish_pct': float(row_t['bearish_pct']),
                'macro_compression_pct': float(row_t['compression_pct']),
                'macro_expansion_pct': float(row_t['expansion_pct']),
            }
            
            max_future_close = group['spot_close'].iloc[i+1 : i+4].max()
            max_pct_move = (max_future_close - row_t['spot_close']) / row_t['spot_close'] * 100
            
            label = 1 if max_pct_move > 3.0 else 0
            
            features.append(f)
            labels.append(label)
            dates.append(row_t['date'])
            
    df_features = pd.DataFrame(features)
    df_features['date'] = dates
    df_features['label'] = labels
    
    # Sort rigorously by date to prevent leakage in TimeSeriesSplit
    df_features = df_features.sort_values('date').reset_index(drop=True)
    
    y = df_features['label']
    dates_s = df_features['date']
    X = df_features.drop(columns=['date', 'label'])
    
    return X, y, dates_s

def train_and_export_model():
    print("[*] Generating ML Features & Macro Context...")
    X_full, y_full, dates_full = create_training_data()
    
    print(f"[*] Total Samples extracted: {len(X_full)}")
    pos_ratio = y_full.mean() * 100
    print(f"[*] Base Positive Class Ratio (Breakouts): {pos_ratio:.2f}%")
    
    # Strict 3-Way Split
    # Train: < '2026-03-01'
    # Validation (for calibration): Mar & Apr 2026
    # True Blind Test: >= '2026-05-01'
    train_mask = dates_full < '2026-03-01'
    val_mask = (dates_full >= '2026-03-01') & (dates_full < '2026-05-01')
    test_mask = dates_full >= '2026-05-01'
    
    X_train, y_train = X_full[train_mask].reset_index(drop=True), y_full[train_mask].reset_index(drop=True)
    X_val, y_val = X_full[val_mask].reset_index(drop=True), y_full[val_mask].reset_index(drop=True)
    X_test, y_test = X_full[test_mask].reset_index(drop=True), y_full[test_mask].reset_index(drop=True)
    
    print(f"[*] Training Set (Jun 2025 - Feb 2026): {len(X_train)} samples")
    print(f"[*] Validation Set (Mar 2026 - Apr 2026): {len(X_val)} samples")
    print(f"[*] TRUE Blind Test Set (May 2026 - Jun 2026): {len(X_test)} samples")
    
    # 1. Walk-Forward Cross Validation + Hyperparameter Tuning
    print("\n[*] Starting Walk-Forward RandomizedSearchCV...")
    tscv = TimeSeriesSplit(n_splits=5, gap=5)
    
    param_dist = {
        "max_depth": [3, 4, 5, 7],
        "learning_rate": [0.01, 0.03, 0.05, 0.1],
        "max_iter": [100, 200, 300],  # equivalent to n_estimators for HistGBM
        "l2_regularization": [0.0, 0.1, 1.0]
    }
    
    base_model = HistGradientBoostingClassifier(
        random_state=42,
        class_weight='balanced'
    )
    
    random_search = RandomizedSearchCV(
        estimator=base_model,
        param_distributions=param_dist,
        n_iter=15,
        cv=tscv,
        scoring='average_precision', # Optimize for PR-AUC
        n_jobs=-1,
        random_state=42,
        verbose=1
    )
    
    random_search.fit(X_train, y_train)
    
    print("\n[*] CV Results across 5 Time Folds (PR-AUC):")
    cv_res = random_search.cv_results_
    best_idx = random_search.best_index_
    for i in range(5):
        score = cv_res[f'split{i}_test_score'][best_idx]
        print(f"    Fold {i+1}: {score:.4f}")
        
    print(f"\n[*] Best Parameters Found: {random_search.best_params_}")
    
    best_model = random_search.best_estimator_
    from sklearn.frozen import FrozenEstimator
    
    print("\n[*] Calibrating Model Probabilities via Isotonic Regression on Validation Set...")
    calibrated_clf = CalibratedClassifierCV(estimator=FrozenEstimator(best_model), method='isotonic')
    calibrated_clf.fit(X_val, y_val)
    
    # 2. True Blind Out-Of-Sample Evaluation
    print("\n=======================================================")
    print("   MODEL PERFORMANCE ON TRUE BLIND DATA (MAY - JUN 2026)")
    print("=======================================================")
    y_pred = calibrated_clf.predict(X_test)
    y_prob = calibrated_clf.predict_proba(X_test)[:, 1]
    
    pr_auc = average_precision_score(y_test, y_prob)
    roc_auc = roc_auc_score(y_test, y_prob)
    
    print(f"[*] Blind PR-AUC Score:  {pr_auc:.4f}")
    print(f"[*] Blind ROC-AUC Score: {roc_auc:.4f}")
    print("\n[*] Classification Report (0.5 Threshold):")
    print(classification_report(y_test, y_pred))
    
    # 3. Export Artifacts
    os.makedirs('data/models', exist_ok=True)
    
    # Save model as joblib
    model_path = 'data/models/macro_regime_model.joblib'
    joblib.dump(calibrated_clf, model_path)
    
    # Save exact feature names
    feature_names = list(X_full.columns)
    with open('data/models/feature_names.json', 'w') as f:
        json.dump(feature_names, f)
        
    # Save metadata
    metadata = {
        "training_window": "Jun 2025 - Feb 2026",
        "validation_window": "Mar 2026 - Apr 2026",
        "true_blind_test_window": "May 2026 - Jun 2026",
        "best_params": random_search.best_params_,
        "blind_pr_auc": pr_auc,
        "blind_roc_auc": roc_auc,
        "export_date": datetime.datetime.now().isoformat()
    }
    with open('data/models/model_metadata.json', 'w') as f:
        json.dump(metadata, f, indent=4)
        
    print(f"\n[SUCCESS] Model and schemas safely exported to data/models/")

if __name__ == '__main__':
    train_and_export_model()
