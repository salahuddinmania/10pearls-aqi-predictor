import os
import sys
import json
import joblib
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import tensorflow as tf
import shap
import matplotlib.pyplot as plt
from datetime import timedelta

# Add parent directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from src.utils.db_client import fetch_training_data, download_model_from_registry

# Configuration
st.set_page_config(page_title="Karachi AQI Forecaster", page_icon="🌍", layout="wide")

st.title("🌍 Karachi Air Quality Forecaster")
st.markdown("Enterprise MLOps Project | **10Pearls Internship**")

st.sidebar.header("⚙️ System Status")
if st.sidebar.button("🔄 Reload Models"):
    st.cache_data.clear()
    st.cache_resource.clear()
    st.rerun()

@st.cache_data
def load_data():
    """Fetches and preprocesses training data from Feature Store."""
    with st.spinner("Fetching data..."):
        df = fetch_training_data(table_name="feature_store")
        
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        df.index = df.index.tz_convert('Asia/Karachi')
        
        return df.sort_index(ascending=True)

@st.cache_resource
def load_artifacts():
    """Downloads and loads model artifacts from Registry."""
    with st.spinner("Loading artifacts..."):
        artifacts = [
            "scaler.pkl", "y_scaler.pkl", "rf_model.pkl", 
            "xgb_model.pkl", "lstm_model.h5", "training_history.json"
        ]
        for art in artifacts:
            download_model_from_registry(art)
        
        scaler = joblib.load("models/scaler.pkl") if os.path.exists("models/scaler.pkl") else None
        y_scaler = joblib.load("models/y_scaler.pkl") if os.path.exists("models/y_scaler.pkl") else None
        
        models = {}
        if os.path.exists("models/rf_model.pkl"):
            try: models["Random Forest"] = joblib.load("models/rf_model.pkl")
            except: pass
        if os.path.exists("models/xgb_model.pkl"):
            try: models["XGBoost"] = joblib.load("models/xgb_model.pkl")
            except: pass
        if os.path.exists("models/lstm_model.h5"):
            try: models["LSTM"] = tf.keras.models.load_model("models/lstm_model.h5", compile=False)
            except: pass
            
        history = []
        if os.path.exists("models/training_history.json"):
            with open("models/training_history.json", "r") as f:
                history = json.load(f)
            
        return models, scaler, y_scaler, history

