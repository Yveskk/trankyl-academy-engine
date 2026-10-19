"""Blocs de texte editorial du site (titre + sous-titre), geres depuis l'admin.
Chaque section a une cle stable (ex: "home_careers") et un interrupteur
is_active : desactivee, elle ne doit plus jamais etre servie au site public,
meme si elle existe toujours en base (juste masquee, pas supprimee)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import current_country, require_access
from app.db.session import get_db
from app.models.content import ContentSection
from app.services.home import invalidate_home_cache
from app.schemas.content import ContentSectionOut, ContentSectionUpsert

router = APIRouter()


@router.get("/sections/{key}", response_model=ContentSectionOut)
def get_public_section(key: str, country: str = Depends(current_country), db: Session = Depends(get_db)):
    """Lecture publique : 404 si la section n'existe pas OU si elle est
    desactivee, pour que le site n'ait qu'un seul cas a gerer ("pas la").
    Le contenu du pays demande, a defaut celui du pays de reference (TG)."""
    section = None
    for code in (country, "TG"):
        section = db.query(ContentSection).filter(ContentSection.key == key, ContentSection.country_code == code, ContentSection.is_active.is_(True)).first()
        if section:
            break
    if not section:
        raise HTTPException(status_code=404, detail="Section introuvable ou desactivee")
    return section


@router.get(
    "/admin/sections/{key}",
    response_model=ContentSectionOut,
)
def get_admin_section(key: str, admin=Depends(require_access("content")), db: Session = Depends(get_db)):
    """Lecture admin : renvoie la section (du pays courant) meme si desactivee, pour pre-remplir
    le formulaire d'edition."""
    section = db.query(ContentSection).filter(ContentSection.key == key, ContentSection.country_code == admin.country).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section introuvable")
    return section


@router.put(
    "/admin/sections/{key}",
    response_model=ContentSectionOut,
)
def upsert_section(key: str, payload: ContentSectionUpsert, admin=Depends(require_access("content")), db: Session = Depends(get_db)):
    """Cree ou met a jour la section (une seule par cle et par pays)."""
    section = db.query(ContentSection).filter(ContentSection.key == key, ContentSection.country_code == admin.country).first()
    if section:
        section.title = payload.title
        section.subtitle = payload.subtitle
        section.title_en = payload.title_en
        section.subtitle_en = payload.subtitle_en
        section.is_active = payload.is_active
    else:
        section = ContentSection(
            key=key,
            country_code=admin.country,
            title=payload.title,
            subtitle=payload.subtitle,
            title_en=payload.title_en,
            subtitle_en=payload.subtitle_en,
            is_active=payload.is_active,
        )
        db.add(section)
    db.commit()
    db.refresh(section)
    invalidate_home_cache()
    return section
