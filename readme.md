# 🌍 Karachi AQI Forecaster

**Enterprise-Grade Air Quality Prediction System | 10Pearls Internship Project**

This project is an end-to-end Machine Learning pipeline designed to forecast the Air Quality Index (AQI) for Karachi, Pakistan. It leverages historical weather data, advanced feature engineering, and a multi-model approach (Random Forest, XGBoost, LSTM) to provide accurate 72-hour forecasts.

The system is built with a focus on **MLOps best practices**, utilizing a Feature Store, Model Registry, and an interactive Streamlit dashboard for visualization and alerts.

---

## 🚀 Key Features

*   **Multi-Model Architecture:** Trains and compares **Random Forest**, **XGBoost**, and **Deep Learning (LSTM)** models to select the best performer automatically.
*   **Automated Pipelines:**
    *   **Feature Pipeline:** Fetches data from Open-Meteo API, cleans noise, engineers features (lags, rolling averages), and pushes to a Supabase Feature Store.
    *   **Training Pipeline:** Retrains models daily, evaluates metrics (RMSE, MAE, R2), and saves artifacts to a Model Registry.
*   **Advanced Forecasting Logic:**
    *   Predicts 24 hours into the future (Lead Time Forecasting).
    *   Uses "Anchoring" to align forecasts with real-time current AQI.
    *   Simulates organic weather variation (Random Walk drift) for realistic 3-day projections.
*   **Interactive Dashboard:**
    *   Real-time AQI monitoring.
    *   72-hour interactive forecast charts.
    *   **🚨 Hazardous Alerts:** Automatic warnings when AQI exceeds safe thresholds (150/300).
    *   Model performance tracking over time.

---

## 🛠️ Tech Stack

*   **Language:** Python 3.10+
*   **Data Processing:** Pandas, NumPy
*   **Machine Learning:** Scikit-Learn, XGBoost, TensorFlow/Keras (LSTM)
*   **Visualization:** Streamlit, Plotly
*   **Infrastructure:** Supabase (PostgreSQL Database & Object Storage)
*   **API:** Open-Meteo (Historical Weather Data)

---

## 📂 Project Structure

```text
aqi_predictor/
├── models/                  # Local cache for model artifacts
├── src/
│   ├── app/
│   │   └── dashboard.py     # Streamlit Dashboard application
│   ├── features/
│   │   └── feature_pipeline.py  # ETL: Fetch -> Clean -> Engineer -> Store
│   ├── models/
│   │   └── train_model.py       # Training: Load -> Train -> Evaluate -> Register
│   └── utils/
│       └── db_client.py         # Supabase connection helper
├── .env                     # API Keys (Not committed)
├── requirements.txt         # Python dependencies
└── README.md                # Project Documentation
```

---

## ⚙️ Setup & Installation

1.  **Clone the Repository**
    ```bash
    git clone <repository-url>
    cd aqi_predictor
    ```

2.  **Create Virtual Environment**
    ```bash
    python -m venv myenv
    # Windows
    myenv\Scripts\activate
    # Mac/Linux
    source myenv/bin/activate
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables**
    Create a `.env` file in the root directory and add your Supabase credentials:
    ```ini
    SUPABASE_URL=your_supabase_url
    SUPABASE_KEY=your_supabase_anon_key
    ```

---

## 🏃‍♂️ Usage

### 1. Run Feature Pipeline (ETL)
Fetches raw data, cleans it, and updates the Feature Store.
*   **Initial Backfill (6 Months):**
    ```bash
    python src/features/feature_pipeline.py backfill
    ```
*   **Daily Update:**
    ```bash
    python src/features/feature_pipeline.py
    ```

### 2. Train Models
Trains RF, XGBoost, and LSTM models, selects the winner, and uploads to the Registry.
```bash
python src/models/train_model.py
```

### 3. Launch Dashboard
Starts the web interface to view forecasts and alerts.
```bash
streamlit run src/app/dashboard.py
```