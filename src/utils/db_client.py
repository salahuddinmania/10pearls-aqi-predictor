import os
from supabase import create_client, Client
from dotenv import load_dotenv
import pandas as pd

# Load environment variables
load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    raise ValueError("Supabase credentials not found. Check your .env file.")

def get_supabase_client() -> Client:
    """Returns an authenticated Supabase client."""
    return create_client(url, key)

def push_features_to_store(df, table_name="feature_store"):
    """
    Pushes a Pandas DataFrame to Supabase.
    Assumes DataFrame index is 'date' or 'timestamp'.
    Handles JSON serialization by converting Timestamps to strings.
    """
    supabase = get_supabase_client()
    
    # 1. Reset index to move 'date' from Index to Column
    data = df.reset_index()
    
    # 2. Create the 'timestamp' column Supabase expects (as a String)
    # We assume the index was named 'date'. If it's different, adjust here.
    data['timestamp'] = data['date'].astype(str)
    
    # 3. CRITICAL FIX: Drop the original 'date' column
    # This removes the non-serializable Timestamp objects
    data = data.drop(columns=['date'])
    
    # 4. Convert DataFrame to list of dictionaries
    records = data.to_dict(orient='records')
    
    # 5. Upsert data
    try:
        response = supabase.table(table_name).upsert(records).execute()
        # Check if response has data to confirm success (Supabase v2 returns object)
        print(f"Success! {len(records)} rows pushed to {table_name}.")
        return response
    except Exception as e:
        print(f"Error pushing to Supabase: {e}")
        
        
# ... (Previous code remains the same) ...

def fetch_training_data(table_name="feature_store"):
    """
    Fetches all data from Supabase for training.
    Returns a Pandas DataFrame.
    """
    supabase = get_supabase_client()
    
    # Fetch all rows (Supabase limits to 1000 by default, so we might need range)
    # For 4000 rows, basic select might be capped. We use CSV download for bulk or range.
    # robust approach for <10k rows:
    response = supabase.table(table_name).select("*").execute()
    data = response.data
    
    if not data:
        raise ValueError("No data found in Feature Store!")
        
    df = pd.DataFrame(data)
    
    # Convert timestamp back to datetime and set index
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        
    return df

def upload_model_to_registry(file_path, file_name, bucket="model-registry"):
    """
    Uploads a .pkl or .h5 file to Supabase Storage.
    """
    supabase = get_supabase_client()
    
    with open(file_path, 'rb') as f:
        try:
            # Overwrite if exists
            response = supabase.storage.from_(bucket).upload(
                path=file_name,
                file=f,
                file_options={"cache-control": "3600", "upsert": "true"}
            )
            print(f"✅ Model saved to Registry: {file_name}")
            return response
        except Exception as e:
            print(f"❌ Error uploading model: {e}")
            
            
def download_model_from_registry(file_name, bucket="model-registry"):
    """
    Downloads a model file from Supabase Storage to the local 'models/' folder.
    """
    supabase = get_supabase_client()
    local_path = os.path.join("models", file_name)
    
    # Ensure local folder exists
    os.makedirs("models", exist_ok=True)
    
    try:
        with open(local_path, 'wb') as f:
            response = supabase.storage.from_(bucket).download(file_name)
            f.write(response)
        print(f"✅ Downloaded {file_name} from Registry.")
        return local_path
    except Exception as e:
        print(f"❌ Error downloading {file_name}: {e}")
        return None