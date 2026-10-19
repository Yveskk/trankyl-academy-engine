"""Tableau de bord d'exploitation de l'administration : indicateurs, graphiques et dernieres activites du pays de l'administrateur.

Meme contenu que le tableau de bord de l'admin Angular Trankyl (reservations, revenus, clients, prestataires, abonnements, services,
demandes de contact, avis), calcule en quelques requetes groupees. Chaque bloc est independant : une table absente ou une colonne
differente d'un environnement n'empeche pas d'afficher les autres."""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import require_access
from app.db.session import get_db
from app.services import booking as bk
from app.services.countries import marketplace_country_id, service_country_clause, vendor_country_clause

router = APIRouter()
_log = logging.getLogger("admin_dashboard")

AMOUNT = "CAST(COALESCE(NULLIF(b.bk_amount_remaining,''), NULLIF(b.bk_total_amount,''), '0') AS DECIMAL(14,2))"
DONE, PENDING, CANCELLED = "b.bk_service_status = '2'", bk.STATUS_SQL["pending"], bk.STATUS_SQL["cancelled"]


def _safe(db: Session, fn, default):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        _log.warning("bloc du tableau de bord ignore : %s", e)
        return default


def _iso(d) -> str | None:
    return d.isoformat() if d else None


@router.get("/operations")
def operations(admin=Depends(require_access("dashboard")), db: Session = Depends(get_db)):
    scope, sp = bk.admin_scope(db, admin.country)
    v_clause, v_params = vendor_country_clause(db, admin.country, "v")
    s_clause, s_params = service_country_clause(db, admin.country, "s")
    cid = marketplace_country_id(db, admin.country)
    now = datetime.utcnow()
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    today = now.date()
    p = {**sp, "first": first, "today": today}

    def kpi_bookings() -> dict:
        r = db.execute(
            text(
                f"SELECT COUNT(*), SUM(CASE WHEN b.bk_created_at >= :first THEN 1 ELSE 0 END), SUM(CASE WHEN DATE(b.bk_created_at) = :today THEN 1 ELSE 0 END), "
                f"COALESCE(SUM(CASE WHEN {DONE} THEN {AMOUNT} ELSE 0 END),0), COALESCE(SUM(CASE WHEN {DONE} AND b.bk_created_at >= :first THEN {AMOUNT} ELSE 0 END),0), "
                f"COUNT(DISTINCT CASE WHEN b.bk_created_at >= :first THEN b.bk_client_id END) {bk.ADMIN_FROM} WHERE {scope}"
            ),
            p,
        ).first()
        return {"bookingsTotal": int(r[0] or 0), "bookingsThisMonth": int(r[1] or 0), "bookingsToday": int(r[2] or 0), "revenueTotal": float(r[3] or 0), "revenueThisMonth": float(r[4] or 0), "clientsActiveThisMonth": int(r[5] or 0)}

    def kpi_vendors() -> dict:
        vp = {**v_params, "now": now, "first": first}
        r = db.execute(
            text(
                "SELECT COUNT(*), SUM(CASE WHEN COALESCE(v.vendor_is_active,'1') IN ('1','true','yes') THEN 1 ELSE 0 END), SUM(CASE WHEN v.vendor_created_at >= :first THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN EXISTS (SELECT 1 FROM subscriptions su WHERE su.subs_vendor_id=v.vendor_id AND su.subs_is_active=1 AND su.subs_end_date>=:now) THEN 1 ELSE 0 END) "
                f"FROM vendors v WHERE {v_clause} AND COALESCE(v.vendor_account_deleted,'0') NOT IN ('1','true')"
            ),
            vp,
        ).first()
        return {"vendorsTotal": int(r[0] or 0), "vendorsActive": int(r[1] or 0), "vendorsThisMonth": int(r[2] or 0), "vendorsWithSubscription": int(r[3] or 0), "subscriptionsActive": int(r[3] or 0)}

    def kpi_clients() -> dict:
        n = db.execute(text("SELECT COUNT(*) FROM clients WHERE client_is_deleted='0' AND (:c IS NULL OR client_country_id=:c)"), {"c": cid}).scalar()
        return {"clientsTotal": int(n or 0)}

    def kpi_services() -> dict:
        r = db.execute(
            text(f"SELECT COUNT(*), SUM(CASE WHEN s.s_is_active='1' THEN 1 ELSE 0 END) FROM services s WHERE {s_clause} AND (s.s_is_deleted IS NULL OR s.s_is_deleted NOT IN ('1','true'))"), s_params
        ).first()
        return {"servicesTotal": int(r[0] or 0), "servicesActive": int(r[1] or 0)}

    def kpi_contacts() -> dict:
        return {"contactRequestsPending": int(db.execute(text("SELECT COUNT(*) FROM academy_contact_requests WHERE status='pending'")).scalar() or 0)}

    def kpi_reviews() -> dict:
        r = db.execute(text(f"SELECT AVG(r.rating), COUNT(*) FROM academy_reviews r JOIN vendors v ON v.vendor_id=r.vendor_id WHERE r.status='approved' AND {v_clause}"), v_params).first()
        return {"avgRating": round(float(r[0]), 2) if r and r[0] else None, "reviewsTotal": int(r[1] or 0) if r else 0}

    kpis = {
        "bookingsTotal": 0, "bookingsThisMonth": 0, "bookingsToday": 0, "revenueTotal": 0, "revenueThisMonth": 0, "clientsTotal": 0, "clientsActiveThisMonth": 0, "vendorsTotal": 0, "vendorsActive": 0,
        "vendorsWithSubscription": 0, "vendorsThisMonth": 0, "subscriptionsActive": 0, "servicesTotal": 0, "servicesActive": 0, "contactRequestsPending": 0, "avgRating": None, "reviewsTotal": 0,
    }
    for fn in (kpi_bookings, kpi_vendors, kpi_clients, kpi_services, kpi_contacts, kpi_reviews):
        kpis.update(_safe(db, fn, {}))

    def revenue_by_month() -> list:
        rows = db.execute(
            text(
                f"SELECT DATE_FORMAT(b.bk_created_at,'%Y-%m') m, COALESCE(SUM({AMOUNT}),0), COUNT(*) {bk.ADMIN_FROM} WHERE {scope} AND {DONE} AND b.bk_created_at >= DATE_SUB(:first, INTERVAL 5 MONTH) GROUP BY m ORDER BY m"
            ),
            p,
        ).fetchall()
        by = {r[0]: (float(r[1] or 0), int(r[2] or 0)) for r in rows}
        out, y, m = [], first.year, first.month
        months = []
        for _ in range(6):
            months.append(f"{y:04d}-{m:02d}")
            m, y = (12, y - 1) if m == 1 else (m - 1, y)
        for key in reversed(months):
            out.append({"month": key, "amount": by.get(key, (0, 0))[0], "count": by.get(key, (0, 0))[1]})
        return out

    def by_status() -> list:
        return [
            {"key": k, "label": label, "count": int(db.execute(text(f"SELECT COUNT(*) {bk.ADMIN_FROM} WHERE {scope} AND {cond}"), p).scalar() or 0)}
            for k, label, cond in (("pending", "En attente", PENDING), ("completed", "Terminées", DONE), ("cancelled", "Annulées", CANCELLED))
        ]

    def by_category() -> list:
        rows = db.execute(
            text(
                f"SELECT COALESCE(c.cat_name_fr,'Autre'), COUNT(*) {bk.ADMIN_FROM} LEFT JOIN sub_categories sc ON sc.subcat_id=s.s_subcat_id LEFT JOIN categories c ON c.cat_id=sc.subcat_cat_id "
                f"WHERE {scope} GROUP BY 1 ORDER BY 2 DESC LIMIT 6"
            ),
            p,
        ).fetchall()
        return [{"label": r[0], "count": int(r[1])} for r in rows]

    def by_payment_status() -> list:
        r = db.execute(text(f"SELECT SUM(CASE WHEN b.bk_payment_status='1' THEN 1 ELSE 0 END), SUM(CASE WHEN b.bk_payment_status='1' THEN 0 ELSE 1 END) {bk.ADMIN_FROM} WHERE {scope} AND NOT ({CANCELLED})"), p).first()
        return [{"label": "Payées", "count": int(r[0] or 0)}, {"label": "Non payées", "count": int(r[1] or 0)}]

    def by_method() -> list:
        rows = db.execute(text(f"SELECT COALESCE(NULLIF(b.bk_payment_method,''),'Non précisé'), COUNT(*) {bk.ADMIN_FROM} WHERE {scope} GROUP BY 1 ORDER BY 2 DESC LIMIT 6"), p).fetchall()
        return [{"label": str(r[0]), "count": int(r[1])} for r in rows]

    def top_vendors() -> list:
        rows = db.execute(
            text(
                f"SELECT b.bk_vendor_id, v.vendor_name, COUNT(*), COALESCE(SUM({AMOUNT}),0) {bk.ADMIN_FROM} WHERE {scope} AND {DONE} GROUP BY b.bk_vendor_id, v.vendor_name ORDER BY 3 DESC, 4 DESC LIMIT 5"
            ),
            p,
        ).fetchall()
        return [{"id": r[0], "name": r[1] or "—", "missions": int(r[2]), "revenue": float(r[3] or 0)} for r in rows]

    def recent_bookings() -> list:
        rows = db.execute(
            text(f"SELECT b.bk_id, b.bk_unique_id, b.bk_client_name, v.vendor_name, s.s_title, b.bk_service_status, b.bk_created_at, {AMOUNT} {bk.ADMIN_FROM} WHERE {scope} ORDER BY b.bk_created_at DESC, b.bk_id DESC LIMIT 6"), p
        ).fetchall()
        st = {None: "pending", "0": "pending", "1": "pending", "2": "completed", "3": "cancelled", "4": "cancelled"}
        return [{"id": r[0], "ref": r[1], "client": r[2], "vendor": r[3], "service": r[4], "status": st.get(r[5], "pending"), "created_at": _iso(r[6]), "amount": float(r[7] or 0)} for r in rows]

    def recent_contacts() -> list:
        rows = db.execute(
            text(
                "SELECT cr.id, cl.client_name, v.vendor_name, cr.status, cr.created_at FROM academy_contact_requests cr JOIN clients cl ON cl.client_id=cr.client_id "
                "JOIN vendors v ON v.vendor_id=cr.vendor_id ORDER BY cr.created_at DESC LIMIT 6"
            )
        ).fetchall()
        return [{"id": r[0], "client": r[1], "vendor": r[2], "status": r[3], "created_at": _iso(r[4])} for r in rows]

    return {
        "kpis": kpis,
        "charts": {
            "revenueByMonth": _safe(db, revenue_by_month, []), "bookingsByStatus": _safe(db, by_status, []), "bookingsByCategory": _safe(db, by_category, []),
            "bookingsByPaymentStatus": _safe(db, by_payment_status, []), "bookingsByPaymentMethod": _safe(db, by_method, []),
        },
        "topVendors": _safe(db, top_vendors, []), "recentBookings": _safe(db, recent_bookings, []), "recentContactRequests": _safe(db, recent_contacts, []),
        "generated_at": now.isoformat(),
    }
