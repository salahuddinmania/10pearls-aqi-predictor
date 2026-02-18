import os
import sys
import json
import joblib
import pandas as pd
import numpy as np
import tensorflow as tf
from datetime import datetime
from pytz import timezone
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import MinMaxScaler
from sklearn.ensemble import RandomForestRegressor
from xgboost import XGBRegressor

# Add parent directory to path to import utils
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from src.utils.db_client import fetch_training_data, upload_model_to_registry, download_model_from_registry

# Configuration
TARGET = 'aqi'
FEATURES = [
    'pm10', 'pm2_5', 'carbon_monoxide', 'nitrogen_dioxide', 'sulphur_dioxide', 'ozone', 'dust',
    'hour', 'day_of_week', 'month',
    'pm2_5_lag1', 'pm2_5_lag24', 'pm10_lag1', 'pm10_lag24', 'aqi_change_rate',
    'pm2_5_rolling_24h', 'pm2_5_rolling_7d', 'pm10_rolling_24h', 'pm10_rolling_7d'
]

def calculate_metrics(name, y_true, y_pred):
    """
    Calculates detailed performance metrics.
    """
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    r2 = r2_score(y_true, y_pred)
    
    print(f"\n📊 {name} Results:")
    print(f"   RMSE: {rmse:.4f} (Lower is better)")
    print(f"   MAE:  {mae:.4f}")
    print(f"   R2:   {r2:.4f} (Closer to 1.0 is better)")
    
    return {"model": name, "mae": mae, "rmse": rmse, "r2": r2}

