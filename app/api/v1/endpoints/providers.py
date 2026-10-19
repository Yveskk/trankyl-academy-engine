"""Donnees de profil des prestataires que `vendors` ne porte pas (temps de
reponse, assurance, mise en avant, realisations, disponibilites). Ecriture
reservee aux admins ; la lecture publique de ces donnees est exposee par les
pages qui les affichent (accueil, recherche, profil)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_admin_ctx, require_access
from app.db.session import get_db
from app.models.provider import ProviderAvailability, ProviderMedia, ProviderProfile
from app.models.user import Apprenant
from app.schemas.provider import AvailabilitySlot, MediaIn, MediaOut, ProviderListItem, ProviderProfileIn, ProviderProfileOut
from app.api.v1.endpoints.directory import clear_directory_cache
from app.services.countries import provider_in_country as vendor_in_country, provider_offer_clause as vendor_country_clause
from app.services.home import invalidate_home_cache

router = APIRouter(dependencies=[Depends(require_access("providers"))])


def _vendor_or_404(db: Session, vendor_id: int, country: str) -> Apprenant:
    """Un prestataire n'est visible / modifiable que dans son pays (sinon : introuvable)."""
    vendor = db.get(Apprenant, vendor_id)
    if not vendor or not vendor_in_country(db, vendor_id, country):
        raise HTTPException(status_code=404, detail="Prestataire introuvable")
    return vendor


def _profile_out(vendor_id: int, p: ProviderProfile | None) -> ProviderProfileOut:
    if p is None:
        return ProviderProfileOut(vendor_id=vendor_id, persisted=False)
    return ProviderProfileOut(
        vendor_id=vendor_id, persisted=True, headline=p.headline, about=p.about, about_en=p.about_en, cover_image_url=p.cover_image_url,
        response_time_minutes=p.response_time_minutes, on_time_rate=float(p.on_time_rate) if p.on_time_rate is not None else None,
        is_insured=bool(p.is_insured), is_address_verified=bool(p.is_address_verified), top_override=p.top_override,
        is_featured=bool(p.is_featured), featured_order=p.featured_order, public_slug=p.public_slug,
        visit_fee=p.visit_fee, years_experience=p.years_experience, service_radius_km=p.service_radius_km,
        zone_label=p.zone_label, services_note=p.services_note, services_note_en=p.services_note_en,
    )


