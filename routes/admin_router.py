from fastapi import APIRouter, HTTPException, Depends
from auth.dependencies import get_current_user
from db.connection import db
from datetime import datetime, timedelta

router = APIRouter(prefix="/admin", tags=["Admin"])

# ── Admin guard — only allow admin users ─────────────────────────────────────
async def require_admin(current_user=Depends(get_current_user)):
    if not current_user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


# ── Stats ─────────────────────────────────────────────────────────────────────
@router.get("/stats")
async def get_stats(admin=Depends(require_admin)):
    total_users = db.users.count_documents({})
    active_today = db.users.count_documents({
        "last_active": {"$gte": datetime.utcnow() - timedelta(days=1)}
    })
    google_users = db.users.count_documents({"auth_provider": "google"})
    facebook_users = db.users.count_documents({"auth_provider": "facebook"})
    email_users = db.users.count_documents(
        {"auth_provider": {"$exists": False}}
    )
    cached_places = db.places_cache.count_documents(
        {"cache_key": {"$regex": "^details_"}}
    )
    cached_popular = db.places_cache.count_documents(
        {"cache_key": {"$regex": "^popular_"}}
    )
    cached_gems = db.places_cache.count_documents(
        {"cache_key": {"$regex": "^gems_"}}
    )

    return {
        "total_users": total_users,
        "active_today": active_today,
        "google_users": google_users,
        "facebook_users": facebook_users,
        "email_users": email_users,
        "cached_places": cached_places,
        "cached_popular": cached_popular,
        "cached_gems": cached_gems,
    }


# ── Users ─────────────────────────────────────────────────────────────────────
@router.get("/users")
async def get_users(admin=Depends(require_admin)):
    users = list(db.users.find({}, {
        "_id": 1, "name": 1, "email": 1,
        "auth_provider": 1, "is_blocked": 1, "created_at": 1
    }))
    for u in users:
        u["_id"] = str(u["_id"])
    return {"users": users}


@router.post("/users/{user_id}/block")
async def toggle_block(user_id: str, payload: dict,
                       admin=Depends(require_admin)):
    from bson import ObjectId
    db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"is_blocked": payload.get("blocked", True)}}
    )
    return {"success": True}


# ── Cache management ──────────────────────────────────────────────────────────
@router.delete("/cache/{cache_type}")
async def clear_cache(cache_type: str, admin=Depends(require_admin)):
    if cache_type == "details":
        result = db.places_cache.delete_many(
            {"cache_key": {"$regex": "^details_"}}
        )
    elif cache_type == "popular":
        result = db.places_cache.delete_many(
            {"cache_key": {"$regex": "^popular_"}}
        )
    elif cache_type == "gems":
        result = db.places_cache.delete_many(
            {"cache_key": {"$regex": "^gems_"}}
        )
    elif cache_type == "all":
        result = db.places_cache.delete_many({})
    else:
        raise HTTPException(status_code=400, detail="Unknown cache type")

    return {"deleted": result.deleted_count, "cache_type": cache_type}