"""Connexion et compte du panneau admin : mot de passe + double authentification (TOTP)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core import country as ctry
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import hash_password, verify_password
from app.db.session import get_db
from app.models.user import AdminUser
from app.schemas.auth import AdminCountryOut, AdminMe, AdminRoleOut, AuthResult, LoginRequest, MeChangePassword, MeCode, MfaEnable, MfaVerify, PreChangePassword, PreOnly
from app.services.countries import active_countries
from app.services.access import admin_auth as aa
from app.services.access import context as ctx
from app.services.security import accounts as sec
from app.services.security import totp
from app.services.security import verification as vf

router = APIRouter()


def _flow(e: aa.AuthFlowError) -> HTTPException:
    return HTTPException(status_code=e.status, detail={"message": e.message, "code": e.code} if e.code else e.message)


def _locked(db: Session, admin_id: int) -> None:
    minutes = sec.lock_remaining_minutes(sec.get_security(db, "admin", admin_id))
    if minutes:
        raise HTTPException(status_code=429, detail=f"Trop d'essais. Compte verrouillé temporairement : réessayez dans {minutes} min.", headers={"Retry-After": str(minutes * 60)})


def _admin_for_stage(db: Session, token: str, *stages: str) -> AdminUser:
    try:
        uid = aa.read_pre(token, *stages)
    except aa.AuthFlowError as e:
        raise _flow(e)
    admin = db.get(AdminUser, uid)
    if admin is None or not ctx.load_access(db, admin).can_enter:
        raise HTTPException(status_code=401, detail="Session de connexion invalide. Reconnectez-vous.")
    _locked(db, admin.id)
    return admin


def _stage_result(db: Session, admin: AdminUser) -> AuthResult:
    stage = aa.next_stage(admin, ctx.get_profile(db, admin.id))
    status = {"change_password": "change_password_required", "mfa_setup": "mfa_setup_required", "mfa_verify": "mfa_required"}[stage]
    return AuthResult(status=status, pre_token=aa.issue_pre(admin.id, stage), role="admin")


def _failure_message(left: int) -> str:
    base = "Email ou mot de passe incorrect"
    if left == 0:
        return f"{base}. Compte verrouillé temporairement, réessayez plus tard."
    return f"{base} ({left} essai{'s' if left > 1 else ''} restant{'s' if left > 1 else ''})" if left <= 2 else base


@router.post("/login", response_model=AuthResult)
@limiter.limit("10/minute")
def admin_login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    ip, ua = sec.client_ip(request), sec.client_agent(request)
    admin = db.query(AdminUser).filter(AdminUser.email == payload.email).first()
    if admin is None:
        sec.burn_password_check(payload.password)
        sec.log_event(db, "login_failed", role="admin", success=False, ip=ip, ua=ua, detail="compte inconnu")
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    _locked(db, admin.id)
    if not verify_password(payload.password, admin.hashed_password):
        raise HTTPException(status_code=401, detail=_failure_message(sec.register_failure(db, "admin", admin.id, ip, ua)))
    access = ctx.load_access(db, admin)
    if not access.can_enter:
        sec.log_event(db, "login_refused", role="admin", account_id=admin.id, success=False, ip=ip, ua=ua, detail=access.status)
        raise HTTPException(status_code=403, detail="Ce compte est suspendu ou n'a accès à aucune partie de l'administration. Contactez un administrateur.")
    profile = ctx.get_profile(db, admin.id)
    if settings.allow_mfa_exempt and profile is not None and profile.mfa_exempt and access.is_super:
        # Compte de test dispense de 2FA (uniquement si le serveur l'autorise) : mot de passe seul, journalise.
        token = aa.issue_session(db, admin, ["pwd"], ip)
        sec.log_event(db, "login_ok", role="admin", account_id=admin.id, ip=ip, ua=ua, detail="pwd (2FA dispensee)")
        return AuthResult(status="ok", access_token=token, role="admin")
    stage = aa.next_stage(admin, profile)
    legacy = profile is None or profile.created_by is None  # jamais invite par un admin : on verifie d'abord la boite email
    if stage == "mfa_setup" and legacy:
        try:
            res = vf.start(db, purpose="login", channel="email", phone=None, email=admin.email, role="admin", account_id=admin.id, ip=ip, ua=ua, lang=payload.lang)
        except vf.VerificationError as e:
            raise HTTPException(status_code=e.status, detail={"message": e.message, "code": e.code, **e.extra})
        return AuthResult(status="verification_required", request_id=res.request_id, channel=res.channel, destination_masked=res.masked, expires_in=res.expires_in, resend_in=res.resend_in, channels=res.channels)
    return _stage_result(db, admin)


@router.post("/password/change", response_model=AuthResult)
@limiter.limit("10/minute")
def change_temporary_password(request: Request, payload: PreChangePassword, db: Session = Depends(get_db)):
    """Premiere connexion : remplace le mot de passe temporaire par un mot de passe personnel."""
    admin = _admin_for_stage(db, payload.pre_token, "change_password")
    if verify_password(payload.new_password, admin.hashed_password):
        raise HTTPException(status_code=422, detail="Choisissez un mot de passe différent du mot de passe temporaire.")
    try:
        sec.check_password_strength(payload.new_password, email=admin.email, names=(admin.firstname or "", admin.lastname or ""))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    admin.hashed_password = hash_password(payload.new_password)
    profile = ctx.get_profile(db, admin.id, create=True)
    profile.must_change_password = False
    db.commit()
    sec.mark_password_changed(db, "admin", admin.id)
    sec.log_event(db, "password_changed", role="admin", account_id=admin.id, ip=sec.client_ip(request), ua=sec.client_agent(request), detail="premiere connexion")
    return _stage_result(db, admin)


@router.post("/mfa/setup")
@limiter.limit("10/minute")
def mfa_setup(request: Request, payload: PreOnly, db: Session = Depends(get_db)):
    """Genere le secret TOTP (QR code / cle de saisie). Rien n'est actif tant qu'un code n'est pas confirme."""
    admin = _admin_for_stage(db, payload.pre_token, "mfa_setup")
    try:
        return aa.begin_enrolment(db, admin)
    except aa.AuthFlowError as e:
        raise _flow(e)


