import duckdb
import pandas as pd
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report, roc_auc_score
import joblib
import os

def create_training_data():
    conn = duckdb.connect('vanguard.duckdb')
    query = """
        SELECT date, symbol, spot_close, spot_change_pct, ifs_score, 
               net_inv_shift, gex_shift, iv_shift, call_wall, put_wall
        FROM daily_market_structure
        ORDER BY symbol, date
    """
    df = conn.execute(query).fetchdf()

    features = []
    labels = []

    for symbol, group in df.groupby('symbol'):
        group = group.reset_index(drop=True)
        for i in range(len(group) - 1):
            row_t = group.iloc[i]
            row_t1 = group.iloc[i + 1]
            
            # Skip if walls are missing or 0 to prevent division by zero
            if row_t['call_wall'] == 0 or row_t['put_wall'] == 0 or row_t['spot_close'] == 0:
                continue

            dist_to_cw = (row_t['call_wall'] - row_t['spot_close']) / row_t['spot_close'] * 100
            dist_to_pw = (row_t['spot_close'] - row_t['put_wall']) / row_t['spot_close'] * 100
            
            f = {
                'spot_change_pct_t': float(row_t['spot_change_pct']),
                'ifs_score_t': float(row_t['ifs_score']),
                'net_inv_shift_t': float(row_t['net_inv_shift']),
                'gex_shift_t': float(row_t['gex_shift']),
                'dist_to_cw': float(dist_to_cw),
                'dist_to_pw': float(dist_to_pw)
            }
            
            # Target Label: 1 if T+1 breakout is > 3.5%
            label = 1 if row_t1['spot_change_pct'] > 3.5 else 0
            
            features.append(f)
            labels.append(label)
            
    return pd.DataFrame(features), pd.Series(labels)

def train_and_export_model():
    print("[*] Generating ML Features from vanguard.duckdb...")
    X, y = create_training_data()
    
    print(f"[*] Total Samples: {len(X)}")
    print(f"[*] Breakout Events (Target=1): {y.sum()}")
    
    # Train-test split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    
    # HistGradientBoosting doesn't support scale_pos_weight directly,
    # so we'll use class_weight 'balanced'
    print("[*] Training HistGradientBoostingClassifier (Scikit-Learn)...")
    
    model = HistGradientBoostingClassifier(
        max_iter=200,
        max_depth=4,
        learning_rate=0.05,
        class_weight='balanced',
        random_state=42
    )
    
    model.fit(X_train, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]
    
    auc = roc_auc_score(y_test, y_prob)
    print(f"\\n[*] Model AUC Score: {auc:.4f}")
    print("[*] Classification Report:")
    print(classification_report(y_test, y_pred))
    
    # Export model
    os.makedirs('data/models', exist_ok=True)
    model_path = 'data/models/breakout_model.joblib'
    joblib.dump(model, model_path)
    print(f"[SUCCESS] Model exported to {model_path}")

if __name__ == '__main__':
    train_and_export_model()
