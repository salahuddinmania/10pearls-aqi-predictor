import os
from supabase import create_client, Client, ClientOptions
from dotenv import load_dotenv
import pandas as pd

# Load environment variables
load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    raise ValueError("Supabase credentials not found. Check your .env file.")

def get_supabase_client() -> Client:
    """Returns an authenticated Supabase client with extended timeouts."""
    return create_client(url, key, options=ClientOptions(
        postgrest_client_timeout=300, storage_client_timeout=300
    ))

def push_features_to_store(df, table_name="feature_store"):
    """Pushes a Pandas DataFrame to Supabase Feature Store."""
    supabase = get_supabase_client()
    
    # Prepare data for JSON serialization
    data = df.reset_index()
    data['timestamp'] = data['date'].astype(str)
    data = data.drop(columns=['date'])
    
    records = data.to_dict(orient='records')
    
    try:
        response = supabase.table(table_name).upsert(records).execute()
        print(f"Success! {len(records)} rows pushed to {table_name}.")
        return response
    except Exception as e:
        print(f"Error pushing to Supabase: {e}")
        
def fetch_training_data(table_name="feature_store"):
    """Fetches latest training data from Supabase."""
    supabase = get_supabase_client()
    
    # Fetch latest 5000 rows
    response = supabase.table(table_name).select("*").order("timestamp", desc=True).limit(5000).execute()
    data = response.data
    
    if not data:
        raise ValueError("No data found in Feature Store!")
        
    df = pd.DataFrame(data)
    
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        
    return df

def upload_model_to_registry(file_path, file_name, bucket="model-registry"):
    """Uploads a model artifact to Supabase Storage."""
    supabase = get_supabase_client()
    
    try:
        with open(file_path, 'rb') as f:
            supabase.storage.from_(bucket).upload(
                path=file_name,
                file=f.read(),
                file_options={"cache-control": "3600", "upsert": "true"}
            )
        print(f"✅ Model saved to Registry: {file_name}")
    except Exception as e:
        print(f"❌ Error uploading model: {e}")
            
            
def download_model_from_registry(file_name, bucket="model-registry"):
    """Downloads a model artifact from Supabase Storage."""
    supabase = get_supabase_client()
    local_path = os.path.join("models", file_name)
    os.makedirs("models", exist_ok=True)
    
    try:
        with open(local_path, 'wb') as f:
            response = supabase.storage.from_(bucket).download(file_name)
            f.write(response)
        print(f"✅ Downloaded {file_name} from Registry.")
        return local_path
    except Exception as e:
        print(f"❌ Error downloading {file_name}: {e}")
        if os.path.exists(local_path):
            os.remove(local_path)
        return None