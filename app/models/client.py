from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Client(Base):
    """Un foyer/particulier qui cherche un prestataire via l'assistant SITA
    (/matching/chat). Stocke dans la table `clients` de la base partagee
    du Trankyl Marketplace — c'est la meme table que celle utilisee par
    l'app Trankyl elle-meme (7000+ lignes existantes).

    Comme pour `Apprenant`/`vendors`, `clients` n'a qu'un champ
    `client_name` (nom complet) : `firstname`/`lastname` decoupent ce champ
    par propriete Python. Cette table n'a par ailleurs aucune colonne de
    date de creation (`created_at` n'existe pas cote Trankyl) : la
    propriete correspondante renvoie toujours None plutot que d'inventer
    une donnee qui n'existe pas."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column("client_id", BigInteger, primary_key=True)
    client_unique_id: Mapped[str] = mapped_column(String(25), nullable=False)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column("client_email", String(255), nullable=False)
    hashed_password: Mapped[str | None] = mapped_column("client_password", String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column("client_phone", String(50), nullable=True)
    is_active_raw: Mapped[int | None] = mapped_column("client_is_active", nullable=True)
    image: Mapped[str | None] = mapped_column("client_image", String(500), nullable=True)
    country_id: Mapped[int | None] = mapped_column("client_country_id", BigInteger, nullable=True)
    country_code: Mapped[str | None] = mapped_column("client_country_code", String(10), nullable=True)

    @property
    def firstname(self) -> str:
        return (self.client_name or "").split(" ", 1)[0]

    @property
    def lastname(self) -> str:
        parts = (self.client_name or "").split(" ", 1)
        return parts[1] if len(parts) > 1 else ""

    @property
    def is_active(self) -> bool:
        return bool(self.is_active_raw)

    @property
    def created_at(self) -> None:
        return None
