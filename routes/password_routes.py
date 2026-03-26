import random
import smtplib
import string
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from auth.auth_utils import hash_password, verify_password
from auth.dependencies import get_current_user
from db.connection import db

router = APIRouter(prefix="/password", tags=["Password"])

users_collection = db["users"]

# ===================== EMAIL CONFIG =====================
# ⚠️ Replace these with your actual Gmail credentials
GMAIL_ADDRESS = "svaibhavi474@gmail.com"       # ← your Gmail address
GMAIL_APP_PASSWORD = "avhgeflsabhilnlg"      # ← your 16-char Gmail App Password

# ===================== TEMP OTP STORE =====================
# Stores OTPs in memory: { user_id: { "otp": "123456", "expires_at": datetime } }
# For production, use Redis or store in MongoDB instead
_otp_store: dict = {}


# ===================== MODELS =====================
class SendOTPRequest(BaseModel):
    current_password: str


class VerifyOTPRequest(BaseModel):
    otp: str


class ChangePasswordRequest(BaseModel):
    otp: str
    new_password: str
    confirm_password: str


# ===================== HELPERS =====================
def generate_otp() -> str:
    return "".join(random.choices(string.digits, k=6))


def send_otp_email(to_email: str, otp: str, name: str):
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "GoVia — Your Password Change OTP"
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = to_email

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background: #f9fafb; padding: 32px;">
            <div style="max-width: 480px; margin: 0 auto; background: white;
                        border-radius: 16px; padding: 32px; box-shadow: 0 4px 12px rgba(0,0,0,0.08);">
                <h2 style="color: #2BB5A5; margin-bottom: 8px;">GoVia</h2>
                <p style="color: #1F2937;">Hi <strong>{name}</strong>,</p>
                <p style="color: #1F2937;">Your OTP for changing your password is:</p>
                <div style="text-align: center; margin: 24px 0;">
                    <span style="font-size: 40px; font-weight: bold; letter-spacing: 10px;
                                 color: #2BB5A5; background: #f0fdfb; padding: 16px 24px;
                                 border-radius: 12px;">{otp}</span>
                </div>
                <p style="color: #6B7280; font-size: 14px;">
                    This OTP expires in <strong>10 minutes</strong>.
                    If you did not request this, please ignore this email.
                </p>
                <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 24px 0;">
                <p style="color: #9CA3AF; font-size: 12px;">GoVia — Smart City Traveller</p>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, to_email, msg.as_string())

        print(f"✅ OTP email sent to {to_email}")
        return True

    except Exception as e:
        print(f"❌ Email sending failed: {e}")
        return False


# ===================== ROUTES =====================

# Step 1: Verify current password + send OTP
@router.post("/send-otp")
async def send_otp(data: SendOTPRequest, current_user=Depends(get_current_user)):
    # ✅ Block Google users from changing password
    if current_user.get("auth_provider") == "google":
        raise HTTPException(
            status_code=400,
            detail="Google sign-in accounts cannot change password here."
        )

    # ✅ Verify current password
    if not verify_password(data.current_password, current_user["password"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    # ✅ Generate OTP and store with expiry
    otp = generate_otp()
    user_id = str(current_user["_id"])

    _otp_store[user_id] = {
        "otp": otp,
        "expires_at": datetime.utcnow() + timedelta(minutes=10),
    }

    # ✅ Send OTP email
    sent = send_otp_email(
        to_email=current_user["email"],
        otp=otp,
        name=current_user.get("name", "User"),
    )

    if not sent:
        raise HTTPException(status_code=500, detail="Failed to send OTP email. Try again.")

    return {
        "success": True,
        "message": f"OTP sent to {current_user['email']}"
    }


# Step 2: Verify OTP only (optional check before final submit)
@router.post("/verify-otp")
async def verify_otp(data: VerifyOTPRequest, current_user=Depends(get_current_user)):
    user_id = str(current_user["_id"])
    stored = _otp_store.get(user_id)

    if not stored:
        raise HTTPException(status_code=400, detail="No OTP found. Please request a new one.")

    if datetime.utcnow() > stored["expires_at"]:
        _otp_store.pop(user_id, None)
        raise HTTPException(status_code=400, detail="OTP has expired. Please request a new one.")

    if stored["otp"] != data.otp:
        raise HTTPException(status_code=400, detail="Incorrect OTP")

    return {"success": True, "message": "OTP verified"}


# Step 3: Change password
@router.post("/change")
async def change_password(data: ChangePasswordRequest, current_user=Depends(get_current_user)):
    user_id = str(current_user["_id"])
    stored = _otp_store.get(user_id)

    # ✅ Validate OTP again on final submit
    if not stored:
        raise HTTPException(status_code=400, detail="No OTP found. Please request a new one.")

    if datetime.utcnow() > stored["expires_at"]:
        _otp_store.pop(user_id, None)
        raise HTTPException(status_code=400, detail="OTP has expired. Please request a new one.")

    if stored["otp"] != data.otp:
        raise HTTPException(status_code=400, detail="Incorrect OTP")

    # ✅ Validate new password
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    if data.new_password != data.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    # ✅ Hash and save new password
    hashed = hash_password(data.new_password)
    users_collection.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"password": hashed}}
    )

    # ✅ Clear OTP after successful use
    _otp_store.pop(user_id, None)

    return {"success": True, "message": "Password changed successfully"}