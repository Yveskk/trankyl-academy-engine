"""Etat de paiement d'une reservation et choix de ce que le client regle en ligne.

Une reservation a un TOTAL (service + options + mise en relation - coupon) compose de deux parts :
  - la MISE EN RELATION (frais Trankyl, `bk_linking_amount`) ;
  - le SERVICE (le reste).
Le client choisit ce qu'il regle en ligne, comme sur le site Trankyl (`invoice_mode`) :
  PL  = mise en relation uniquement ;  BK = service uniquement ;  ALL = les deux.
Chaque facture SEMOA porte son mode (`payment_invoices.pay_inv_mode`) ; ce qui est deja regle se deduit des paiements
recus (`payment_records`). Seules les parts encore dues restent proposees."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

MODES = ("ALL", "PL", "BK")


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def split(total: float, linking: float) -> dict[str, float]:
    """Montant de chaque choix pour une reservation de ce total."""
    total = max(0.0, _num(total))
    pl = min(max(0.0, _num(linking)), total)
    return {"ALL": total, "PL": pl, "BK": total - pl}


def paid_by_mode(db: Session, booking_ids: list[int]) -> dict[int, dict[str, float]]:
    """{reservation: {mode: somme recue}} pour un lot de reservations (une seule requete)."""
    if not booking_ids:
        return {}
    from sqlalchemy import bindparam

    rows = db.execute(
        text(
            "SELECT i.pay_inv_owner_id, i.pay_inv_mode, COALESCE(SUM(r.prc_amount),0) FROM payment_invoices i "
            "JOIN payment_records r ON r.prc_invoice_id = i.pay_inv_id WHERE i.pay_inv_discr='booking' AND i.pay_inv_owner_id IN :ids GROUP BY i.pay_inv_owner_id, i.pay_inv_mode"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": booking_ids},
    ).fetchall()
    out: dict[int, dict[str, float]] = {}
    for bid, mode, amount in rows:
        out.setdefault(int(bid), {})[mode or "ALL"] = float(amount)
    return out


def summarize(total, linking, paid: dict[str, float] | None) -> dict:
    """Resume de paiement : montants, ce qui est regle, statut et choix encore proposes."""
    paid = paid or {}
    amounts = split(total, linking)
    linking_paid = any(paid.get(m, 0) > 0 for m in ("PL", "ALL"))
    service_paid = any(paid.get(m, 0) > 0 for m in ("BK", "ALL"))
    received = sum(paid.values())
    status = "paid" if amounts["ALL"] > 0 and received >= amounts["ALL"] else ("partial" if received > 0 else "unpaid")
    if linking_paid and service_paid:
        due: list[str] = []
    elif linking_paid:
        due = ["BK"]
    elif service_paid:
        due = ["PL"]
    else:
        due = list(MODES)
    options = [{"mode": m, "amount": int(amounts[m])} for m in due if amounts[m] > 0]
    return {
        "total": int(amounts["ALL"]), "linking": int(amounts["PL"]), "service": int(amounts["BK"]), "paid": int(received),
        "linking_paid": linking_paid, "service_paid": service_paid, "remaining": int(max(0.0, amounts["ALL"] - received)), "status": status, "options": options,
    }


def booking_summary(db: Session, booking_id: int) -> dict | None:
    b = db.execute(text("SELECT bk_amount_remaining, bk_total_amount, bk_linking_amount FROM bookings WHERE bk_id=:i"), {"i": booking_id}).first()
    if b is None:
        return None
    total = _num(b[0]) or _num(b[1])
    return summarize(total, _num(b[2]), paid_by_mode(db, [booking_id]).get(booking_id))
