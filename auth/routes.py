from fastapi import APIRouter, HTTPException, status, Depends
from auth.models import SignupModel, LoginModel
from auth.auth_utils import hash_password, verify_password
from auth.jwt_helper import create_access_token
from auth.dependencies import get_current_user
from db.connection import db
from firebase_admin import auth as firebase_auth
from fastapi import HTTPException
from auth.models import GoogleLoginModel
import httpx
from pydantic import BaseModel
from auth.models import FacebookLoginModel

router = APIRouter(prefix="/auth", tags=["Auth"])

users_collection = db["users"]


@router.post("/signup")
async def signup(user: SignupModel):
    existing = users_collection.find_one({"email": user.email})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    hashed = hash_password(user.password)

    result = users_collection.insert_one({
        "name": user.name,
        "email": user.email,
        "password": hashed
    })

    return {
        "success": True,
        "message": "Signup successful",
        "user_id": str(result.inserted_id)
    }


@router.post("/login")
async def login(credentials: LoginModel):
    user = users_collection.find_one({"email": credentials.email})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email or password"
        )

    if not verify_password(credentials.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email or password"
        )

    access_token = create_access_token({"sub": str(user["_id"])})

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "message": "Login successful",
        "user": {
            "name": user["name"],
            "email": user["email"]
        }
    }


@router.get("/me")
async def get_me(current_user=Depends(get_current_user)):
    current_user.pop("password", None)
    current_user["_id"] = str(current_user["_id"])
    return current_user

@router.post("/google")
def google_login(payload: GoogleLoginModel):
    try:
        decoded_token = firebase_auth.verify_id_token(payload.id_token,  clock_skew_seconds=60)
    except Exception as e:
        # ✅ Print real error so you can see it in backend logs
        print(f"❌ Firebase token verification failed: {e}")
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {str(e)}")

    uid = decoded_token["uid"]
    email = decoded_token.get("email")
    name = decoded_token.get("name")
    picture = decoded_token.get("picture")

    if not email:
        raise HTTPException(status_code=400, detail="Email not found in token")

    user = db.users.find_one({"email": email})

    if not user:
        result = db.users.insert_one({
            "email": email,
            "name": name,
            "google_uid": uid,
            "auth_provider": "google",
            "profile_image": picture,
            "is_active": True,
        })
        user_id = str(result.inserted_id)
    else:
        user_id = str(user["_id"])

    access_token = create_access_token(
        data={"sub": user_id}
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user_id,
            "email": email,
            "name": name,
            "profile_image": picture,
        }
    }

@router.post("/facebook")
async def facebook_login(payload: FacebookLoginModel):
    try:
        # ✅ Verify token with Facebook Graph API
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://graph.facebook.com/me",
                params={
                    "fields": "id,name,email,picture",
                    "access_token": payload.access_token,
                },
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid Facebook token")

        fb_data = resp.json()
        if "error" in fb_data:
            raise HTTPException(status_code=401, detail=fb_data["error"].get("message", "Facebook auth failed"))

        fb_id = fb_data.get("id")
        email = fb_data.get("email")
        name = fb_data.get("name", "")
        picture = fb_data.get("picture", {}).get("data", {}).get("url", "")

        if not fb_id:
            raise HTTPException(status_code=400, detail="Could not get Facebook user ID")

        # ✅ Find or create user
        user = db.users.find_one({"$or": [
            {"facebook_id": fb_id},
            {"email": email} if email else {"facebook_id": fb_id}
        ]})

        if not user:
            result = db.users.insert_one({
                "email": email or f"fb_{fb_id}@facebook.com",
                "name": name,
                "facebook_id": fb_id,
                "auth_provider": "facebook",
                "profile_image": picture,
                "is_active": True,
            })
            user_id = str(result.inserted_id)
        else:
            user_id = str(user["_id"])
            # Update profile image if changed
            db.users.update_one(
                {"_id": user["_id"]},
                {"$set": {"profile_image": picture, "name": name}}
            )

        access_token = create_access_token(data={"sub": user_id})

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user_id,
                "email": email,
                "name": name,
                "profile_image": picture,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Facebook login error: {e}")
        raise HTTPException(status_code=500, detail=f"Facebook login failed: {str(e)}")