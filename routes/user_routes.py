import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional
from auth.dependencies import get_current_user
from db.connection import db
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/user", tags=["User"])

users_collection = db["users"]

# ✅ Read from .env — never hardcode IP again
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
UPLOAD_DIR = "uploads/profile_pictures"


# ===== Request Model =====
class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    language: Optional[str] = None
    profile_image: Optional[str] = None


# ===== Upload Profile Picture =====
@router.post("/upload-picture")
async def upload_profile_picture(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    print(f"📸 Upload received: filename={file.filename}, content_type={file.content_type}")

    allowed_extensions = ["jpg", "jpeg", "png", "webp"]

    raw_name = file.filename or "image.jpg"
    ext = raw_name.split(".")[-1].lower() if "." in raw_name else "jpg"

    if ext not in allowed_extensions:
        ct = file.content_type or ""
        if "jpeg" in ct or "jpg" in ct:
            ext = "jpg"
        elif "png" in ct:
            ext = "png"
        elif "webp" in ct:
            ext = "webp"
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type. Got extension: '{ext}', content_type: '{file.content_type}'"
            )

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    print(f"📦 File size: {size_mb:.2f} MB")

    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Max 5MB.")

    os.makedirs(UPLOAD_DIR, exist_ok=True)

    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(contents)

    print(f"✅ Saved to: {filepath}")

    image_url = f"{BASE_URL}/uploads/profile_pictures/{filename}"
    print(f"🌐 Image URL: {image_url}")

    return {
        "success": True,
        "image_url": image_url
    }


# ===== Update Profile =====
@router.put("/update")
async def update_profile(
    data: UpdateProfileRequest,
    current_user=Depends(get_current_user)
):
    update_data = {k: v for k, v in data.dict().items() if v is not None}

    if not update_data:
        raise HTTPException(status_code=400, detail="No data provided")

    if "profile_image" in update_data:
        old_image = current_user.get("profile_image")
        if old_image and "/uploads/profile_pictures/" in old_image:
            old_filename = old_image.split("/uploads/profile_pictures/")[-1]
            old_path = os.path.join(UPLOAD_DIR, old_filename)
            if os.path.exists(old_path):
                os.remove(old_path)
                print(f"🗑️ Deleted old image: {old_path}")

    users_collection.update_one(
        {"_id": current_user["_id"]},
        {"$set": update_data}
    )

    updated_user = users_collection.find_one({"_id": current_user["_id"]})
    updated_user["_id"] = str(updated_user["_id"])
    updated_user.pop("password", None)

    return {
        "message": "Profile updated successfully",
        "user": updated_user
    }