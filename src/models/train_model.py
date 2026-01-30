import pandas as pd
import numpy as np
import joblib
import json
import os
import sys

# Metrics & Selection
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import MinMaxScaler

# Models
from sklearn.ensemble import RandomForestRegressor
from xgboost import XGBRegressor

# Deep Learning (TensorFlow/Keras)
import tensorflow as tf

# Utils (Importing your Supabase client)
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from src.utils.db_client import fetch_training_data, upload_model_to_registry

# --- CONFIGURATION ---
TARGET = 'aqi'
# Inputs: Pollutants + Derived Time Features + Lags
FEATURES = [
    'pm2_5', 'pm10', 'nitrogen_dioxide', 'carbon_monoxide', 'sulphur_dioxide', 'ozone', 'dust',
    'pm2_5_lag1', 'pm2_5_lag24', 'pm2_5_rolling_24h', 
    'hour', 'day_of_week', 'month'
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

def train_lstm_model(X_train, y_train, X_test, y_test):
    """
    Trains an LSTM (Long Short-Term Memory) Neural Network.
    Required for the 'Deep Learning' constraint in the project docs.
    """
    # Reshape input to [samples, time_steps, features]
    X_train_rs = X_train.reshape((X_train.shape[0], 1, X_train.shape[1]))
    X_test_rs = X_test.reshape((X_test.shape[0], 1, X_test.shape[1]))
    
    model = tf.keras.models.Sequential([
        tf.keras.layers.LSTM(64, return_sequences=True, input_shape=(1, X_train.shape[1])),
        tf.keras.layers.Dropout(0.2),
        tf.keras.layers.LSTM(32),
        tf.keras.layers.Dropout(0.1),
        tf.keras.layers.Dense(1)
    ])
    
    model.compile(optimizer='adam', loss='mse')
    
    # Early stopping prevents overfitting
    early_stop = tf.keras.callbacks.EarlyStopping(monitor='val_loss', patience=5, restore_best_weights=True)
    
    print("\n🧠 Training LSTM Deep Learning Model...")
    history = model.fit(
        X_train_rs, y_train, 
        epochs=50, 
        batch_size=32, 
        validation_data=(X_test_rs, y_test),
        callbacks=[early_stop],
        verbose=1
    )
    
    y_pred = model.predict(X_test_rs).flatten()
    return model, y_pred

if __name__ == "__main__":
    print("--- STARTING DAILY TRAINING PIPELINE ---")
    
    # 1. Fetch Data from Supabase Feature Store
    print("Fetching training data...")
    df = fetch_training_data(table_name="feature_store")
    
    # Sort by time is CRITICAL for forecasting
    df.sort_index(inplace=True)
    
    # Drop NaNs created by lag features
    df.dropna(subset=FEATURES, inplace=True)
    
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
    rf = RandomForestRegressor(n_estimators=100, max_depth=15, random_state=42)
    rf.fit(X_train, y_train)
    y_pred_rf = rf.predict(X_test)
    results.append(calculate_metrics("Random Forest", y_test, y_pred_rf))

    # --- MODEL B: XGBoost (Gradient Boosting) ---
    print("\n🚀 Training XGBoost...")
    xgb = XGBRegressor(n_estimators=200, learning_rate=0.05, max_depth=5, random_state=42)
    xgb.fit(X_train, y_train)
    y_pred_xgb = xgb.predict(X_test)
    results.append(calculate_metrics("XGBoost", y_test, y_pred_xgb))

    # --- MODEL C: LSTM (Deep Learning) ---
    lstm, y_pred_lstm = train_lstm_model(X_train_scaled, y_train, X_test_scaled, y_test)
    results.append(calculate_metrics("LSTM", y_test, y_pred_lstm))

    # 4. Compare and Select Winner
    # We select the model with the LOWEST RMSE
    best_model_stats = min(results, key=lambda x: x['rmse'])
    print(f"\n🏆 WINNER: {best_model_stats['model']} with RMSE: {best_model_stats['rmse']:.4f}")

    # 5. Save Artifacts locally
    os.makedirs("models", exist_ok=True)
    
    # A. Save Scaler (ALWAYS required)
    joblib.dump(scaler, "models/scaler.pkl")
    upload_model_to_registry("models/scaler.pkl", "scaler.pkl")
    
    # B. Save the Best Model
    if best_model_stats['model'] == "Random Forest":
        joblib.dump(rf, "models/best_model.pkl")
        model_ext = ".pkl"
    elif best_model_stats['model'] == "XGBoost":
        joblib.dump(xgb, "models/best_model.pkl")
        model_ext = ".pkl"
    else:
        # Keras model saving
        lstm.save("models/best_model.h5")
        model_ext = ".h5"
        
    # C. Save Metrics (For Reporting/Analysis)
    with open("models/metrics.json", "w") as f:
        json.dump(results, f, indent=4)
        
    # 6. Push to Supabase Registry
    # We rename it to generic 'best_model' so the Web App doesn't need to know which algo won.
    print(f"Uploading {best_model_stats['model']} to Registry...")
    upload_model_to_registry(f"models/best_model{model_ext}", f"best_model{model_ext}")
    
    print("--- TRAINING PIPELINE COMPLETE ---")
    
    
    # --- ADD THIS NEW LINE ---
    upload_model_to_registry("models/metrics.json", "metrics.json")
    
    print("--- TRAINING PIPELINE COMPLETE ---")