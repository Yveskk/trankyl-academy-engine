from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    secret_key: str
    access_token_expire_minutes: int = 60 * 24 * 7
    jwt_algorithm: str = "HS256"
    cors_origins: str = "http://localhost:5173"
    # Base des chemins relatifs d'images du catalogue Trankyl
    # (ex. "uploads/subcategory/xxx.jpeg" -> "<base>uploads/subcategory/xxx.jpeg").
    media_base_url: str = "https://trankyl.com/"
    # Duree de vie (secondes) du cache en memoire de GET /home.
    home_cache_ttl_seconds: int = 60
    # Decalage horaire local par rapport a UTC (Togo/Cote d'Ivoire = 0, Benin = 1) :
    # sert a calculer "aujourd'hui", "demain" et les creneaux de disponibilite.
    local_utc_offset_hours: int = 0
    # URL publique du site (liens de partage de profil).
    public_site_url: str = "https://trankyl.com"

    # --- Verification par code (WhatsApp / SMS / email) -----------------------
    # "log" : le code est ecrit dans la console du serveur, RIEN n'est envoye (defaut,
    # donc aucun message reel ni cout tant qu'on ne passe pas explicitement en "live").
    otp_delivery_mode: str = "log"
    whatsapp_token: str | None = None
    whatsapp_phone_id: str | None = None
    whatsapp_otp_template: str = "otp_verification"
    # Indicatifs autorises pour WhatsApp/SMS (anti "SMS pumping" : un robot ne doit pas
    # pouvoir vider le budget en envoyant des codes vers des pays lointains). L'email n'est pas limite.
    otp_allowed_dial_codes: str = "228,229,225,223,237"
    otp_code_length: int = 6
    otp_ttl_minutes: int = 10
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    otp_max_sends_per_hour_destination: int = 5
    otp_max_sends_per_day_destination: int = 10
    otp_max_sends_per_hour_ip: int = 20
    # off (defaut) : pas de code a la connexion ; new_device : code sur tout appareil non reconnu ; always
    login_verification_policy: str = "off"
    require_signup_verification: bool = True
    # A activer uniquement derriere un reverse proxy de confiance (nginx, load balancer) : l'IP
    # du visiteur est alors lue dans X-Forwarded-For. Sinon un client pourrait la falsifier.
    trust_proxy_headers: bool = False
    trusted_device_days: int = 30
    # Reservations : si renseigne, la reservation est enregistree PAR le backend Trankyl (POST /booking/book : notifications
    # admin / client et paiement en ligne inclus) ; sinon elle est ecrite directement dans la table partagee `bookings`.
    node_api_url: str | None = None
    # Paiement en ligne SEMOA (memes variables que le backend Node : API de production). Sans identifiants, "En ligne" est indisponible.
    semoa_api_key_prod: str | None = None
    semoa_login_prod: str | None = None
    semoa_api_reference_prod: str | None = None
    semoa_callback_url: str | None = None
    semoa_endpoint: str = "https://api.semoa-payments.ovh/prod"
    # Alertes "nouvelle reservation" (meme variable que le backend Node) : une ou plusieurs adresses separees par des virgules.
    admin_email: str | None = None
    booking_max_days_ahead: int = 120
    # Panneau admin : session courte (8 h) et URL de connexion citee dans les invitations.
    # Autorise les comptes marques "sans 2FA" a se connecter par mot de passe seul. A laisser FAUX en production.
    allow_mfa_exempt: bool = False
    admin_session_minutes: int = 60 * 8
    admin_panel_url: str = "http://localhost:5173/admin/login"
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    @property
    def admin_email_list(self) -> list[str]:
        return [e.strip() for e in (self.admin_email or "").split(",") if "@" in e]

    @property
    def otp_allowed_dial_code_list(self) -> list[str]:
        return [c.strip().lstrip("+") for c in self.otp_allowed_dial_codes.split(",") if c.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
