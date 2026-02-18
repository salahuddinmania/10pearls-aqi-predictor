import openmeteo_requests
import requests
import pandas as pd
import numpy as np
from retry_requests import retry
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path to import utils
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from src.utils.db_client import push_features_to_store

# --- CONFIGURATION ---
LAT = 24.8607  # Karachi
LON = 67.0011
# Raw Pollutants (Input)
FEATURE_COLS = ['pm10', 'pm2_5', 'carbon_monoxide', 'nitrogen_dioxide', 'sulphur_dioxide', 'ozone', 'dust']

def fetch_weather_data(days_back=180):
    """Fetches hourly AQI data from Open-Meteo API."""
    print(f"Fetching data for the last {days_back} days...")
    
    # Setup Open-Meteo client
    session = requests.Session()
    retry_session = retry(session, retries=5, backoff_factor=0.2)
    openmeteo = openmeteo_requests.Client(session=retry_session)

    url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days_back)
    
    params = {
        "latitude": LAT,
        "longitude": LON,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "hourly": FEATURE_COLS + ["us_aqi"]
    }

    responses = openmeteo.weather_api(url, params=params)
    response = responses[0]

    # Process into DataFrame
    hourly = response.Hourly()
    hourly_data = {
        "date": pd.date_range(
            start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
            end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=hourly.Interval()),
            inclusive="left"
        )
    }

    # Map API response variables to our DataFrame columns
    api_vars = FEATURE_COLS + ["us_aqi"]
    for i, var_name in enumerate(api_vars):
        col_name = "aqi" if var_name == "us_aqi" else var_name
        hourly_data[col_name] = hourly.Variables(i).ValuesAsNumpy()

    df = pd.DataFrame(data=hourly_data)
    df.set_index('date', inplace=True)
    
    # Convert to Karachi Time (PKT)
    df.index = df.index.tz_convert('Asia/Karachi')
    return df

def clean_data(df):
    """Applies data cleaning: interpolation, smoothing, and outlier capping."""
    print("Starting Data Cleaning...")
    
    # 1. Fill Missing Values
    df.interpolate(method='linear', inplace=True)
    df.fillna(df.mean(), inplace=True)
    
    # 2. Noise Smoothing (3-hour rolling average)
    for col in FEATURE_COLS:
        df[f'{col}_smoothed'] = df[col].rolling(window=3, min_periods=1).mean()
    
    # 3. Cap Outliers using IQR on Smoothed Data
    for col in FEATURE_COLS:
        series = df[f'{col}_smoothed']
        Q1 = series.quantile(0.25)
        Q3 = series.quantile(0.75)
        IQR = Q3 - Q1
        lower = Q1 - 1.5 * IQR
        upper = Q3 + 1.5 * IQR
        df[col] = series.clip(lower=lower, upper=upper)
        
    df.drop(columns=[f'{col}_smoothed' for col in FEATURE_COLS], inplace=True)
    
    # 4. Force Negatives to 0
    df[df < 0] = 0
        
    print("Data Cleaning Complete.")
    return df

def feature_engineering(df):
    """Generates derived features for model training."""
    print("Starting Feature Engineering...")
    
    # Log Transform for Skewed Features
    for col in ['nitrogen_dioxide', 'dust']:
        df[col] = np.log1p(df[col])
    
    # Time-Based Features
    df['hour'] = df.index.hour
    df['day_of_week'] = df.index.dayofweek
    df['month'] = df.index.month
    
    # Lag Features
    for col in ['pm2_5', 'pm10']:
        df[f'{col}_lag1'] = df[col].shift(1)
        df[f'{col}_lag24'] = df[col].shift(24)
        
    # Rolling Window Features
    for col in ['pm2_5', 'pm10']:
        df[f'{col}_rolling_24h'] = df[col].rolling(window=24, min_periods=1).mean()
        df[f'{col}_rolling_7d'] = df[col].rolling(window=24*7, min_periods=1).mean()
        
    # AQI Change Rate (Derivative)
    df['aqi_change_rate'] = df['aqi'].shift(1).diff()
    
    df.dropna(inplace=True)
    
    print(f"Feature Engineering Complete. Final Columns: {df.shape[1]}")
    return df

if __name__ == "__main__":
    mode = "update"
    days = 3
    
    if len(sys.argv) > 1 and sys.argv[1] == "backfill":
        mode = "backfill"
        days = 180
        
    print(f"--- RUNNING PIPELINE (Mode: {mode} | Days: {days}) ---")
    
    raw_df = fetch_weather_data(days_back=days)
    clean_df = clean_data(raw_df)
    final_df = feature_engineering(clean_df)
    push_features_to_store(final_df, table_name="feature_store")
    
    print("--- PIPELINE SUCCESS ---")