def generate_forecast(model, scaler, y_scaler, df_history, hours=72):
    """Generates a 72-hour forecast with dynamic features and anchoring."""
    last_timestamp = df_history.index[-1]
    if isinstance(last_timestamp, str):
        last_timestamp = pd.to_datetime(last_timestamp)
        
    future_dates = [last_timestamp + timedelta(hours=i) for i in range(1, hours + 1)]
    future_df = pd.DataFrame(index=future_dates)
    
    pollutant_features = ['pm2_5', 'pm10', 'nitrogen_dioxide', 'carbon_monoxide', 'sulphur_dioxide', 'ozone', 'dust']
    
    # 1. Pattern Projection & Variation
    last_24h_data = df_history[pollutant_features].iloc[-24:]
    repetitions = (hours // 24) + 1
    projected_values = np.tile(last_24h_data.values, (repetitions, 1))[:hours]
    future_df[pollutant_features] = projected_values
    
    np.random.seed(42) 
    for col in pollutant_features:
        base_val = last_24h_data[col].mean()
        drift = np.cumsum(np.random.normal(0, base_val * 0.01, size=hours))
        noise = np.random.normal(0, base_val * 0.05, size=hours)
        future_df[col] += drift + noise
        future_df[col] = future_df[col].clip(lower=0)

    # 2. Feature Engineering
    future_df['hour'] = future_df.index.hour
    future_df['day_of_week'] = future_df.index.dayofweek
    future_df['month'] = future_df.index.month
    
    lookback_window = 24 * 8
    for col in ['pm2_5', 'pm10']:
        combined_series = pd.concat([df_history[col].iloc[-lookback_window:], future_df[col]])
        future_df[f'{col}_rolling_24h'] = combined_series.rolling(window=24, min_periods=1).mean().iloc[-hours:].values
        future_df[f'{col}_rolling_7d'] = combined_series.rolling(window=24*7, min_periods=1).mean().iloc[-hours:].values
        future_df[f'{col}_lag1'] = combined_series.shift(1).iloc[-hours:].values
        future_df[f'{col}_lag24'] = combined_series.shift(24).iloc[-hours:].values
        
    last_diff = df_history['aqi'].diff().iloc[-1]
    if pd.isna(last_diff): last_diff = 0
    decay_factors = [0.95 ** i for i in range(len(future_df))]
    future_df['aqi_change_rate'] = last_diff * np.array(decay_factors)
    
    # 3. Prediction
    features_needed = [
        'pm10', 'pm2_5', 'carbon_monoxide', 'nitrogen_dioxide', 'sulphur_dioxide', 'ozone', 'dust',
        'hour', 'day_of_week', 'month',
        'pm2_5_lag1', 'pm2_5_lag24', 'pm10_lag1', 'pm10_lag24', 'aqi_change_rate',
        'pm2_5_rolling_24h', 'pm2_5_rolling_7d', 'pm10_rolling_24h', 'pm10_rolling_7d'
    ]
    
    # Shift inputs for 24h lead time
    full_timeline = pd.concat([df_history[features_needed], future_df[features_needed]])
    start_idx = len(df_history) - 24
    end_idx = start_idx + hours
    X_inputs = full_timeline.iloc[start_idx : end_idx]
    
    try:
        X_scaled = scaler.transform(X_inputs)
        
        if isinstance(model, tf.keras.Model):
            X_reshaped = X_scaled.reshape((X_scaled.shape[0], 1, X_scaled.shape[1]))
            pred_scaled = model.predict(X_reshaped, verbose=0)
            future_df['predicted_aqi'] = y_scaler.inverse_transform(pred_scaled).flatten() if y_scaler else pred_scaled.flatten()
        else:
            future_df['predicted_aqi'] = model.predict(X_scaled).flatten()
            
        # 4. Anchoring (Bias Correction)
        if len(df_history) >= 25:
            X_anchor = df_history[features_needed].iloc[-25:-24]
            X_anchor_scaled = scaler.transform(X_anchor)
            
            if isinstance(model, tf.keras.Model):
                X_anchor_reshaped = X_anchor_scaled.reshape((X_anchor_scaled.shape[0], 1, X_anchor_scaled.shape[1]))
                pred_scaled = model.predict(X_anchor_reshaped, verbose=0)
                anchor_pred = y_scaler.inverse_transform(pred_scaled).flatten()[0] if y_scaler else pred_scaled.flatten()[0]
            else:
                anchor_pred = model.predict(X_anchor_scaled).flatten()[0]
            
            bias = df_history['aqi'].iloc[-1] - anchor_pred
            decay = np.array([0.95 ** i for i in range(len(future_df))])
            future_df['predicted_aqi'] += bias * decay
            future_df['predicted_aqi'] = future_df['predicted_aqi'].clip(lower=0)
            
        return future_df
        
    except (KeyError, ValueError) as e:
        st.error(f"Model/Feature Mismatch: {e}")
        st.stop()
        
# --- Main Execution ---
try:
    df = load_data()
    models, scaler, y_scaler, history = load_artifacts()
    
    st.sidebar.success("✅ System Online")
    st.sidebar.markdown("---")
    
    if scaler is None or not models:
        st.error("⚠️ Artifacts missing. Run training pipeline.")
        st.stop()
        
    st.sidebar.subheader("🎛 Model Selection")
    selected_model_name = st.sidebar.selectbox("Choose Algorithm", list(models.keys()))
    active_model = models[selected_model_name]
    
    if history:
        latest_run = history[-1]['results']
        metrics = next((m for m in latest_run if m["model"] == selected_model_name), None)
        if metrics:
            st.sidebar.info(f"**{selected_model_name} Performance**")
            st.sidebar.text(f"RMSE: {metrics['rmse']:.2f}")
            st.sidebar.text(f"MAE: {metrics['mae']:.2f}")
    
    # Generate Forecast
    latest_record = df.iloc[-1]
    forecast_df = generate_forecast(active_model, scaler, y_scaler, df, hours=72)

    # Alerts
    max_forecast = forecast_df['predicted_aqi'].max()
    current_aqi = latest_record['aqi']

    if current_aqi > 300 or max_forecast > 300:
        st.error("🚨 **HAZARDOUS AIR QUALITY WARNING:** AQI > 300. Remain indoors.", icon="⚠️")
    elif current_aqi > 150 or max_forecast > 150:
        st.warning("😷 **UNHEALTHY AIR QUALITY:** AQI > 150. Reduce outdoor exertion.", icon="⚠️")

    # Metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Current AQI", f"{current_aqi:.0f}", delta_color="inverse")
    c2.metric("Tomorrow's Avg", f"{forecast_df.iloc[0:24]['predicted_aqi'].mean():.0f}")
    c3.metric("Model", selected_model_name)
    c4.metric("Last Updated", str(latest_record.name.strftime('%Y-%m-%d %H:%M')))

    # Chart
    st.subheader("📉 AQI Forecast & History (Last 10 Days)")
    fig = go.Figure()
    
    history_subset = df.tail(24 * 10)
    fig.add_trace(go.Scatter(x=history_subset.index, y=history_subset['aqi'], mode='lines', name='Historical', line=dict(color='#1f77b4', width=2)))
    
    last_pt = pd.DataFrame({'predicted_aqi': [history_subset['aqi'].iloc[-1]]}, index=[history_subset.index[-1]])
    forecast_plot = pd.concat([last_pt, forecast_df[['predicted_aqi']]])
    
    fig.add_trace(go.Scatter(x=forecast_plot.index, y=forecast_plot['predicted_aqi'], mode='lines', name='Forecast', line=dict(color='#ff7f0e', width=2, dash='dot')))
    fig.add_hline(y=100, line_dash="dash", line_color="red", annotation_text="Unhealthy Threshold")
    fig.update_layout(xaxis_title="Date/Time", yaxis_title="AQI Level", hovermode="x unified", xaxis=dict(rangeslider=dict(visible=True), type="date"))
    st.plotly_chart(fig, width='stretch')

    # Details
    st.subheader("📊 Forecast Data (Next 72 Hours)")
    st.dataframe(forecast_df[['predicted_aqi']].head(72).style.format("{:.1f}"), use_container_width=True)

    # Explainability
    st.markdown("---")
    st.subheader("🔍 Model Explainability (SHAP)")
    st.markdown("See which features are driving the **Next Hour's** forecast.")
    
    if st.checkbox("Show Feature Importance"):
        with st.spinner("Calculating SHAP values... (This may take a moment)"):
            try:
                # 1. Prepare Input (T-23 to predict T+1)
                features = [
                    'pm10', 'pm2_5', 'carbon_monoxide', 'nitrogen_dioxide', 'sulphur_dioxide', 'ozone', 'dust',
                    'hour', 'day_of_week', 'month',
                    'pm2_5_lag1', 'pm2_5_lag24', 'pm10_lag1', 'pm10_lag24', 'aqi_change_rate',
                    'pm2_5_rolling_24h', 'pm2_5_rolling_7d', 'pm10_rolling_24h', 'pm10_rolling_7d'
                ]
                
                # Input for T+1 forecast comes from T-23 (due to 24h lead time)
                input_data = df[features].iloc[-24].to_frame().T
                input_scaled = scaler.transform(input_data)
                
                # 2. Calculate SHAP
                shap_values = None
                
                if selected_model_name in ["Random Forest", "XGBoost"]:
                    explainer = shap.TreeExplainer(active_model)
                    shap_values = explainer.shap_values(input_scaled)
                else:
                    # LSTM/Generic: Use KernelExplainer with small background sample
                    background = df[features].sample(20, random_state=42)
                    background_scaled = scaler.transform(background)
                    
                    def model_wrapper(x):
                        if isinstance(active_model, tf.keras.Model):
                            x = x.reshape((x.shape[0], 1, x.shape[1]))
                            return active_model.predict(x, verbose=0).flatten()
                        return active_model.predict(x).flatten()
                    
                    explainer = shap.KernelExplainer(model_wrapper, background_scaled)
                    shap_values = explainer.shap_values(input_scaled)

                # 3. Visualize
                if shap_values is not None:
                    if isinstance(shap_values, list): shap_values = shap_values[0]
                    
                    fig = plt.figure(figsize=(10, 5))
                    shap.summary_plot(shap_values, input_data, feature_names=features, plot_type="bar", show=False)
                    st.pyplot(fig)
                    
            except Exception as e:
                st.error(f"Could not generate SHAP plot: {e}")

    # History
    st.markdown("---")
    st.subheader("📜 Model Training History")
    if history:
        history_data = []
        for entry in history:
            for res in entry['results']:
                history_data.append({
                    "Date": entry['date'], "Model": res['model'], 
                    "RMSE": res['rmse'], "MAE": res.get('mae', np.nan), "R2": res.get('r2', np.nan)
                })
        hist_df = pd.DataFrame(history_data)
        fig_hist = px.line(hist_df, x="Date", y="RMSE", color="Model", markers=True, title="Model Performance Trend (RMSE)")
        st.plotly_chart(fig_hist, width='stretch')
        st.subheader("📋 Detailed Training Logs")
        st.dataframe(hist_df.sort_values(by="Date", ascending=False), use_container_width=True)
    else:
        st.info("No training history available.")

except Exception as e:
    st.error(f"System Error: {e}")
    st.stop()