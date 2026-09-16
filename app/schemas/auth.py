from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


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
