import os
from pymongo import MongoClient, ASCENDING
from dotenv import load_dotenv

load_dotenv()

# ✅ Use environment variable (SAFE)
MONGO_URI = os.getenv("MONGO_URI")

if not MONGO_URI:
    raise ValueError("❌ MONGO_URI not found in .env file")

# ✅ Connect to MongoDB Atlas
client = MongoClient(MONGO_URI)

# ✅ Select database
db = client["mysticity"]


def create_indexes():
    try:
        db.places_cache.create_index(
            [("cache_key", ASCENDING)],
            unique=True,
            background=True
        )
        print("✅ MongoDB indexes ready")
    except Exception as e:
        print(f"ℹ️ Indexes already exist: {e}")