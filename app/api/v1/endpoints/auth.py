from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import current_country, get_current_apprenant, get_current_client
from app.core.config import settings
from app.core.ids import generate_unique_id
from app.core.phone import normalize_phone_for_storage, phone_lookup_variants
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.client import Client
from app.models.user import AdminUser, Apprenant
from app.schemas.auth import (
    AdminOut,
    AuthResult,
    ForgotRequest,
    ResendRequest,
    ResetWithTokenRequest,
    SignupChecked,
    SignupStart,
    VerificationStarted,
    VerifyCodeRequest,
    VerifyResetRequest,
    ApprenantOut,
    ApprenantRegister,
    ClientOut,
    ClientRegister,
    LoginRequest,
    PhoneLoginRequest,
    Token,
)
from app.services import account_deletion as ad
from app.services.countries import marketplace_country_id
from app.services.image_upload import ImageUploadError, upload_image
from app.services.security import accounts as sec
from app.services.security import verification as vf
from app.services.security.delivery import mask_destination

router = APIRouter()


@router.post("/register", response_model=ApprenantOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(request: Request, payload: ApprenantRegister, db: Session = Depends(get_db)):
    _refuse_unverified_signup()
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


@router.post("/login", response_model=AuthResult)
@limiter.limit("10/minute")
def login(request: Request, payload: PhoneLoginRequest, db: Session = Depends(get_db)):
    return _password_login(db, request, "apprenant", payload)


@router.get("/me", response_model=ApprenantOut)
def me(current: Apprenant = Depends(get_current_apprenant)):
    return current


@router.post("/client/register", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register_client(request: Request, payload: ClientRegister, db: Session = Depends(get_db)):
    """Inscription d'un client (foyer/particulier cherchant un prestataire
    via SITA) — table separee des apprenants, ce n'est pas la meme
    personne ni le meme parcours."""
    _refuse_unverified_signup()
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


@router.post("/client/login", response_model=AuthResult)
@limiter.limit("10/minute")
def login_client(request: Request, payload: PhoneLoginRequest, db: Session = Depends(get_db)):
    return _password_login(db, request, "client", payload)


@router.get("/client/me", response_model=ClientOut)
def client_me(current: Client = Depends(get_current_client)):
    return current


# ---- "Mon compte" du client : profil, mot de passe, activite, fermeture
class ClientProfileUpdate(BaseModel):
    firstname: str | None = Field(default=None, min_length=1, max_length=80)
    lastname: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)
    # Exigé pour changer l'e-mail ou le téléphone (identifiants de connexion) : un jeton volé ne suffit pas.
    current_password: str | None = Field(default=None, max_length=200)


class ClientPasswordChange(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


class ClientClose(BaseModel):
    password: str = Field(max_length=200)


def _check_current_password(db: Session, request: Request, client: Client, password: str | None) -> None:
    ip, ua = sec.client_ip(request), sec.client_agent(request)
    _raise_if_locked(db, "client", client.id)
    if not password or not verify_password(password, client.hashed_password or ""):
        remaining = sec.register_failure(db, "client", client.id, ip, ua)
        raise HTTPException(status_code=403, detail=_failure_message("Mot de passe actuel incorrect", remaining))


@router.patch("/client/me", response_model=ClientOut)
@limiter.limit("10/minute")
def update_client_me(request: Request, payload: ClientProfileUpdate, current: Client = Depends(get_current_client), db: Session = Depends(get_db)):
    ip, ua = sec.client_ip(request), sec.client_agent(request)
    changed = []
    first = " ".join((payload.firstname if payload.firstname is not None else current.firstname).split())
    last = " ".join((payload.lastname if payload.lastname is not None else current.lastname).split())
    if not first:
        raise HTTPException(status_code=422, detail="Le prenom est obligatoire.")
    new_email = str(payload.email).strip().lower() if payload.email else None
    new_phone = None
    if payload.phone is not None and payload.phone.strip():
        new_phone = vf.normalize_e164(payload.phone)
        if not new_phone:
            raise HTTPException(status_code=422, detail="Numero de telephone invalide.")
    email_changes = bool(new_email) and new_email != (current.email or "").lower()
    phone_variants = phone_lookup_variants(new_phone) if new_phone else []  # toutes les formes sous lesquelles ce numero peut etre stocke
    phone_changes = bool(new_phone) and (current.phone or "") not in phone_variants
    if email_changes or phone_changes:
        _check_current_password(db, request, current, payload.current_password)
        if email_changes and db.query(Client).filter(Client.email == new_email, Client.id != current.id).first():
            raise HTTPException(status_code=400, detail="Un compte existe deja avec cet email")
        if phone_changes and db.query(Client).filter(Client.phone.in_(phone_variants), Client.id != current.id).first():
            raise HTTPException(status_code=400, detail="Un compte existe deja avec ce numero de telephone")
    if f"{first} {last}".strip() != (current.client_name or "").strip():
        current.client_name = f"{first} {last}".strip()
        changed.append("nom")
    if email_changes:
        current.email = new_email
        changed.append("email")
    if phone_changes:
        current.phone = normalize_phone_for_storage(new_phone)
        changed.append("telephone")
    db.commit()
    if changed:
        sec.log_event(db, "profile_updated", role="client", account_id=current.id, ip=ip, ua=ua, detail=", ".join(changed))
    db.refresh(current)
    return current


_PHOTO_MAX = 3 * 1024 * 1024


def _sniff_image(data: bytes) -> str | None:
    """Type reel de l'image d'apres son contenu (l'en-tete Content-Type envoye par le navigateur n'est pas fiable)."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.post("/client/me/photo", response_model=ClientOut)
@limiter.limit("10/minute")
async def upload_client_photo(request: Request, file: UploadFile = File(...), current: Client = Depends(get_current_client), db: Session = Depends(get_db)):
    data = await file.read(_PHOTO_MAX + 1)
    if len(data) > _PHOTO_MAX:
        raise HTTPException(status_code=413, detail="Photo trop volumineuse (3 Mo maximum).")
    kind = _sniff_image(data)
    if not kind:
        raise HTTPException(status_code=422, detail="Format non supporte : utilisez une photo JPEG, PNG ou WEBP.")
    try:
        url = upload_image(data, kind)
    except ImageUploadError as e:
        raise HTTPException(status_code=502, detail=str(e))
    current.image = url
    db.commit()
    sec.log_event(db, "profile_updated", role="client", account_id=current.id, ip=sec.client_ip(request), ua=sec.client_agent(request), detail="photo")
    db.refresh(current)
    return current


@router.delete("/client/me/photo", response_model=ClientOut)
def delete_client_photo(request: Request, current: Client = Depends(get_current_client), db: Session = Depends(get_db)):
    current.image = None
    db.commit()
    db.refresh(current)
    return current


@router.post("/client/me/password")
@limiter.limit("5/minute")
def change_client_password(request: Request, payload: ClientPasswordChange, current: Client = Depends(get_current_client), db: Session = Depends(get_db)):
    ip, ua = sec.client_ip(request), sec.client_agent(request)
    _check_current_password(db, request, current, payload.current_password)
    try:
        sec.check_password_strength(payload.new_password, email=current.email, phone=current.phone, names=(current.firstname, current.lastname))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if verify_password(payload.new_password, current.hashed_password or ""):
        raise HTTPException(status_code=422, detail="Le nouveau mot de passe doit etre different de l'actuel.")
    current.hashed_password = hash_password(payload.new_password)
    db.commit()
    sec.mark_password_changed(db, "client", current.id)
    sec.revoke_devices(db, "client", current.id)
    sec.log_event(db, "password_changed", role="client", account_id=current.id, ip=ip, ua=ua)
    return {"ok": True}


@router.post("/client/me/devices/revoke")
def revoke_client_devices(request: Request, current: Client = Depends(get_current_client), db: Session = Depends(get_db)):
    """Oublie les appareils de confiance : un code sera redemande a la prochaine connexion."""
    sec.revoke_devices(db, "client", current.id)
    sec.log_event(db, "devices_revoked", role="client", account_id=current.id, ip=sec.client_ip(request), ua=sec.client_agent(request))
    return {"ok": True}


_EVENT_LABELS = {
    "login_ok": "Connexion", "login_failed": "Tentative de connexion échouée", "password_changed": "Mot de passe modifié",
    "profile_updated": "Profil modifié", "devices_revoked": "Appareils de confiance oubliés", "signup": "Compte créé",
    "password_reset": "Mot de passe réinitialisé", "booking_created": "Réservation créée", "booking_cancelled": "Réservation annulée", "booking_edited": "Réservation modifiée", "account_closed": "Compte fermé",
}


@router.get("/client/me/activity")
def client_activity(current: Client = Depends(get_current_client), db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT event, success, ip, created_at FROM academy_security_events WHERE role='client' AND account_id=:i AND event<>'verification_sent' ORDER BY id DESC LIMIT 15"),
        {"i": current.id},
    ).fetchall()
    return [{"event": r[0], "label": _EVENT_LABELS.get(r[0], r[0].replace("_", " ").capitalize()), "success": bool(r[1]), "ip": r[2], "at": r[3].isoformat() if r[3] else None} for r in rows]


@router.post("/client/me/close")
@limiter.limit("3/minute")
def close_client_account(request: Request, payload: ClientClose, current: Client = Depends(get_current_client), db: Session = Depends(get_db)):
    """Fermeture du compte : desactivation (aucune donnee supprimee : l'historique des reservations reste intact)."""
    _check_current_password(db, request, current, payload.password)
    open_bookings = db.execute(
        text("SELECT COUNT(*) FROM bookings WHERE bk_client_id=:i AND (bk_service_status IS NULL OR bk_service_status IN ('0','1'))"), {"i": current.id}
    ).scalar() or 0
    if open_bookings:
        raise HTTPException(status_code=409, detail=f"Vous avez {open_bookings} reservation(s) en cours : annulez-les ou attendez qu'elles soient terminees avant de fermer votre compte.")
    current.is_active_raw = 0
    db.commit()
    sec.revoke_devices(db, "client", current.id)
    sec.log_event(db, "account_closed", role="client", account_id=current.id, ip=sec.client_ip(request), ua=sec.client_agent(request))
    return {"ok": True}


# ====================================================================
# Verification par code (WhatsApp / SMS / email)
# ====================================================================
_ROLE_MODEL = {"apprenant": Apprenant, "client": Client, "admin": AdminUser}


def _refuse_unverified_signup() -> None:
    if settings.require_signup_verification:
        raise HTTPException(status_code=403, detail="L'inscription exige une verification par code : utilisez /auth/signup/start.")


def _failure_message(base: str, attempts_left: int) -> str:
    if attempts_left == 0:
        return f"{base}. Compte verrouille temporairement, reessayez plus tard."
    if attempts_left <= 2:
        return f"{base} ({attempts_left} essai{'s' if attempts_left > 1 else ''} restant{'s' if attempts_left > 1 else ''})"
    return base


def _raise_if_locked(db: Session, role: str, account_id: int) -> None:
    minutes = sec.lock_remaining_minutes(sec.get_security(db, role, account_id))
    if minutes:
        raise HTTPException(status_code=429, detail=f"Trop d'essais. Compte verrouille temporairement : reessayez dans {minutes} min.", headers={"Retry-After": str(minutes * 60)})


def _verr(e: vf.VerificationError) -> HTTPException:
    headers = {"Retry-After": str(e.retry_after)} if e.retry_after else None
    detail = {"message": e.message, "code": e.code, **e.extra}
    return HTTPException(status_code=e.status, detail=detail, headers=headers)


def _started(res: vf.StartResult) -> AuthResult:
    return AuthResult(
        status="verification_required", request_id=res.request_id, channel=res.channel, destination_masked=res.masked,
        expires_in=res.expires_in, resend_in=res.resend_in, channels=res.channels,
    )


def _token_result(db: Session, request: Request, role: str, account_id: int, *, amr: list[str], trust_device: bool) -> AuthResult:
    ip, ua = sec.client_ip(request), sec.client_agent(request)
    sec.register_success(db, role, account_id, ip)
    sec.log_event(db, "login_ok", role=role, account_id=account_id, ip=ip, ua=ua, detail="+".join(amr))
    device = sec.issue_device(db, role, account_id, ip, ua) if (trust_device and role != "admin") else None
    return AuthResult(status="ok", access_token=create_access_token(subject=str(account_id), role=role, amr=amr), role=role, device_token=device)


def _default_channel(db: Session, phone: str | None, email: str | None, preferred: str | None) -> str:
    channels = vf.available_channels(db, phone, email)
    if preferred in channels:
        return preferred
    return channels[0] if channels else "email"


def _after_password(db: Session, request: Request, role: str, account_id: int, *, phone: str | None, email: str | None, channel: str | None, device_token: str | None, lang: str) -> AuthResult:
    """Mot de passe correct : on connecte, ou on exige d'abord un code selon la politique."""
    ip, ua = sec.client_ip(request), sec.client_agent(request)
    if not sec.requires_step_up(db, role, account_id, device_token):
        return _token_result(db, request, role, account_id, amr=["pwd", "device"], trust_device=False)
    chosen = _default_channel(db, phone, email, channel)
    try:
        res = vf.start(db, purpose="login", channel=chosen, phone=phone, email=email, role=role, account_id=account_id, ip=ip, ua=ua, lang=lang)
    except vf.VerificationError as e:
        raise _verr(e)
    return _started(res)


def _password_login(db: Session, request: Request, role: str, payload: PhoneLoginRequest) -> AuthResult:
    ip, ua = sec.client_ip(request), sec.client_agent(request)
    model = _ROLE_MODEL[role]
    phone = vf.normalize_e164(payload.phone)
    account = db.query(model).filter(model.phone.in_(phone_lookup_variants(payload.phone))).first() if phone else None
    if account is None:
        sec.burn_password_check(payload.password)  # meme duree de reponse qu'un vrai compte
        sec.log_event(db, "login_failed", role=role, success=False, ip=ip, ua=ua, detail="compte inconnu")
        raise HTTPException(status_code=401, detail="Telephone ou mot de passe incorrect")
    _raise_if_locked(db, role, account.id)
    if not verify_password(payload.password, account.hashed_password):
        left = sec.register_failure(db, role, account.id, ip, ua)
        raise HTTPException(status_code=401, detail=_failure_message("Telephone ou mot de passe incorrect", left))
    if role == "apprenant" and ad.cancel_if_pending(db, account.id):  # reconnexion pendant le delai : la suppression est annulee
        db.refresh(account)
        sec.log_event(db, "account_deletion_cancelled", role=role, account_id=account.id, ip=ip, ua=ua, detail="reconnexion")
    if not getattr(account, "is_active", True):
        sec.log_event(db, "login_failed", role=role, account_id=account.id, success=False, ip=ip, ua=ua, detail="compte desactive")
        raise HTTPException(status_code=403, detail="Ce compte est desactive. Contactez le support pour le reactiver.")
    email = getattr(account, "email", None)
    return _after_password(db, request, role, account.id, phone=phone, email=email, channel=payload.channel, device_token=payload.device_token, lang=payload.lang)


@router.post("/login/verify", response_model=AuthResult)
@limiter.limit("20/minute")
def login_verify(request: Request, payload: VerifyCodeRequest, db: Session = Depends(get_db)):
    """Seconde etape de la connexion : code recu par WhatsApp, SMS ou email."""
    ip, ua = sec.client_ip(request), sec.client_agent(request)
    try:
        row = vf.verify(db, payload.request_id, payload.code, purpose="login", ip=ip, ua=ua)
    except vf.VerificationError as e:
        raise _verr(e)
    role, account_id = row.role, row.account_id
    if role not in _ROLE_MODEL or account_id is None or db.get(_ROLE_MODEL[role], account_id) is None:
        raise HTTPException(status_code=400, detail={"message": "Code invalide ou expire.", "code": "invalid"})
    _raise_if_locked(db, role, account_id)
    sec.mark_verified(db, role, account_id, row.channel)
    vf.consume(db, row)
    if role == "admin":
        # Compte admin historique : le code email prouve la propriete de la boite, puis on impose la 2FA.
        from app.services.access import admin_auth as aa

        return AuthResult(status="mfa_setup_required", pre_token=aa.issue_pre(account_id, "mfa_setup"), role="admin")
    return _token_result(db, request, role, account_id, amr=["pwd", "otp", row.channel], trust_device=payload.trust_device)


@router.post("/verification/resend", response_model=AuthResult)
@limiter.limit("10/minute")
def verification_resend(request: Request, payload: ResendRequest, db: Session = Depends(get_db)):
    """Renvoie un code (eventuellement par un autre canal : "essayer d'une autre facon")."""
    try:
        res = vf.resend(db, payload.request_id, payload.channel, sec.client_ip(request), sec.client_agent(request))
    except vf.VerificationError as e:
        raise _verr(e)
    return _started(res)


# --------------------------------------------------------------------- inscription verifiee (3 ecrans)
_GENERIC_BOT = "Requete invalide. Rechargez la page et reessayez."
_MIN_FORM_MS = 1200  # un humain ne remplit pas ce formulaire en moins de ~1 s


def _clean_name(value: str) -> str:
    """Espaces normalises, caracteres de controle retires (jamais d'injection dans les journaux / emails)."""
    import re

    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", "", value or "")).strip()


def _validate_signup(db: Session, payload: SignupStart, request: Request) -> tuple[str, str | None, str, str]:
    """Controles communs aux etapes 1 (check) et 2 (start). Retourne (phone E.164, email, prenoms, nom).
    Aucun envoi, aucune ecriture."""
    ip, ua = sec.client_ip(request), sec.client_agent(request)
    # Anti-robots : champ piege rempli ou formulaire "rempli" en quelques millisecondes.
    if (payload.hp or "").strip() or (payload.elapsed_ms is not None and payload.elapsed_ms < _MIN_FORM_MS):
        sec.log_event(db, "signup_bot_blocked", role="apprenant" if payload.role != "client" else "client", success=False, ip=ip, ua=ua, detail="honeypot" if (payload.hp or "").strip() else "trop rapide")
        raise HTTPException(status_code=400, detail=_GENERIC_BOT)
    firstname, lastname = _clean_name(payload.firstname), _clean_name(payload.lastname)
    if not firstname:
        raise HTTPException(status_code=422, detail="Indiquez votre prenom.")
    email = (str(payload.email).strip().lower() if payload.email else None)
    if payload.role == "client" and not email:
        raise HTTPException(status_code=422, detail="L'email est obligatoire pour un compte client.")
    model = _ROLE_MODEL["apprenant" if payload.role == "prestataire" else payload.role]
    phone = vf.normalize_e164(payload.phone)
    if phone is None:
        raise HTTPException(status_code=422, detail="Numero de telephone invalide.")
    if email and db.query(model).filter(model.email == email).first():
        raise HTTPException(status_code=400, detail="Un compte existe deja avec cet email")
    if db.query(model).filter(model.phone.in_(phone_lookup_variants(phone))).first():
        raise HTTPException(status_code=400, detail="Un compte existe deja avec ce numero de telephone")
    try:
        sec.check_password_strength(payload.password, email=email, phone=phone, names=(firstname, lastname))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return phone, email, firstname, lastname


@router.post("/signup/check", response_model=SignupChecked)
@limiter.limit("20/hour")
def signup_check(request: Request, payload: SignupStart, db: Session = Depends(get_db)):
    """Ecran 1 -> 2 : valide les informations et indique les canaux disponibles pour recevoir le code.
    N'envoie RIEN et ne cree RIEN. Limite stricte par IP (evite l'enumeration de comptes en masse)."""
    phone, email, _, _ = _validate_signup(db, payload, request)
    channels = vf.available_channels(db, phone, email)
    if not channels:
        raise HTTPException(status_code=422, detail="Aucun canal disponible pour ce numero : ajoutez un email pour recevoir le code.")
    preferred = payload.channel if payload.channel in channels else channels[0]
    return SignupChecked(channels=channels, recommended=preferred, destinations={ch: mask_destination(ch, email if ch == "email" else phone) for ch in channels})


@router.post("/signup/start", response_model=AuthResult)
@limiter.limit("10/hour")
def signup_start(request: Request, payload: SignupStart, country: str = Depends(current_country), db: Session = Depends(get_db)):
    """Ecran 2 -> 3 : envoie le code par le canal CHOISI. AUCUN compte n'est cree tant que le code n'est pas
    saisi : pas de comptes fantomes dans la base partagee."""
    ip, ua = sec.client_ip(request), sec.client_agent(request)
    phone, email, firstname, lastname = _validate_signup(db, payload, request)
    channels = vf.available_channels(db, phone, email)
    if payload.channel not in channels:
        raise HTTPException(status_code=422, detail="Ce canal n'est pas disponible : choisissez-en un autre.")
    pending = {
        "role": payload.role, "firstname": firstname, "lastname": lastname,
        "password_hash": hash_password(payload.password),  # jamais le mot de passe en clair
        "country": country,
    }
    if payload.role == "prestataire":
        metier = (payload.metier or "").strip()
        if payload.subcategory_id:
            row = db.execute(text("SELECT subcat_name_fr FROM sub_categories WHERE subcat_id=:i AND subcat_is_active=1"), {"i": payload.subcategory_id}).first()
            if not row:
                raise HTTPException(status_code=422, detail="Metier inconnu.")
            metier = row[0]
        pending.update({"metier": metier or None, "subcategory_id": payload.subcategory_id, "city": (payload.city or "").strip() or None, "years_experience": payload.years_experience})
    try:
        res = vf.start(db, purpose="signup", channel=payload.channel, phone=phone, email=email, payload=pending, ip=ip, ua=ua, lang=payload.lang)
    except vf.VerificationError as e:
        raise _verr(e)
    return _started(res)


@router.post("/signup/verify", response_model=AuthResult, status_code=201)
@limiter.limit("20/minute")
def signup_verify(request: Request, payload: VerifyCodeRequest, db: Session = Depends(get_db)):
    """Ecran 3 : le code est correct -> le compte est cree (numero ou email marque comme verifie)."""
    ip, ua = sec.client_ip(request), sec.client_agent(request)
    try:
        row = vf.verify(db, payload.request_id, payload.code, purpose="signup", ip=ip, ua=ua)
    except vf.VerificationError as e:
        raise _verr(e)
    data = vf.payload_of(row)
    role = data.get("role")
    if role not in ("apprenant", "client", "prestataire"):
        raise HTTPException(status_code=400, detail={"message": "Code invalide ou expire.", "code": "invalid"})
    is_provider = role == "prestataire"
    if is_provider:
        role = "apprenant"  # meme espace de connexion (table vendors) ; seul le statut Academy change
    model = _ROLE_MODEL[role]
    country = data.get("country") or "TG"
    country_id = marketplace_country_id(db, country)
    phone, email = data.get("phone"), (data.get("email") or None)
    # Course possible entre l'etape 2 et 3 : on reverifie l'unicite (sans comparer un e-mail absent a NULL).
    clash = model.phone.in_(phone_lookup_variants(phone))
    if email:
        clash = (model.email == email) | clash
    if db.query(model).filter(clash).first():
        raise HTTPException(status_code=400, detail="Un compte existe deja avec cet email ou ce numero")
    full_name = f"{data.get('firstname', '')} {data.get('lastname', '')}".strip()
    if role == "apprenant":
        account = Apprenant(
            vendor_unique_id=generate_unique_id("VEN"), vendor_name=full_name, email=email or "", phone=normalize_phone_for_storage(phone),  # colonne NOT NULL : "" = pas d'email
            hashed_password=data["password_hash"], academy_status="provider" if is_provider else "apprentice", is_active_raw="1", created_at=datetime.utcnow(),
            country_id=country_id, country_code=country, address_city=(data.get("city") if is_provider else None),
        )
    else:
        account = Client(
            client_unique_id=generate_unique_id("CLI"), client_name=full_name, email=email, phone=normalize_phone_for_storage(phone),
            hashed_password=data["password_hash"], is_active_raw=1, country_id=country_id, country_code=country,
        )
    db.add(account)
    db.commit()
    db.refresh(account)
    if is_provider and (data.get("metier") or data.get("years_experience") is not None):
        from app.models.provider import ProviderProfile

        db.add(ProviderProfile(vendor_id=account.id, headline=(data.get("metier") or None), years_experience=data.get("years_experience")))
        db.commit()
    vf.consume(db, row)
    sec.mark_verified(db, role, account.id, row.channel)
    sec.mark_password_changed(db, role, account.id)
    sec.log_event(db, "signup", role=role, account_id=account.id, channel=row.channel, ip=ip, ua=ua, detail="prestataire" if is_provider else None)
    return _token_result(db, request, role, account.id, amr=["pwd", "otp", row.channel], trust_device=payload.trust_device)


# --------------------------------------------------------------------- mot de passe oublie (unifie)
def _find_account(db: Session, role: str, identifier: str):
    model = _ROLE_MODEL[role]
    ident = identifier.strip()
    if "@" in ident:
        return db.query(model).filter(model.email == ident).first()
    if role == "admin":
        return None
    phone = vf.normalize_e164(ident)
    return db.query(model).filter(model.phone.in_(phone_lookup_variants(phone or ident))).first()


@router.post("/forgot-password", response_model=AuthResult)
@limiter.limit("5/hour")
def forgot_password(request: Request, payload: ForgotRequest, db: Session = Depends(get_db)):
    """Reponse TOUJOURS de meme forme, que le compte existe ou non (aucune fuite sur les inscrits) :
    pour un compte inconnu on renvoie une demande factice qui n'enverra jamais rien."""
    import uuid

    ip, ua = sec.client_ip(request), sec.client_agent(request)
    ident = (payload.identifier or payload.email or "").strip()
    if not ident:
        raise HTTPException(status_code=422, detail="Indiquez votre email ou votre numero de telephone.")
    account = _find_account(db, payload.role, ident)
    if account is None:
        fake_channel = payload.channel
        return AuthResult(
            status="verification_required", request_id=str(uuid.uuid4()), channel=fake_channel,
            destination_masked=mask_destination(fake_channel, ident if fake_channel == "email" else (vf.normalize_e164(ident) or ident)),
            expires_in=settings.otp_ttl_minutes * 60, resend_in=settings.otp_resend_cooldown_seconds, channels=["whatsapp", "sms", "email"],
        )
    phone = vf.normalize_e164(getattr(account, "phone", None)) or (vf.normalize_e164(ident) if "@" not in ident else None)
    email = getattr(account, "email", None)
    channel = _default_channel(db, phone, email, payload.channel)
    try:
        res = vf.start(db, purpose="password_reset", channel=channel, phone=phone, email=email, role=payload.role, account_id=account.id, ip=ip, ua=ua, lang=payload.lang)
    except vf.VerificationError as e:
        raise _verr(e)
    return _started(res)


def _reset_token(row_id: int, role: str, account_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=15)
    return jwt.encode({"purpose": "password_reset", "vid": row_id, "role": role, "sub": str(account_id), "exp": exp}, settings.secret_key, algorithm=settings.jwt_algorithm)


@router.post("/verify-otp")
@limiter.limit("20/hour")
def verify_otp_endpoint(request: Request, payload: VerifyResetRequest, db: Session = Depends(get_db)):
    try:
        row = vf.verify(db, payload.request_id, payload.code, purpose="password_reset", ip=sec.client_ip(request), ua=sec.client_agent(request))
    except vf.VerificationError as e:
        raise _verr(e)
    if row.role not in _ROLE_MODEL or row.account_id is None:
        raise HTTPException(status_code=400, detail={"message": "Code invalide ou expire.", "code": "invalid"})
    return {"reset_token": _reset_token(row.id, row.role, row.account_id)}


@router.post("/reset-password")
@limiter.limit("10/hour")
def reset_password_endpoint(request: Request, payload: ResetWithTokenRequest, db: Session = Depends(get_db)):
    from app.models.security import Verification

    try:
        claims = jwt.decode(payload.reset_token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status_code=400, detail="Lien de reinitialisation invalide ou expire.")
    if claims.get("purpose") != "password_reset":
        raise HTTPException(status_code=400, detail="Lien de reinitialisation invalide ou expire.")
    row = db.get(Verification, claims.get("vid"))
    if row is None or row.verified_at is None or row.consumed_at is not None or row.purpose != "password_reset" or row.role != claims.get("role"):
        raise HTTPException(status_code=400, detail="Lien de reinitialisation invalide ou expire.")
    account = db.get(_ROLE_MODEL[row.role], row.account_id)
    if account is None:
        raise HTTPException(status_code=400, detail="Lien de reinitialisation invalide ou expire.")
    try:
        sec.check_password_strength(payload.new_password, email=getattr(account, "email", None), phone=getattr(account, "phone", None), names=(getattr(account, "firstname", "") or "",))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    account.hashed_password = hash_password(payload.new_password)
    db.commit()
    vf.consume(db, row)
    sec.mark_password_changed(db, row.role, row.account_id)
    sec.mark_verified(db, row.role, row.account_id, row.channel)
    sec.revoke_devices(db, row.role, row.account_id)  # tous les appareils devront se re-verifier
    sec.log_event(db, "password_reset", role=row.role, account_id=row.account_id, channel=row.channel, ip=sec.client_ip(request), ua=sec.client_agent(request))
    return {"detail": "Mot de passe reinitialise."}
