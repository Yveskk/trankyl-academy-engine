from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

Role = Literal["apprenant", "client", "admin"]


class ApprenantRegister(BaseModel):
    firstname: str
    lastname: str
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    phone: str | None = None


class ApprenantOut(BaseModel):
    id: int
    firstname: str
    lastname: str
    email: EmailStr
    phone: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class ClientRegister(BaseModel):
    firstname: str
    lastname: str
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    phone: str | None = None


class ClientOut(BaseModel):
    id: int
    firstname: str
    lastname: str
    email: EmailStr
    phone: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class AdminLogin(BaseModel):
    email: EmailStr
    password: str


class AdminOut(BaseModel):
    id: int
    firstname: str
    lastname: str
    email: EmailStr

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ForgotPasswordRequest(BaseModel):
    email: EmailStr
    role: Role
    channel: Literal["email", "sms"] = "email"


class VerifyOtpRequest(BaseModel):
    email: EmailStr
    role: Role
    code: str


class VerifyOtpResponse(BaseModel):
    reset_token: str


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    role: Role
    reset_token: str
    new_password: str = Field(min_length=8, max_length=72)
