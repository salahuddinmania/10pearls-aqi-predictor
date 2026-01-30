import streamlit as st
import pandas as pd
import joblib
import plotly.express as px
import plotly.graph_objects as go
import sys
import os
import json
import numpy as np
from datetime import timedelta

# Add parent directory to path to import utils
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from src.utils.db_client import fetch_training_data, download_model_from_registry

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Karachi AQI Forecaster", page_icon="🌍", layout="wide")

# --- HEADER ---
st.title("🌍 Karachi Air Quality Forecaster")
st.markdown("Enterprise MLOps Project | **10Pearls Internship**")

# --- SIDEBAR: SYSTEM STATUS ---
st.sidebar.header("⚙️ System Status")

# --- 1. LOAD DATA & MODELS ---
@st.cache_data
def load_data():
    with st.spinner("Fetching data from Supabase Feature Store..."):
        df = fetch_training_data(table_name="feature_store")
        df = df.sort_index()
        return df

@st.cache_resource
def load_artifacts():
    with st.spinner("Downloading Model Artifacts..."):
        # Download all necessary files
        download_model_from_registry("scaler.pkl")
        download_model_from_registry("best_model.pkl") # Or .h5 if LSTM won
        download_model_from_registry("metrics.json")
        
        scaler = joblib.load("models/scaler.pkl")
        model = joblib.load("models/best_model.pkl")
        
        # Load metrics to find out WHICH model is running
        with open("models/metrics.json", "r") as f:
            metrics = json.load(f)
            # Find the winner (lowest RMSE)
            best_model_info = min(metrics, key=lambda x: x['rmse'])
            
        return model, scaler, best_model_info

try:
    df = load_data()
    model, scaler, model_info = load_artifacts()
    
    st.sidebar.success("✅ System Online")
    st.sidebar.markdown("---")
    st.sidebar.subheader("🏆 Current Model")
    st.sidebar.info(f"**Algorithm:** {model_info['model']}")
    st.sidebar.text(f"RMSE: {model_info['rmse']:.2f}")
    st.sidebar.text(f"MAE: {model_info['mae']:.2f}")
    
except Exception as e:
    st.error(f"System Error: {e}")
    st.stop()

# --- 2. FORECASTING LOGIC (Next 3 Days) ---
def generate_forecast(model, scaler, df_history, hours=72):
    """
    Generates an intelligent 3-day forecast.
    Includes Type-Safety checks to prevent String/Timestamp errors.
    """
    # --- FIX: Ensure Timestamp is strictly Datetime object ---
    last_timestamp = df_history.index[-1]
    
    # If it's a string (e.g., "2026-01-30..."), convert it.
    if isinstance(last_timestamp, str):
        last_timestamp = pd.to_datetime(last_timestamp)
        
    future_dates = [last_timestamp + timedelta(hours=i) for i in range(1, hours + 1)]
    future_df = pd.DataFrame(index=future_dates)
    
    # 1. INTELLIGENCE: Get the stable 'Background Level'
    # We use the mean of the last 24 hours to avoid noise from a single spike
    last_24h_avg = df_history.iloc[-24:].mean(numeric_only=True)
    
    # List of features our model expects
    pollutant_features = ['pm2_5', 'pm10', 'nitrogen_dioxide', 'carbon_monoxide', 'sulphur_dioxide', 'ozone', 'dust']
    
    # Fill future inputs with the stable background level
    for col in pollutant_features:
        future_df[col] = last_24h_avg[col]

    # 2. TEMPORAL INTELLIGENCE: Build Time Features
    future_df['hour'] = future_df.index.hour
    future_df['day_of_week'] = future_df.index.dayofweek
    future_df['month'] = future_df.index.month
    
    # 3. LAG FEATURES
    future_df['pm2_5_lag1'] = last_24h_avg['pm2_5']
    future_df['pm2_5_lag24'] = last_24h_avg['pm2_5'] 
    future_df['pm2_5_rolling_24h'] = last_24h_avg['pm2_5_rolling_24h']
    
    # 4. PREDICT USING MODEL
    features_needed = [
        'pm2_5', 'pm10', 'nitrogen_dioxide', 'carbon_monoxide', 'sulphur_dioxide', 'ozone', 'dust',
        'pm2_5_lag1', 'pm2_5_lag24', 'pm2_5_rolling_24h', 
        'hour', 'day_of_week', 'month'
    ]
    
    try:
        X_future = future_df[features_needed]
        X_scaled = scaler.transform(X_future)
        future_df['predicted_aqi'] = model.predict(X_scaled)
        return future_df
        
    except KeyError as e:
        st.error(f"Feature Mismatch Error: {e}")
        st.stop()
        
        
# Generate the forecast
latest_record = df.iloc[-1]
forecast_df = generate_forecast(model, scaler, df, hours=72)

# --- 3. DASHBOARD LAYOUT ---

# Top Metrics
col1, col2, col3, col4 = st.columns(4)
col1.metric("Current AQI", f"{latest_record['aqi']:.0f}", delta_color="inverse")
col2.metric("Tomorrow's Avg AQI", f"{forecast_df.iloc[0:24]['predicted_aqi'].mean():.0f}")
col3.metric("Model Used", model_info['model'])
col4.metric("Last Updated", str(latest_record.name.strftime('%Y-%m-%d %H:%M')))

# Main Chart: History + Forecast
st.subheader("📉 3-Day AQI Forecast")

fig = go.Figure()

# Plot History (Last 3 Days only to keep chart readable)
history_subset = df.tail(72)
fig.add_trace(go.Scatter(
    x=history_subset.index, 
    y=history_subset['aqi'],
    mode='lines',
    name='Historical (Actual)',
    line=dict(color='#1f77b4', width=2)
))

# Plot Forecast
fig.add_trace(go.Scatter(
    x=forecast_df.index, 
    y=forecast_df['predicted_aqi'],
    mode='lines',
    name='Forecast (Predicted)',
    line=dict(color='#ff7f0e', width=2, dash='dot') # Dashed line for prediction
))

# Add Threshold Line
fig.add_hline(y=100, line_dash="dash", line_color="red", annotation_text="Unhealthy Threshold")
fig.update_layout(xaxis_title="Date/Time", yaxis_title="AQI Level", hovermode="x unified")
st.plotly_chart(fig, use_container_width=True)

# --- 4. DETAILS SECTION ---
col_raw, col_sim = st.columns(2)

with col_raw:
    st.subheader("📊 Forecast Data")
    st.dataframe(forecast_df[['predicted_aqi']].head(12).style.format("{:.1f}"))

with col_sim:
    st.subheader("🛠 Simulation Mode")
    st.write("What if PM2.5 doubles tomorrow?")
    factor = st.slider("Multiply PM2.5 by:", 0.5, 3.0, 1.0)
    
    if factor != 1.0:
        # Run a quick simulation
        sim_record = latest_record.copy()
        sim_record['pm2_5'] = sim_record['pm2_5'] * factor
        sim_forecast = generate_forecast(model, scaler, sim_record, hours=24)
        
        st.write(f"Predicted AQI would change from **{forecast_df.iloc[0]['predicted_aqi']:.0f}** to **{sim_forecast.iloc[0]['predicted_aqi']:.0f}**")