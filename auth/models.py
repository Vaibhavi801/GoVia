from pydantic import BaseModel, EmailStr, Field

class SignupModel(BaseModel):
    name: str = Field(..., min_length=2, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)

class LoginModel(BaseModel):
    email: EmailStr
    password: str

class GoogleLoginModel(BaseModel):
    id_token: str

class FacebookLoginModel(BaseModel):
    access_token: str