"""Images de la banniere d'accueil, gerees depuis l'admin. Maximum 3 en
base (une par slot `ordre` 1/2/3) : le frontend garde ses images par defaut
pour tout slot sans banniere active, donc rien ne casse si l'admin n'a pas
encore uploade de visuel."""
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.models.banner import Banner
from app.schemas.banner import BannerCreate, BannerOut, BannerUpdate
from app.services.image_upload import ImageUploadError, upload_image

router = APIRouter()

MAX_BANNERS = 3


@router.get("", response_model=list[BannerOut])
def list_banners(db: Session = Depends(get_db)):
    """Lecture publique : uniquement les bannieres actives."""
    return db.query(Banner).filter(Banner.is_active.is_(True)).order_by(Banner.ordre).all()


@router.get("/admin", response_model=list[BannerOut], dependencies=[Depends(get_current_admin)])
def admin_list_banners(db: Session = Depends(get_db)):
    return db.query(Banner).order_by(Banner.ordre).all()


@router.post("/admin/upload-image", dependencies=[Depends(get_current_admin)])
@limiter.limit("20/minute")
async def upload_banner_image(request: Request, file: UploadFile = File(...)):
    content = await file.read()
    try:
        url = upload_image(content, file.content_type or "")
    except ImageUploadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"url": url}


@router.post("", response_model=BannerOut, status_code=201, dependencies=[Depends(get_current_admin)])
def create_banner(payload: BannerCreate, db: Session = Depends(get_db)):
    total = db.query(Banner).count()
    if total >= MAX_BANNERS:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_BANNERS} bannieres — supprimez-en une avant d'en ajouter.")
    existing = db.query(Banner).filter(Banner.ordre == payload.ordre).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Une banniere existe deja pour l'emplacement {payload.ordre}")

    banner = Banner(ordre=payload.ordre, image_url=payload.image_url)
    db.add(banner)
    db.commit()
    db.refresh(banner)
    return banner


@router.put("/{banner_id}", response_model=BannerOut, dependencies=[Depends(get_current_admin)])
def update_banner(banner_id: int, payload: BannerUpdate, db: Session = Depends(get_db)):
    banner = db.get(Banner, banner_id)
    if not banner:
        raise HTTPException(status_code=404, detail="Banniere introuvable")
    existing = db.query(Banner).filter(Banner.ordre == payload.ordre, Banner.id != banner_id).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Une autre banniere utilise deja l'emplacement {payload.ordre}")

    banner.ordre = payload.ordre
    banner.image_url = payload.image_url
    banner.is_active = payload.is_active
    db.commit()
    db.refresh(banner)
    return banner


@router.delete("/{banner_id}", status_code=204, dependencies=[Depends(get_current_admin)])
def delete_banner(banner_id: int, db: Session = Depends(get_db)):
    banner = db.get(Banner, banner_id)
    if not banner:
        raise HTTPException(status_code=404, detail="Banniere introuvable")
    db.delete(banner)
    db.commit()