@router.post("/mfa/enable", response_model=AuthResult)
@limiter.limit("10/minute")
def mfa_enable(request: Request, payload: MfaEnable, db: Session = Depends(get_db)):
    admin = _admin_for_stage(db, payload.pre_token, "mfa_setup")
    ip, ua = sec.client_ip(request), sec.client_agent(request)
    try:
        codes = aa.confirm_enrolment(db, admin, payload.code, ip, ua)
    except aa.AuthFlowError as e:
        raise _flow(e)
    token = aa.issue_session(db, admin, ["pwd", "totp"], ip)
    sec.log_event(db, "login_ok", role="admin", account_id=admin.id, ip=ip, ua=ua, detail="pwd+totp (activation)")
    return AuthResult(status="ok", access_token=token, role="admin", recovery_codes=codes, recovery_left=len(codes))


@router.post("/mfa/verify", response_model=AuthResult)
@limiter.limit("10/minute")
def mfa_verify(request: Request, payload: MfaVerify, db: Session = Depends(get_db)):
    admin = _admin_for_stage(db, payload.pre_token, "mfa_verify")
    ip, ua = sec.client_ip(request), sec.client_agent(request)
    if not payload.code and not payload.recovery_code:
        raise HTTPException(status_code=422, detail="Saisissez le code de votre application d'authentification.")
    try:
        amr, left = aa.verify_second_factor(db, admin, code=payload.code, recovery_code=payload.recovery_code, ip=ip, ua=ua)
    except aa.AuthFlowError as e:
        raise _flow(e)
    token = aa.issue_session(db, admin, amr, ip)
    sec.log_event(db, "login_ok", role="admin", account_id=admin.id, ip=ip, ua=ua, detail="+".join(amr))
    return AuthResult(status="ok", access_token=token, role="admin", recovery_left=left)


