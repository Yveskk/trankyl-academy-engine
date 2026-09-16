"""Blocs de texte editorial du site (titre + sous-titre), geres depuis l'admin.
Chaque section a une cle stable (ex: "home_careers") et un interrupteur
is_active : desactivee, elle ne doit plus jamais etre servie au site public,
meme si elle existe toujours en base (juste masquee, pas supprimee)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.db.session import get_db
from app.models.content import ContentSection
from app.schemas.content import ContentSectionOut, ContentSectionUpsert

router = APIRouter()


@router.get("/sections/{key}", response_model=ContentSectionOut)
def get_public_section(key: str, db: Session = Depends(get_db)):
    """Lecture publique : 404 si la section n'existe pas OU si elle est
    desactivee, pour que le site n'ait qu'un seul cas a gerer ("pas la")."""
    section = db.query(ContentSection).filter(ContentSection.key == key, ContentSection.is_active.is_(True)).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section introuvable ou desactivee")
    return section


@router.get(
    "/admin/sections/{key}",
    response_model=ContentSectionOut,
    dependencies=[Depends(get_current_admin)],
)
def get_admin_section(key: str, db: Session = Depends(get_db)):
    """Lecture admin : renvoie la section meme si desactivee, pour pre-remplir
    le formulaire d'edition."""
    section = db.query(ContentSection).filter(ContentSection.key == key).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section introuvable")
    return section


@router.put(
    "/admin/sections/{key}",
    response_model=ContentSectionOut,
    dependencies=[Depends(get_current_admin)],
)
def upsert_section(key: str, payload: ContentSectionUpsert, db: Session = Depends(get_db)):
    """Cree ou met a jour la section (une seule par cle)."""
    section = db.query(ContentSection).filter(ContentSection.key == key).first()
    if section:
        section.title = payload.title
        section.subtitle = payload.subtitle
        section.is_active = payload.is_active
    else:
        section = ContentSection(key=key, title=payload.title, subtitle=payload.subtitle, is_active=payload.is_active)
        db.add(section)
    db.commit()
    db.refresh(section)
    return section
