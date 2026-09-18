"""SITA — assistant IA d'orientation formation, public (voir
app.services.orientation_ai). Aucune authentification requise : un
visiteur pas encore inscrit doit pouvoir discuter avant de creer un
compte."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.db.session import get_db
from app.services.orientation_ai import chat_orientation

router = APIRouter()


class OrientationChatRequest(BaseModel):
    message: str
    history: list[dict] | None = None


@router.post("/chat")
@limiter.limit("20/minute")
def chat(request: Request, payload: OrientationChatRequest, db: Session = Depends(get_db)):
    try:
        response = chat_orientation(payload.message, db, payload.history)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur SITA: {str(e)}")
