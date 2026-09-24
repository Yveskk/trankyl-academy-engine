from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_apprenant, get_current_client
from app.core.ids import generate_unique_id
from app.core.phone import normalize_phone_for_storage, phone_lookup_variants
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.client import Client
from app.models.user import AdminUser, Apprenant
from app.schemas.auth import (
    AdminOut,
    ApprenantOut,
    ApprenantRegister,
    ClientOut,
    ClientRegister,
    ForgotPasswordRequest,
    LoginRequest,
    PhoneLoginRequest,
    ResetPasswordRequest,
    Token,
    VerifyOtpRequest,
    VerifyOtpResponse,
)
from app.services.mail import MailError
from app.services.otp import request_password_reset, reset_password, verify_otp
from app.services.sms import SmsError

router = APIRouter()


@router.post("/register", response_model=ApprenantOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(request: Request, payload: ApprenantRegister, db: Session = Depends(get_db)):
    if db.query(Apprenant).filter(Apprenant.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Un compte existe deja avec cet email")
    apprenant = Apprenant(
        vendor_unique_id=generate_unique_id("VEN"),
        vendor_name=f"{payload.firstname} {payload.lastname}".strip(),
        email=payload.email,
        phone=normalize_phone_for_storage(payload.phone),
        hashed_password=hash_password(payload.password),
        academy_status="apprentice",
        is_active_raw="1",
        created_at=datetime.utcnow(),
    )
    db.add(apprenant)
    db.commit()
    db.refresh(apprenant)
    return apprenant


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
def login(request: Request, payload: PhoneLoginRequest, db: Session = Depends(get_db)):
    apprenant = db.query(Apprenant).filter(Apprenant.phone.in_(phone_lookup_variants(payload.phone))).first()
    if not apprenant or not verify_password(payload.password, apprenant.hashed_password):
        raise HTTPException(status_code=401, detail="Telephone ou mot de passe incorrect")
    token = create_access_token(subject=str(apprenant.id), role="apprenant")
    return Token(access_token=token)


@router.get("/me", response_model=ApprenantOut)
def me(current: Apprenant = Depends(get_current_apprenant)):
    return current


@router.post("/client/register", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register_client(request: Request, payload: ClientRegister, db: Session = Depends(get_db)):
    """Inscription d'un client (foyer/particulier cherchant un prestataire
    via SITA) — table separee des apprenants, ce n'est pas la meme
    personne ni le meme parcours."""
    if db.query(Client).filter(Client.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Un compte existe deja avec cet email")
    client = Client(
        client_unique_id=generate_unique_id("CLI"),
        client_name=f"{payload.firstname} {payload.lastname}".strip(),
        email=payload.email,
        phone=normalize_phone_for_storage(payload.phone),
        hashed_password=hash_password(payload.password),
        is_active_raw=1,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.post("/client/login", response_model=Token)
@limiter.limit("10/minute")
def login_client(request: Request, payload: PhoneLoginRequest, db: Session = Depends(get_db)):
    client = db.query(Client).filter(Client.phone.in_(phone_lookup_variants(payload.phone))).first()
    if not client or not verify_password(payload.password, client.hashed_password):
        raise HTTPException(status_code=401, detail="Telephone ou mot de passe incorrect")
    token = create_access_token(subject=str(client.id), role="client")
    return Token(access_token=token)


@router.get("/client/me", response_model=ClientOut)
def client_me(current: Client = Depends(get_current_client)):
    return current


@router.post("/admin/login", response_model=Token)
@limiter.limit("10/minute")
def admin_login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    admin = db.query(AdminUser).filter(AdminUser.email == payload.email).first()
    if not admin or not verify_password(payload.password, admin.hashed_password):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    token = create_access_token(subject=str(admin.id), role="admin")
    return Token(access_token=token)


@router.get("/admin/me", response_model=AdminOut)
def admin_me(current: AdminUser = Depends(get_current_admin)):
    return current


# --- Mot de passe oublie (OTP par email/SMS, memes identifiants que
# trankyl_backend_nodejs) — commun aux 3 roles (apprenant, client, admin) ---


@router.post("/forgot-password")
@limiter.limit("5/hour")
def forgot_password(request: Request, payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Toujours une reponse generique : ne revele jamais si un compte existe
    pour cet email."""
    try:
        request_password_reset(db, payload.email, payload.role, payload.channel)
    except (MailError, SmsError) as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"detail": "Si un compte existe avec cet email, un code de verification a ete envoye."}


@router.post("/verify-otp", response_model=VerifyOtpResponse)
@limiter.limit("10/hour")
def verify_otp_endpoint(request: Request, payload: VerifyOtpRequest, db: Session = Depends(get_db)):
    try:
        token = verify_otp(db, payload.email, payload.role, payload.code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return VerifyOtpResponse(reset_token=token)


@router.post("/reset-password")
@limiter.limit("10/hour")
def reset_password_endpoint(request: Request, payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    try:
        reset_password(db, payload.email, payload.role, payload.reset_token, payload.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"detail": "Mot de passe reinitialise."}
