"""Articles de blog = evenements reels Trankyl (table partagee `events`,
voir app.models.blog). is_active permet de depublier un article sans le
supprimer — mais rappel : supprimer/depublier ici affecte la meme ligne que
le site principal Trankyl consulte."""
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.models.blog import BlogArticle
from app.schemas.blog import BlogArticleCreate, BlogArticleDetailOut, BlogArticleOut, BlogArticleUpdate
from app.services.image_upload import ImageUploadError, upload_image

router = APIRouter()


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


@router.post("/admin/upload-image", dependencies=[Depends(get_current_admin)])
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
def list_articles(db: Session = Depends(get_db)):
    """Liste publique : uniquement les evenements actifs, plus recents d'abord."""
    return (
        db.query(BlogArticle)
        .filter(BlogArticle.is_active.is_(True))
        .order_by(BlogArticle.created_at.desc())
        .all()
    )


@router.get("/articles/{article_id}", response_model=BlogArticleDetailOut)
def get_article(article_id: int, db: Session = Depends(get_db)):
    article = db.query(BlogArticle).filter(BlogArticle.id == article_id, BlogArticle.is_active.is_(True)).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article introuvable")
    return _to_detail(article)


@router.get("/admin/articles", response_model=list[BlogArticleOut], dependencies=[Depends(get_current_admin)])
def admin_list_articles(db: Session = Depends(get_db)):
    """Liste admin : tous les evenements, actifs ou non."""
    return db.query(BlogArticle).order_by(BlogArticle.created_at.desc()).all()


@router.get(
    "/admin/articles/{article_id}", response_model=BlogArticleDetailOut, dependencies=[Depends(get_current_admin)]
)
def admin_get_article(article_id: int, db: Session = Depends(get_db)):
    article = db.get(BlogArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article introuvable")
    return _to_detail(article)


@router.post("/articles", response_model=BlogArticleDetailOut, status_code=201, dependencies=[Depends(get_current_admin)])
def create_article(payload: BlogArticleCreate, db: Session = Depends(get_db)):
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
    db.commit()
    db.refresh(article)
    return _to_detail(article)


@router.put(
    "/articles/{article_id}", response_model=BlogArticleDetailOut, dependencies=[Depends(get_current_admin)]
)
def update_article(article_id: int, payload: BlogArticleUpdate, db: Session = Depends(get_db)):
    article = db.get(BlogArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article introuvable")

    article.title = payload.title
    article.excerpt = payload.excerpt
    article.category = payload.category
    article.cover_image_url = payload.cover_image_url
    article.event_start_date = payload.event_start_date
    article.event_end_date = payload.event_end_date
    article.content = "\n\n".join(payload.content)
    article.is_active = payload.is_active
    db.commit()
    db.refresh(article)
    return _to_detail(article)


@router.delete("/articles/{article_id}", status_code=204, dependencies=[Depends(get_current_admin)])
def delete_article(article_id: int, db: Session = Depends(get_db)):
    article = db.get(BlogArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article introuvable")
    db.delete(article)
    db.commit()