@router.get("/admin", response_model=list[ProviderListItem])
def admin_list_providers(q: str = "", only_certified: bool = True, limit: int = 50, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    clause, cparams = vendor_country_clause(db, admin.country, "v")
    rows = db.execute(
        text(
            "SELECT v.vendor_id, v.vendor_name, v.vendor_address_city, v.vendor_academy_verified, v.vendor_academy_status, "
            "COALESCE(p.is_featured,0), p.top_override, COALESCE(p.is_insured,0) "
            "FROM vendors v LEFT JOIN academy_provider_profiles p ON p.vendor_id=v.vendor_id "
            f"WHERE (:q='' OR v.vendor_name LIKE :like) AND (:certified=0 OR v.vendor_academy_status IS NOT NULL) AND {clause} "
            "ORDER BY v.vendor_name LIMIT :lim"
        ),
        {"q": q, "like": f"%{q}%", "certified": 1 if only_certified else 0, "lim": min(limit, 200), **cparams},
    ).fetchall()
    return [
        ProviderListItem(vendor_id=r[0], name=r[1], city=r[2], is_verified=bool(r[3]), academy_status=r[4], is_featured=bool(r[5]), top_override=r[6], is_insured=bool(r[7]))
        for r in rows
    ]


@router.get("/admin/{vendor_id}/profile", response_model=ProviderProfileOut)
def admin_get_profile(vendor_id: int, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _vendor_or_404(db, vendor_id, admin.country)
    return _profile_out(vendor_id, db.query(ProviderProfile).filter(ProviderProfile.vendor_id == vendor_id).first())


@router.put("/admin/{vendor_id}/profile", response_model=ProviderProfileOut)
def admin_put_profile(vendor_id: int, payload: ProviderProfileIn, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _vendor_or_404(db, vendor_id, admin.country)
    if payload.public_slug:
        clash = db.query(ProviderProfile).filter(ProviderProfile.public_slug == payload.public_slug, ProviderProfile.vendor_id != vendor_id).first()
        if clash:
            raise HTTPException(status_code=400, detail="Ce lien public est deja utilise par un autre prestataire")
    p = db.query(ProviderProfile).filter(ProviderProfile.vendor_id == vendor_id).first()
    if p is None:
        p = ProviderProfile(vendor_id=vendor_id)
        db.add(p)
    for field, value in payload.model_dump().items():
        setattr(p, field, value)
    db.commit()
    db.refresh(p)
    invalidate_home_cache()
    clear_directory_cache()
    return _profile_out(vendor_id, p)


@router.get("/admin/{vendor_id}/media", response_model=list[MediaOut])
def admin_list_media(vendor_id: int, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _vendor_or_404(db, vendor_id, admin.country)
    rows = db.query(ProviderMedia).filter(ProviderMedia.vendor_id == vendor_id).order_by(ProviderMedia.sort_order, ProviderMedia.id).all()
    return [MediaOut(id=m.id, vendor_id=m.vendor_id, kind=m.kind, url=m.url, thumb_url=m.thumb_url, caption=m.caption, sort_order=m.sort_order, is_active=bool(m.is_active)) for m in rows]


@router.post("/admin/{vendor_id}/media", response_model=MediaOut, status_code=201)
def admin_add_media(vendor_id: int, payload: MediaIn, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _vendor_or_404(db, vendor_id, admin.country)
    m = ProviderMedia(vendor_id=vendor_id, **payload.model_dump())
    db.add(m)
    db.commit()
    db.refresh(m)
    clear_directory_cache()
    return MediaOut(id=m.id, vendor_id=m.vendor_id, kind=m.kind, url=m.url, thumb_url=m.thumb_url, caption=m.caption, sort_order=m.sort_order, is_active=bool(m.is_active))


@router.delete("/admin/media/{media_id}", status_code=204)
def admin_delete_media(media_id: int, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    m = db.get(ProviderMedia, media_id)
    if not m or not vendor_in_country(db, m.vendor_id, admin.country):
        raise HTTPException(status_code=404, detail="Media introuvable")
    db.delete(m)
    db.commit()
    clear_directory_cache()


@router.get("/admin/{vendor_id}/availability", response_model=list[AvailabilitySlot])
def admin_get_availability(vendor_id: int, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _vendor_or_404(db, vendor_id, admin.country)
    rows = db.query(ProviderAvailability).filter(ProviderAvailability.vendor_id == vendor_id).order_by(ProviderAvailability.weekday, ProviderAvailability.start_time).all()
    return [AvailabilitySlot(weekday=a.weekday, start_time=a.start_time, end_time=a.end_time, is_active=bool(a.is_active)) for a in rows]


@router.put("/admin/{vendor_id}/availability", response_model=list[AvailabilitySlot])
def admin_put_availability(vendor_id: int, slots: list[AvailabilitySlot], admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    """Remplace toutes les plages du prestataire (semantique "PUT")."""
    _vendor_or_404(db, vendor_id, admin.country)
    for s in slots:
        if s.end_time <= s.start_time:
            raise HTTPException(status_code=400, detail="L'heure de fin doit etre apres l'heure de debut")
    db.query(ProviderAvailability).filter(ProviderAvailability.vendor_id == vendor_id).delete()
    for s in slots:
        db.add(ProviderAvailability(vendor_id=vendor_id, **s.model_dump()))
    db.commit()
    clear_directory_cache()
    return slots
