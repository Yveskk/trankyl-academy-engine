from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# Pool dimensionne pour les requetes paralleles de GET /home (jusqu'a 8 a la
# fois) : sans cela, les connexions au-dela de la taille du pool sont refermees
# a chaque retour puis rouvertes (poignee de main reseau couteuse).
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=8,
    max_overflow=4,
    pool_recycle=1800,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
