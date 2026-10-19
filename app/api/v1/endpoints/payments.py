"""Paiement en ligne : webhook SEMOA (public, authentifie par la signature du jeton) et registre des paiements pour l'administration."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import require_access
from app.db.session import get_db
from app.services import booking as bk
from app.services import semoa

router = APIRouter()


class WebhookIn(BaseModel):
    token: str


@router.post("/semoa-webhook")
def semoa_webhook(payload: WebhookIn, db: Session = Depends(get_db)):
    """Appele par SEMOA apres un paiement. Le jeton est un JWT HS256 signe avec la cle API : tout autre appelant est refuse."""
    try:
        paid = semoa.handle_webhook(db, payload.token)
    except semoa.SemoaError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    return {"success": True, "paid": paid}


# ===================================================================== ADMINISTRATION : menu "Paiements"
_MODE_LABEL = {"PL": "Mise en relation", "BK": "Service", "ALL": "Service + mise en relation"}

_FROM = (
    "FROM payment_invoices i JOIN bookings b ON b.bk_id=i.pay_inv_owner_id LEFT JOIN vendors v ON v.vendor_id=b.bk_vendor_id "
    "LEFT JOIN services s ON s.s_id=b.bk_service_id LEFT JOIN (SELECT prc_invoice_id, SUM(prc_amount) AS paid, MAX(prc_date) AS paid_at, COUNT(*) AS n FROM payment_records GROUP BY prc_invoice_id) r ON r.prc_invoice_id=i.pay_inv_id"
)


@router.get("/admin")
def admin_payments(status: str | None = None, mode: str | None = None, q: str = "", page: int = 1, page_size: int = 20, admin=Depends(require_access("payments", write="view")), db: Session = Depends(get_db)):
    """Registre des paiements en ligne des reservations du pays : une ligne par facture (mise en relation, service ou les deux),
    avec ce qui a ete reellement encaisse. Filtres : statut (paid / pending), mode (PL / BK / ALL), recherche."""
    scope, params = bk.admin_scope(db, admin.country)
    where, p = [scope, "i.pay_inv_discr='booking'"], dict(params)
    if q.strip():
        where.append("(b.bk_unique_id LIKE :q OR b.bk_client_name LIKE :q OR b.bk_client_phone LIKE :q OR v.vendor_name LIKE :q OR i.pay_inv_reference LIKE :q)")
        p["q"] = f"%{q.strip()}%"
    if mode in _MODE_LABEL:
        where.append("i.pay_inv_mode = :mode")
        p["mode"] = mode
    base = " AND ".join(where)
    paid_sql, pending_sql = "COALESCE(r.n,0) > 0", "COALESCE(r.n,0) = 0"
    sums = db.execute(
        text(f"SELECT COUNT(*), COALESCE(SUM(CASE WHEN {paid_sql} THEN 1 ELSE 0 END),0), COALESCE(SUM(CASE WHEN {paid_sql} THEN r.paid ELSE 0 END),0), COALESCE(SUM(CASE WHEN {pending_sql} THEN i.pay_inv_amount ELSE 0 END),0) {_FROM} WHERE {base}"),
        p,
    ).first()
    counts = {"all": int(sums[0]), "paid": int(sums[1]), "pending": int(sums[0]) - int(sums[1])}
    shown = base + (f" AND {paid_sql}" if status == "paid" else f" AND {pending_sql}" if status == "pending" else "")
    page, page_size = max(1, page), min(max(1, page_size), 100)
    rows = db.execute(
        text(
            "SELECT i.pay_inv_id, i.pay_inv_reference, i.pay_inv_mode, i.pay_inv_amount, i.pay_inv_created_at, i.pay_inv_bill_url, COALESCE(r.paid,0), r.paid_at, "
            f"b.bk_id, b.bk_unique_id, b.bk_client_name, b.bk_client_phone, v.vendor_name, s.s_title {_FROM} WHERE {shown} ORDER BY i.pay_inv_created_at DESC, i.pay_inv_id DESC LIMIT :lim OFFSET :off"
        ),
        {**p, "lim": page_size, "off": (page - 1) * page_size},
    ).fetchall()
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    items = [
        {
            "id": r[0], "reference": r[1], "mode": r[2], "mode_label": _MODE_LABEL.get(r[2], r[2] or "—"), "amount": r[3], "created_at": iso(r[4]), "bill_url": r[5],
            "paid_amount": float(r[6] or 0), "paid_at": iso(r[7]), "status": "paid" if float(r[6] or 0) > 0 else "pending",
            "booking_id": r[8], "booking_ref": r[9], "client_name": r[10], "client_phone": r[11], "vendor_name": r[12], "service": r[13],
        }
        for r in rows
    ]
    total = counts["paid"] if status == "paid" else counts["pending"] if status == "pending" else counts["all"]
    return {"total": total, "page": page, "page_size": page_size, "counts": counts, "collected": float(sums[2]), "awaiting": float(sums[3]), "items": items}
