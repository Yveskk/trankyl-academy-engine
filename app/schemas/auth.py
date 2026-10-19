from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

Role = Literal["apprenant", "client", "admin"]


class ApprenantRegister(BaseModel):
    firstname: str
    lastname: str
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    phone: str


class ApprenantOut(BaseModel):
    id: int
    firstname: str
    lastname: str
    email: str | None = None  # absent ('' en base) pour un compte cree avec le telephone seul
    phone: str | None
    created_at: datetime | None
    academy_status: str | None = None  # apprentice | provider | certified_provider : oriente vers le bon espace

    @field_validator("email", mode="before")
    @classmethod
    def _blank_email(cls, v):
        return v or None

    class Config:
        from_attributes = True


class ClientRegister(BaseModel):
    firstname: str
    lastname: str
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    phone: str


class ClientOut(BaseModel):
    id: int
    firstname: str
    lastname: str
    email: EmailStr
    phone: str | None
    image: str | None = None
    created_at: datetime | None

    @field_validator("image")
    @classmethod
    def _only_urls(cls, v):
        # Anciennes valeurs relatives ("uploads/x.jpg") : pas d'URL exploitable -> pas de photo.
        return v if v and v.startswith("https://") else None

    class Config:
        from_attributes = True


class AdminLogin(BaseModel):
    email: EmailStr
    password: str


class AdminOut(BaseModel):
    id: int
    firstname: str
    lastname: str | None
    email: EmailStr

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    """Reserve a la connexion admin (email + mot de passe)."""

    email: EmailStr
    password: str
    lang: Literal["fr", "en"] = "fr"


class PhoneLoginRequest(BaseModel):
    """Connexion apprenant/client : telephone + mot de passe (+ jeton d'appareil de confiance)."""

    phone: str
    password: str
    device_token: str | None = Field(default=None, max_length=200)
    channel: Literal["whatsapp", "sms", "email"] | None = None
    lang: Literal["fr", "en"] = "fr"


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


# --------------------------------------------------------------------------- verification par code
Channel = Literal["whatsapp", "sms", "email"]


class SignupStart(BaseModel):
    """Inscription en 3 etapes : (1) /signup/check valide les informations, (2) /signup/start envoie le code par le
    canal choisi, (3) /signup/verify cree le compte. Meme corps pour les deux premieres.

    - apprenant / prestataire : prenoms, telephone, mot de passe ; e-mail FACULTATIF ;
    - client : e-mail OBLIGATOIRE ;
    - "prestataire" : professionnel qui exerce deja, certificat NON requis."""

    role: Literal["apprenant", "client", "prestataire"]
    firstname: str = Field(min_length=1, max_length=100)
    lastname: str = Field(default="", max_length=100)
    email: EmailStr | None = None
    password: str = Field(min_length=8, max_length=72)
    phone: str = Field(min_length=6, max_length=32)
    channel: Channel = "whatsapp"
    lang: Literal["fr", "en"] = "fr"
    # Anti-robots : champ piege (doit rester vide) et duree passee sur le formulaire.
    hp: str | None = Field(default=None, max_length=200)
    elapsed_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    # Facultatifs pour un prestataire (a completer plus tard depuis son profil)
    subcategory_id: int | None = None
    metier: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    years_experience: int | None = Field(default=None, ge=0, le=60)


class SignupChecked(BaseModel):
    """Informations valides : voici comment recevoir le code (rien n'a encore ete envoye)."""

    ok: bool = True
    channels: list[Channel]
    recommended: Channel
    destinations: dict[str, str]  # canal -> destination masquee


class VerificationStarted(BaseModel):
    """Un code vient d'etre envoye : `request_id` identifie la demande (a renvoyer avec le code)."""

    status: Literal["verification_required"] = "verification_required"
    request_id: str
    channel: Channel
    destination_masked: str
    expires_in: int
    resend_in: int
    channels: list[Channel]


class VerifyCodeRequest(BaseModel):
    request_id: str = Field(min_length=36, max_length=36)
    code: str = Field(min_length=4, max_length=10)
    trust_device: bool = False


class ResendRequest(BaseModel):
    request_id: str = Field(min_length=36, max_length=36)
    channel: Channel | None = None


class AuthResult(BaseModel):
    """Reponse d'une connexion / inscription : soit un jeton, soit un code a saisir."""

    status: Literal["ok", "verification_required", "change_password_required", "mfa_setup_required", "mfa_required"] = "ok"
    access_token: str | None = None
    token_type: str = "bearer"
    role: str | None = None
    device_token: str | None = None
    # present quand status == "verification_required"
    request_id: str | None = None
    channel: Channel | None = None
    destination_masked: str | None = None
    expires_in: int | None = None
    resend_in: int | None = None
    channels: list[Channel] = []
    # connexion admin : jeton d'etape (change_password_required / mfa_setup_required / mfa_required)
    pre_token: str | None = None
    recovery_codes: list[str] | None = None  # montres UNE seule fois, a l'activation de la 2FA
    recovery_left: int | None = None


class ForgotRequest(BaseModel):
    """Email ou telephone du compte (le role evite toute ambiguite)."""

    identifier: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)  # ancien champ, accepte pour compatibilite
    role: Role
    channel: Channel = "email"
    lang: Literal["fr", "en"] = "fr"


class VerifyResetRequest(BaseModel):
    request_id: str = Field(min_length=36, max_length=36)
    code: str = Field(min_length=4, max_length=10)


class ResetWithTokenRequest(BaseModel):
    reset_token: str = Field(min_length=20, max_length=2000)
    new_password: str = Field(min_length=8, max_length=72)


# ----------------------------------------------------------------------------- admin : 2FA / compte
class AdminRoleOut(BaseModel):
    id: int
    name: str


class AdminCountryOut(BaseModel):
    code: str
    name: str
    name_en: str | None = None


class AdminMe(BaseModel):
    id: int
    firstname: str
    lastname: str | None
    email: EmailStr
    role: AdminRoleOut | None = None
    is_super: bool = False
    permissions: list[str] = []
    mfa_enabled: bool = False
    recovery_left: int = 0
    # Pays auxquels l'administrateur a acces (le selecteur de pays du panneau n'affiche que ceux-la).
    all_countries: bool = False
    countries: list[AdminCountryOut] = []
    default_country: str | None = None


class PreChangePassword(BaseModel):
    pre_token: str
    new_password: str = Field(min_length=8, max_length=72)


class PreOnly(BaseModel):
    pre_token: str


class MfaEnable(BaseModel):
    pre_token: str
    code: str = Field(min_length=6, max_length=8)


class MfaVerify(BaseModel):
    pre_token: str
    code: str | None = Field(default=None, max_length=12)
    recovery_code: str | None = Field(default=None, max_length=24)


class MeChangePassword(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=72)
    code: str = Field(min_length=6, max_length=8)


class MeCode(BaseModel):
    code: str = Field(min_length=6, max_length=8)