# --------------------------------------------------------------------------- compte connecte
def _me(admin: AdminUser, db: Session) -> AdminMe:
    a = admin.access  # type: ignore[attr-defined]
    rows = active_countries(db)
    mine = [c for c in rows if a.in_country(c["code"])]
    if not rows:  # aucun pays configure : repli sur les codes connus (comportement historique)
        names = {"TG": ("Togo", "Togo"), "CI": ("Côte d'Ivoire", "Côte d'Ivoire"), "BJ": ("Bénin", "Benin"), "ML": ("Mali", "Mali"), "CM": ("Cameroun", "Cameroon")}
        mine = [{"code": c, "name": names.get(c, (c, c))[0], "name_en": names.get(c, (c, c))[1]} for c in ctry.known_codes(db) if a.in_country(c)]
    default = ctry.default_country(db)
    return AdminMe(
        all_countries=a.all_countries, countries=[AdminCountryOut(code=c["code"], name=c["name"], name_en=c.get("name_en")) for c in mine],
        default_country=default if a.in_country(default) else (mine[0]["code"] if mine else None),
        id=admin.id, firstname=admin.firstname, lastname=admin.lastname, email=admin.email,
        role=AdminRoleOut(id=a.role_id, name=a.role_name or "") if a.role_id else None,
        is_super=a.is_super, permissions=sorted(a.keys), mfa_enabled=bool(admin.totp_enabled), recovery_left=totp.recovery_left(admin.totp_recovery_codes),
    )


@router.get("/me", response_model=AdminMe)
def admin_me(admin: AdminUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _me(admin, db)


@router.post("/me/password")
@limiter.limit("5/minute")
def change_my_password(request: Request, payload: MeChangePassword, admin: AdminUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Changement de mot de passe : ancien mot de passe + code 2FA (re-authentification)."""
    ip, ua = sec.client_ip(request), sec.client_agent(request)
    _locked(db, admin.id)
    if not verify_password(payload.current_password, admin.hashed_password):
        sec.register_failure(db, "admin", admin.id, ip, ua)
        raise HTTPException(status_code=401, detail="Mot de passe actuel incorrect.")
    try:
        aa.require_totp(db, admin, payload.code, ip, ua)
    except aa.AuthFlowError as e:
        raise _flow(e)
    if verify_password(payload.new_password, admin.hashed_password):
        raise HTTPException(status_code=422, detail="Le nouveau mot de passe doit être différent de l'actuel.")
    try:
        sec.check_password_strength(payload.new_password, email=admin.email, names=(admin.firstname or "", admin.lastname or ""))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    admin.hashed_password = hash_password(payload.new_password)
    db.commit()
    sec.mark_password_changed(db, "admin", admin.id)
    sec.log_event(db, "password_changed", role="admin", account_id=admin.id, ip=ip, ua=ua)
    token = aa.issue_session(db, admin, ["pwd", "totp"], ip)  # nouvelle session ; les anciennes sont fermees
    return {"detail": "Mot de passe modifié. Vos autres sessions ont été déconnectées.", "access_token": token}


@router.post("/me/recovery-codes")
@limiter.limit("5/minute")
def regenerate_recovery_codes(request: Request, payload: MeCode, admin: AdminUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    ip, ua = sec.client_ip(request), sec.client_agent(request)
    _locked(db, admin.id)
    try:
        aa.require_totp(db, admin, payload.code, ip, ua)
    except aa.AuthFlowError as e:
        raise _flow(e)
    codes, stored = totp.new_recovery_codes()
    admin.totp_recovery_codes = stored
    db.commit()
    sec.log_event(db, "mfa_recovery_regenerated", role="admin", account_id=admin.id, ip=ip, ua=ua)
    return {"recovery_codes": codes}
