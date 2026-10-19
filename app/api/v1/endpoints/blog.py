"""Articles de blog = evenements reels Trankyl (table partagee `events`,
voir app.models.blog). is_active permet de depublier un article sans le
supprimer — mais rappel : supprimer/depublier ici affecte la meme ligne que
le site principal Trankyl consulte."""
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.api.deps import current_country, require_access
from app.db.session import get_db
from app.models.blog import BlogArticle
from app.models.user import EntityCountry
from app.services.countries import reference_country
from app.schemas.blog import BlogArticleCreate, BlogArticleDetailOut, BlogArticleOut, BlogArticleUpdate
from app.services.home import invalidate_home_cache
from app.services.image_upload import ImageUploadError, upload_image

router = APIRouter()


ENTITY = "blog"


def _in_country(db: Session, country: str):
    """Condition "cet article est dans ce pays". `events` est partage avec tout Trankyl : le pays est
    memorise a part (`academy_entity_countries`). Un article sans rattachement (publie par Trankyl,
    avant le multi-pays) appartient au pays de reference."""
    tagged_here = select(EntityCountry.entity_id).where(EntityCountry.entity_type == ENTITY, EntityCountry.country_code == country)
    cond = BlogArticle.id.in_(tagged_here)
    if country == reference_country(db):
        tagged_any = select(EntityCountry.entity_id).where(EntityCountry.entity_type == ENTITY)
        cond = or_(cond, BlogArticle.id.notin_(tagged_any))
    return cond


def _own_article(db: Session, article_id: int, country: str) -> BlogArticle:
    article = db.query(BlogArticle).filter(BlogArticle.id == article_id, _in_country(db, country)).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article introuvable")
    return article


def _to_detail(article: BlogArticle) -> BlogArticleDetailOut:
    content = article.content.split("\n\n") if article.content else []
    return BlogArticleDetailOut(
        id=article.id,
        title=article.title,
        excerpt=article.excerpt,
        category=article.category,
        cover_image_url=article.cover_image_url,
        event_start_date=article.event_start_date,
        event_end_date=article.event_end_date,
        is_active=article.is_active,
        published_at=article.published_at,
        updated_at=article.updated_at,
        content=content,
    )


@router.post("/admin/upload-image", dependencies=[Depends(require_access("blog"))])
@limiter.limit("20/minute")
async def upload_cover_image(request: Request, file: UploadFile = File(...)):
    """Upload une image de couverture d'article vers Cloudinary (meme compte
    que trankyl_backend_nodejs) et retourne son URL publique."""
    content = await file.read()
    try:
        url = upload_image(content, file.content_type or "")
    except ImageUploadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"url": url}


@router.get("/articles", response_model=list[BlogArticleOut])
def list_articles(country: str = Depends(current_country), db: Session = Depends(get_db)):
    """Liste publique : uniquement les evenements actifs du pays, plus recents d'abord."""
    return (
        db.query(BlogArticle)
        .filter(BlogArticle.is_active.is_(True), _in_country(db, country))
        .order_by(BlogArticle.created_at.desc())
        .all()
    )


@router.get("/articles/{article_id}", response_model=BlogArticleDetailOut)
def get_article(article_id: int, country: str = Depends(current_country), db: Session = Depends(get_db)):
    article = db.query(BlogArticle).filter(BlogArticle.id == article_id, BlogArticle.is_active.is_(True), _in_country(db, country)).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article introuvable")
    return _to_detail(article)


@router.get("/admin/articles", response_model=list[BlogArticleOut])
def admin_list_articles(admin=Depends(require_access("blog")), db: Session = Depends(get_db)):
    """Liste admin : tous les evenements du pays, actifs ou non."""
    return db.query(BlogArticle).filter(_in_country(db, admin.country)).order_by(BlogArticle.created_at.desc()).all()


@router.get("/admin/articles/{article_id}", response_model=BlogArticleDetailOut)
def admin_get_article(article_id: int, admin=Depends(require_access("blog")), db: Session = Depends(get_db)):
    return _to_detail(_own_article(db, article_id, admin.country))


@router.post("/articles", response_model=BlogArticleDetailOut, status_code=201)
def create_article(payload: BlogArticleCreate, admin=Depends(require_access("blog")), db: Session = Depends(get_db)):
    article = BlogArticle(
        title=payload.title,
        excerpt=payload.excerpt,
        category=payload.category,
        cover_image_url=payload.cover_image_url,
        event_start_date=payload.event_start_date,
        event_end_date=payload.event_end_date,
        content="\n\n".join(payload.content),
        is_active=True,
    )
    db.add(article)
    db.flush()
    db.add(EntityCountry(entity_type=ENTITY, entity_id=article.id, country_code=admin.country))  # rattache au pays courant
    db.commit()
    invalidate_home_cache()
    db.refresh(article)
    return _to_detail(article)


@router.put("/articles/{article_id}", response_model=BlogArticleDetailOut)
def update_article(article_id: int, payload: BlogArticleUpdate, admin=Depends(require_access("blog")), db: Session = Depends(get_db)):
    article = _own_article(db, article_id, admin.country)

    article.title = payload.title
    article.excerpt = payload.excerpt
    article.category = payload.category
    article.cover_image_url = payload.cover_image_url
    article.event_start_date = payload.event_start_date
    article.event_end_date = payload.event_end_date
    article.content = "\n\n".join(payload.content)
    article.is_active = payload.is_active
    db.commit()
    invalidate_home_cache()
    db.refresh(article)
    return _to_detail(article)


@router.delete("/articles/{article_id}", status_code=204)
def delete_article(article_id: int, admin=Depends(require_access("blog")), db: Session = Depends(get_db)):
    article = _own_article(db, article_id, admin.country)
    db.query(EntityCountry).filter(EntityCountry.entity_type == ENTITY, EntityCountry.entity_id == article.id).delete()
    db.delete(article)
    db.commit()
    invalidate_home_cache()
