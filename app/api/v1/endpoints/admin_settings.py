"""Reglages simples de l'administration (tarifs d'abonnement des prestataires).

Stockes comme le backend Trankyl : une ligne JSON de `meta_data` contenant la cle « subscription » -> les deux applications lisent la meme valeur."""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import require_access
from app.db.session import get_db

router = APIRouter()

DEFAULT = {"monthly_amount": 500, "yearly_amount": 10000}


class PricingIn(BaseModel):
    monthly_amount: int = Field(ge=0, le=100_000_000)
    yearly_amount: int = Field(ge=0, le=100_000_000)


def _row(db: Session):
    return db.execute(text("SELECT mdt_id, mdt_data FROM meta_data WHERE mdt_data LIKE :p ORDER BY mdt_id LIMIT 1"), {"p": '%"subscription"%'}).first()


@router.get("/subscription")
def get_pricing(admin=Depends(require_access("subscription")), db: Session = Depends(get_db)):
    row = _row(db)
    if row is None:
        return {**DEFAULT, "configured": False}
    try:
        sub = json.loads(row[1]).get("subscription") or {}
        return {"monthly_amount": int(float(sub.get("monthly_amount", DEFAULT["monthly_amount"]))), "yearly_amount": int(float(sub.get("yearly_amount", DEFAULT["yearly_amount"]))), "configured": True}
    except (ValueError, TypeError):
        return {**DEFAULT, "configured": False}


@router.put("/subscription")
def save_pricing(payload: PricingIn, admin=Depends(require_access("subscription")), db: Session = Depends(get_db)):
    row = _row(db)
    try:
        current = json.loads(row[1]) if row else {}
    except ValueError:
        raise HTTPException(status_code=409, detail="La configuration existante est illisible : modification refusée pour ne pas l'écraser.")
    current["subscription"] = {"monthly_amount": payload.monthly_amount, "yearly_amount": payload.yearly_amount}
    data = json.dumps(current, ensure_ascii=False)
    if row:
        db.execute(text("UPDATE meta_data SET mdt_data=:d WHERE mdt_id=:i"), {"d": data, "i": row[0]})
    else:
        db.execute(text("INSERT INTO meta_data (mdt_data) VALUES (:d)"), {"d": data})
    db.commit()
    return {**current["subscription"], "configured": True}