if __name__ == "__main__":
    print("--- STARTING DAILY TRAINING PIPELINE ---")
    
    # 1. Fetch Data from Supabase Feature Store
    print("Fetching training data...")
    df = fetch_training_data(table_name="feature_store")
    
    # Ensure 'date' is the index and is datetime
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        
    # Standardize to Karachi Time
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC')
    df.index = df.index.tz_convert('Asia/Karachi')
    
    # Sort by time is CRITICAL for forecasting
    df.sort_index(ascending=True, inplace=True)
    
    # Drop NaNs created by lag features
    df.dropna(subset=FEATURES, inplace=True)
    
    # --- ADD THESE 3 LINES FOR TRUE FORECASTING ---
    # Shift the target so the model learns to predict 24 hours into the future
    df['target_aqi_24h_ahead'] = df['aqi'].shift(-24)
    df.dropna(inplace=True) # Drop the last 24 rows which now have NaN targets
    
    TARGET = 'target_aqi_24h_ahead' # Update the target variable
    
    print(f"Training on {len(df)} rows of data.")
    
    X = df[FEATURES]
    y = df[TARGET]
    
    # 2. Time-Series Split (80% Train, 20% Test)
    # strictly chronological split; no shuffling!
    split_idx = int(len(df) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    
    # 3. Scaling (Essential for LSTM and helps others)
    scaler = MinMaxScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    results = []

    # --- MODEL A: Random Forest (Baseline) ---
    print("\n🌲 Training Random Forest...")
    rf = RandomForestRegressor(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)
    rf.fit(X_train_scaled, y_train)
    y_pred_rf = rf.predict(X_test_scaled)
    results.append(calculate_metrics("Random Forest", y_test, y_pred_rf))

    # --- MODEL B: XGBoost (Gradient Boosting) ---
    print("\n🚀 Training XGBoost...")
    xgb = XGBRegressor(n_estimators=200, learning_rate=0.05, max_depth=5, random_state=42)
    xgb.fit(X_train_scaled, y_train)
    y_pred_xgb = xgb.predict(X_test_scaled)
    results.append(calculate_metrics("XGBoost", y_test, y_pred_xgb))

    # --- 3. Deep Learning (LSTM) ---
    print("\nTraining Deep Learning LSTM...")
    
    # A. Scale the Target Variable (Crucial for Neural Networks!)
    y_scaler = MinMaxScaler()
    y_train_scaled = y_scaler.fit_transform(y_train.values.reshape(-1, 1))
    y_test_scaled = y_scaler.transform(y_test.values.reshape(-1, 1))
    
    # B. Reshape for LSTM [samples, time_steps, features]
    X_train_lstm = X_train_scaled.reshape((X_train_scaled.shape[0], 1, X_train_scaled.shape[1]))
    X_test_lstm = X_test_scaled.reshape((X_test_scaled.shape[0], 1, X_test_scaled.shape[1]))

    # C. Stable Architecture (Removed 'relu' from LSTM layers, using default 'tanh')
    lstm = tf.keras.models.Sequential([
        tf.keras.layers.LSTM(64, return_sequences=True, input_shape=(1, X_train_scaled.shape[1])),
        tf.keras.layers.Dropout(0.2),
        tf.keras.layers.LSTM(32),
        tf.keras.layers.Dense(16, activation='relu'),
        tf.keras.layers.Dense(1, activation='linear') # Linear output for regression
    ])
    
    lstm.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=0.001), loss='mse')
    early_stop = tf.keras.callbacks.EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)

    # D. Train on SCALED target
    lstm.fit(X_train_lstm, y_train_scaled, epochs=50, batch_size=32, 
             validation_data=(X_test_lstm, y_test_scaled), callbacks=[early_stop], verbose=0)

    # E. Predict and INVERSE TRANSFORM back to real AQI values
    lstm_preds_scaled = lstm.predict(X_test_lstm, verbose=0)
    lstm_preds = y_scaler.inverse_transform(lstm_preds_scaled).flatten()

    # F. Evaluate on real AQI values
    results.append(calculate_metrics("LSTM", y_test, lstm_preds))

    # 4. Compare and Select Winner
    # We select the model with the LOWEST RMSE
    best_model_stats = min(results, key=lambda x: x['rmse'])
    print(f"\n🏆 WINNER: {best_model_stats['model']} with RMSE: {best_model_stats['rmse']:.4f}")

    # 5. Save Artifacts locally
    os.makedirs("models", exist_ok=True)
    
    # A. Save Scaler (ALWAYS required)
    joblib.dump(scaler, "models/scaler.pkl")
    upload_model_to_registry("models/scaler.pkl", "scaler.pkl")
    
    # Save Target Scaler (Needed for LSTM in Dashboard)
    joblib.dump(y_scaler, "models/y_scaler.pkl")
    upload_model_to_registry("models/y_scaler.pkl", "y_scaler.pkl")
    
    # B. Save ALL Models (So user can switch in Dashboard)
    print("Saving all models...")
    
    # Random Forest
    joblib.dump(rf, "models/rf_model.pkl", compress=3)
    upload_model_to_registry("models/rf_model.pkl", "rf_model.pkl")
    
    # XGBoost
    joblib.dump(xgb, "models/xgb_model.pkl", compress=3)
    upload_model_to_registry("models/xgb_model.pkl", "xgb_model.pkl")
    
    # LSTM
    lstm.save("models/lstm_model.h5")
    upload_model_to_registry("models/lstm_model.h5", "lstm_model.h5")

    # C. Update History (Append mode)
    print("Updating Training History...")
    history_file = "models/training_history.json"
    
    # Try to download existing history, else start new
    if download_model_from_registry("training_history.json") is None:
        history = []
    else:
        with open(history_file, "r") as f:
            history = json.load(f)
            
    # Append today's results
    new_entry = {
        "date": datetime.now(timezone('Asia/Karachi')).strftime("%Y-%m-%d %H:%M:%S"),
        "winner": best_model_stats['model'],
        "results": results
    }
    history.append(new_entry)
    
    with open(history_file, "w") as f:
        json.dump(history, f, indent=4)
        
    upload_model_to_registry(history_file, "training_history.json")
    
    print("--- TRAINING PIPELINE COMPLETE ---")
    
    
