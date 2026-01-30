import openmeteo_requests
import requests_cache
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
    """
    Fetches hourly AQI data. 
    Default: 180 days (6 Months) as per Project Requirements.
    """
    print(f"Fetching data for the last {days_back} days...")
    
    # Setup Open-Meteo client with caching
    cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
    retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
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

    for i, col in enumerate(FEATURE_COLS + ["aqi"]):
        hourly_data[col] = hourly.Variables(i).ValuesAsNumpy()

    df = pd.DataFrame(data=hourly_data)
    df.set_index('date', inplace=True)
    return df

def clean_data(df):
    """
    Applies Enterprise Cleaning verified in EDA.
    1. Interpolation
    2. Negative Value Removal
    3. Outlier Capping (Winsorization)
    """
    print("Starting Data Cleaning...")
    
    # 1. Fill Missing Values
    df.interpolate(method='linear', inplace=True)
    
    # 2. Force Negatives to 0 (Physically impossible)
    df[df < 0] = 0
    
    # 3. Cap Outliers (1st - 99th Percentile Rule)
    # We do NOT cap the target 'aqi', only input features.
    for col in FEATURE_COLS:
        lower = df[col].quantile(0.01)
        upper = df[col].quantile(0.99)
        df[col] = df[col].clip(lower=lower, upper=upper)
        
    print("Data Cleaning Complete.")
    return df

def feature_engineering(df):
    """
    Generates derived features as required by Project Docs (Source 31).
    """
    print("Starting Feature Engineering...")
    
    # 1. Time-Based Features
    df['hour'] = df.index.hour
    df['day_of_week'] = df.index.dayofweek
    df['month'] = df.index.month
    
    # 2. Lag Features (History) - Crucial for Forecasting
    # "What was the PM2.5 level 1 hour ago? 24 hours ago?"
    for col in ['pm2_5', 'pm10', 'nitrogen_dioxide']:
        df[f'{col}_lag1'] = df[col].shift(1)   # Previous Hour
        df[f'{col}_lag24'] = df[col].shift(24) # Previous Day
        
    # 3. Rolling Window Features (Trends)
    # "What was the average AQI over the last 24 hours?"
    df['pm2_5_rolling_24h'] = df['pm2_5'].rolling(window=24).mean()
    
    # 4. Drop NaN values created by shifting/rolling
    df.dropna(inplace=True)
    
    print(f"Feature Engineering Complete. Final Columns: {df.shape[1]}")
    return df

if __name__ == "__main__":
    # --- ENTERPRISE PIPELINE EXECUTION ---
    
    # CLI Argument to control Backfill vs Update
    # Usage: python src/features/feature_pipeline.py backfill
    mode = "update"
    if len(sys.argv) > 1 and sys.argv[1] == "backfill":
        mode = "backfill"
        days = 180 # 6 Months [Requirement Check: PASSED]
    else:
        days = 3   # Standard Incremental Update
        
    print(f"--- RUNNING PIPELINE (Mode: {mode} | Days: {days}) ---")
    
    # 1. Fetch
    raw_df = fetch_weather_data(days_back=days)
    
    # 2. Clean
    clean_df = clean_data(raw_df)
    
    # 3. Engineer Features (New Step)
    final_df = feature_engineering(clean_df)
    
    # 4. Push to Feature Store
    # Note: Ensure your Supabase table has columns for the new features 
    # (hour, day_of_week, pm2_5_lag1, etc.) or uses JSONB.
    push_features_to_store(final_df, table_name="feature_store")
    
    print("--- PIPELINE SUCCESS ---")