from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_apprenant
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.user import AdminUser, Apprenant
from app.schemas.auth import AdminOut, ApprenantOut, ApprenantRegister, LoginRequest, Token

router = APIRouter()


@router.post("/register", response_model=ApprenantOut, status_code=status.HTTP_201_CREATED)
def register(payload: ApprenantRegister, db: Session = Depends(get_db)):
    if db.query(Apprenant).filter(Apprenant.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Un compte existe deja avec cet email")
    apprenant = Apprenant(
        firstname=payload.firstname,
        lastname=payload.lastname,
        email=payload.email,
        phone=payload.phone,
        hashed_password=hash_password(payload.password),
    )
    db.add(apprenant)
    db.commit()
    db.refresh(apprenant)
    return apprenant


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    apprenant = db.query(Apprenant).filter(Apprenant.email == payload.email).first()
    if not apprenant or not verify_password(payload.password, apprenant.hashed_password):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    token = create_access_token(subject=str(apprenant.id), role="apprenant")
    return Token(access_token=token)


@router.get("/me", response_model=ApprenantOut)
def me(current: Apprenant = Depends(get_current_apprenant)):
    return current


@router.post("/admin/login", response_model=Token)
def admin_login(payload: LoginRequest, db: Session = Depends(get_db)):
    admin = db.query(AdminUser).filter(AdminUser.email == payload.email).first()
    if not admin or not verify_password(payload.password, admin.hashed_password):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    token = create_access_token(subject=str(admin.id), role="admin")
    return Token(access_token=token)


@router.get("/admin/me", response_model=AdminOut)
def admin_me(current: AdminUser = Depends(get_current_admin)):
    return current
