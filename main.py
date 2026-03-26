from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from auth.routes import router as auth_router
from db.connection import create_indexes, client
from routes.user_routes import router as user_router
from routes.password_routes import router as password_router
from routes.place_routes import router as places_router
from routes.admin_router import router as admin_router
from routes.place_routes import (
    get_popular_places,
    get_nearby_places,
    get_hidden_gems,
)
import core.firebase
import os
import asyncio

app = FastAPI(title="GoVia Backend", version="1.0.0")

@app.on_event("startup")
async def startup_event():
    # ✅ Check MongoDB connection
    try:
        client.admin.command('ping')
        print("✅ MongoDB Atlas Connected")
    except Exception as e:
        print("❌ MongoDB Connection Failed:", e)

    # ✅ Create indexes
    create_indexes()

    # ✅ Create folders
    os.makedirs("uploads/profile_pictures", exist_ok=True)

    # ✅ Prewarm cache
    asyncio.create_task(_prewarm_cache())
    


async def _prewarm_cache():
    await asyncio.sleep(5)  # Give server more time to fully start
    print("🔥 Pre-warming cache...")

    # ✅ Warm each independently — one failure won't stop the others
    try:
        await get_popular_places(city="mumbai")
        print("✅ Popular cache warmed")
    except Exception as e:
        print(f"⚠️ Popular warm failed (will load on first request): {e}")

    try:
        await get_nearby_places(city="mumbai")
        print("✅ Nearby cache warmed")
    except Exception as e:
        print(f"⚠️ Nearby warm failed (will load on first request): {e}")

    try:
        await get_hidden_gems(city="mumbai", lat=None, lon=None, radius_km=10.0)
        print("✅ Gems cache warmed")
    except Exception as e:
        print(f"⚠️ Gems warm failed (will load on first request): {e}")

    print("🚀 Cache pre-warming complete!")


# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static files ──────────────────────────────────────────────────────────────
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(password_router)
app.include_router(places_router)
app.include_router(admin_router)


@app.get("/")
async def root():
    return {"message": "GoVia backend is running 🚀"}