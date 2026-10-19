"""Reservations d'un prestataire : options, devis (prix recalcule cote serveur), creation, historique, annulation."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import current_country, current_lang, get_current_client, require_access
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.models.client import Client
from app.services import booking as bk
from app.services import booking_payment as bp
from app.services import semoa
from app.services.booking_mail import notify_new_booking
from app.services.security import accounts as sec
from app.services.security import verification as vf

router = APIRouter()


def _err(e: bk.BookingError) -> HTTPException:
    return HTTPException(status_code=e.status, detail={"message": e.message, "code": e.code} if e.code else e.message)


class QuoteIn(BaseModel):
    ref: str = Field(min_length=1, max_length=160)
    service_id: int
    unit_id: str | None = Field(default=None, max_length=20)
    qty: int = Field(default=1, ge=1, le=20)
    options: list[str] = Field(default_factory=list, max_length=20)
    coupon: str | None = Field(default=None, max_length=25)


class BookingIn(QuoteIn):
    date: str = Field(min_length=10, max_length=10)  # AAAA-MM-JJ
    time: str = Field(min_length=5, max_length=5)  # HH:MM
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=6, max_length=32)
    address: str = Field(min_length=3, max_length=300)
    info: str | None = Field(default=None, max_length=1000)
    district_id: int | None = None
    link: str | None = Field(default=None, max_length=255)
    latitude: float | None = None
    longitude: float | None = None
    street_name: str | None = Field(default=None, max_length=120)
    street_number: str | None = Field(default=None, max_length=30)
    postal_code: str | None = Field(default=None, max_length=10)
    payment: str = Field(default="cash", pattern="^(cash|online)$")
    # Paiement en ligne : ce que le client regle maintenant (ALL = tout, PL = mise en relation, BK = service).
    pay_mode: str = Field(default="ALL", pattern="^(ALL|PL|BK)$")


@router.get("/options/{ref}")
@limiter.limit("120/minute")
def options(request: Request, ref: str, lang: str = Depends(current_lang), country: str = Depends(current_country), db: Session = Depends(get_db)):
    """Services reservables DANS LE PAYS COURANT (le pays est porte par chaque service)."""
    data = bk.booking_options(db, ref, lang, country)
    if data is None:
        raise HTTPException(status_code=404, detail="Prestataire introuvable")
    return data


@router.post("/quote")
@limiter.limit("60/minute")
def quote(request: Request, payload: QuoteIn, lang: str = Depends(current_lang), country: str = Depends(current_country), db: Session = Depends(get_db)):
    """Prix detaille (service x quantite + options + mise en relation - coupon), calcule cote serveur."""
    try:
        return bk.quote(db, payload.ref, payload.service_id, payload.unit_id, payload.qty, payload.options, payload.coupon, lang, country)
    except bk.BookingError as e:
        raise _err(e)


@router.post("", status_code=201)
@limiter.limit("10/hour")
def create(request: Request, background: BackgroundTasks, payload: BookingIn, lang: str = Depends(current_lang), country: str = Depends(current_country), client: Client = Depends(get_current_client), db: Session = Depends(get_db)):
    return _make_booking(request, background, payload, lang, country, client, db, role="client", actor_id=client.id)


class AdminBookingIn(BookingIn):
    client_id: int


@router.post("/admin", status_code=201)
def admin_create(
    request: Request, background: BackgroundTasks, payload: AdminBookingIn, lang: str = Depends(current_lang), admin=Depends(require_access("bookings", write="manage")), db: Session = Depends(get_db),
):
    """Reservation saisie par l'administration POUR un client (appel, WhatsApp…). Memes controles et memes e-mails qu'une reservation
    faite par le client lui-meme ; le reglement est en especes (le client pourra payer en ligne depuis « Mes reservations »)."""
    client = db.get(Client, payload.client_id)
    if client is None or not client.is_active:
        raise HTTPException(status_code=404, detail="Client introuvable ou désactivé.")
    payload = payload.model_copy(update={"payment": "cash"})
    return _make_booking(request, background, payload, lang, admin.country, client, db, role="admin", actor_id=admin.id)


def _make_booking(request: Request, background: BackgroundTasks, payload: BookingIn, lang: str, country: str, client: Client, db: Session, *, role: str, actor_id: int):
    ip, ua = sec.client_ip(request), sec.client_agent(request)
    try:
        vendor = bk.listed_vendor(db, payload.ref, country)
        if vendor is None:
            raise bk.BookingError(404, "Prestataire introuvable.")
        try:
            day = datetime.strptime(payload.date, "%Y-%m-%d").date()
        except ValueError:
            raise bk.BookingError(422, "Date invalide.")
        bk.validate_when(day, payload.time)
        phone = vf.normalize_e164(payload.phone)
        if phone is None:
            raise bk.BookingError(422, "Numero de telephone invalide.")
        row, unit, chosen = bk._pick_service(db, vendor, payload.service_id, payload.unit_id, payload.options, lang, country)
        coupon = bk.coupon_for(db, payload.coupon)
        if (payload.coupon or "").strip() and coupon is None:
            raise bk.BookingError(422, "Code promo invalide ou deja utilise.", "bad_coupon")
        price = bk.compute_price(unit["price"], payload.qty, sum(o["price"] for o in chosen), bk.linking_amount(db, vendor["vendor_mark"]), coupon)
        loc = bk.validate_location(db, vendor, payload.model_dump())
        if payload.payment == "online" and not bk.online_available():
            raise bk.BookingError(422, "Le paiement en ligne n'est pas encore disponible : choisissez le paiement en especes.")
        if payload.payment == "online" and bp.split(price["total"], price["linking"])[payload.pay_mode] <= 0:
            raise bk.BookingError(422, "Ce choix de paiement n'est pas disponible pour cette reservation.")
        # une meme demande envoyee deux fois (double clic, reseau lent) ne cree qu'une reservation
        dup = db.execute(
            text("SELECT bk_unique_id FROM bookings WHERE bk_client_id=:c AND bk_vendor_id=:v AND bk_service_id=:s AND bk_date=:d AND bk_time=:t AND bk_created_at >= :since LIMIT 1"),
            {"c": client.id, "v": vendor["vendor_id"], "s": payload.service_id, "d": day, "t": payload.time, "since": datetime.utcnow() - timedelta(minutes=10)},
        ).first()
        if dup:
            raise bk.BookingError(409, f"Cette reservation existe deja ({dup[0]}).")
        data = {
            "name": " ".join(payload.name.split()), "phone": phone, "address": " ".join(payload.address.split()), "info": (payload.info or "").strip() or None, "time": payload.time,
            "qty": payload.qty, "coupon": coupon["c_code"] if coupon else None, "_coupon_id": coupon["cp_id"] if coupon else None, "payment": payload.payment, "pay_mode": payload.pay_mode,
            "street_name": payload.street_name, "street_number": payload.street_number, "postal_code": payload.postal_code,
            "country": country, "city": vendor.get("vendor_address_city"),  # pays du SERVICE reserve
        }
        created = bk.create_booking(db, client, vendor, data, price, row, unit, chosen, loc, day, ip)
    except bk.BookingError as e:
        raise _err(e)
    sec.log_event(db, "booking_created", role=role, account_id=actor_id, ip=ip, ua=ua, detail=f"{created['ref']} vendeur #{vendor['vendor_id']}" + (f" pour client #{client.id}" if role == "admin" else ""))
    district = db.execute(text("SELECT district_name FROM district WHERE district_id=:i"), {"i": loc["district_id"]}).scalar() if loc.get("district_id") else None
    # E-mails (client + administration) envoyes APRES la reponse : un echec d'envoi ne bloque jamais la reservation.
    background.add_task(
        notify_new_booking,
        {
            "ref": created["ref"], "lang": lang, "client_name": data["name"], "client_phone": data["phone"], "client_email": getattr(client, "email", None),
            "vendor_name": vendor["vendor_name"], "vendor_phone": vendor.get("vendor_phone"), "service": row["s_title"], "qty": payload.qty, "options": chosen,
            "date": day.isoformat(), "time": payload.time, "address": data["address"], "district": district, "map_link": loc["link"], "info": data["info"],
            "payment": payload.payment, "coupon": data["coupon"], "country": country, "price": price,
        },
    )
    return {"id": created["id"], "ref": created["ref"], "status": "pending", "price": price, "payment": {"method": payload.payment, "invoice": created.get("invoice"), "invoice_error": created.get("invoice_error")}}


_STATUS = {None: "pending", "0": "pending", "1": "pending", "2": "completed", "3": "cancelled", "4": "cancelled"}


@router.get("/mine")
@limiter.limit("60/minute")
def mine(request: Request, client: Client = Depends(get_current_client), db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            "SELECT b.bk_id, b.bk_unique_id, b.bk_date, b.bk_time, b.bk_total_amount, b.bk_amount_remaining, b.bk_payment_method, b.bk_payment_status, b.bk_service_status, "
            "b.bk_address, b.bk_vendor_id, v.vendor_name, s.s_title, b.bk_qty, b.bk_created_at, b.bk_linking_amount, b.bk_additional_info, b.bk_client_name, b.bk_client_phone "
            "FROM bookings b LEFT JOIN vendors v ON v.vendor_id=b.bk_vendor_id "
            "LEFT JOIN services s ON s.s_id=b.bk_service_id WHERE b.bk_client_id=:c ORDER BY b.bk_created_at DESC, b.bk_id DESC LIMIT 100"
        ),
        {"c": client.id},
    ).fetchall()
    paid = bp.paid_by_mode(db, [r[0] for r in rows])
    out = []
    for r in rows:
        total = bp._num(r[5]) or bp._num(r[4])
        pay = bp.summarize(total, bp._num(r[15]), paid.get(r[0]))
        out.append(
            {
                "id": r[0], "ref": r[1], "date": r[2].isoformat() if r[2] else None, "time": r[3], "total": r[5] or r[4], "payment_method": r[6], "paid": pay["status"] == "paid" or str(r[7]) == "1",
                "status": _STATUS.get(r[8], "pending"), "address": r[9], "vendor_id": r[10], "vendor_name": r[11], "service": r[12], "qty": r[13], "created_at": r[14].isoformat() if r[14] else None,
                "info": r[16], "client_name": r[17], "client_phone": r[18], "payment": pay,
            }
        )
    return out


def _own_booking(db: Session, booking_id: int, client_id: int):
    row = db.execute(
        text(
            "SELECT bk_id, bk_unique_id, bk_vendor_id, bk_client_name, bk_client_phone, bk_amount_remaining, bk_total_amount, bk_payment_method, bk_payment_status, bk_service_status, bk_linking_amount "
            "FROM bookings WHERE bk_id=:i AND bk_client_id=:c"
        ),
        {"i": booking_id, "c": client_id},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Reservation introuvable.")
    return row


def _open_invoice(db: Session, booking_id: int) -> dict | None:
    """Derniere facture de paiement encore ouverte (aucun paiement recu dessus) : le lien a ouvrir pour regler."""
    r = db.execute(
        text(
            "SELECT pay_inv_reference, pay_inv_bill_url, pay_inv_amount, pay_inv_currency, pay_inv_mode FROM payment_invoices i WHERE pay_inv_owner_id=:b AND pay_inv_discr='booking' "
            "AND pay_inv_bill_url IS NOT NULL AND NOT EXISTS (SELECT 1 FROM payment_records r WHERE r.prc_invoice_id = i.pay_inv_id) ORDER BY pay_inv_id DESC LIMIT 1"
        ),
        {"b": booking_id},
    ).first()
    return {"order_reference": r[0], "bill_url": r[1], "amount": r[2], "currency": r[3], "mode": r[4]} if r else None


def _payment_summary(db: Session, row) -> dict:
    total = bp._num(row[5]) or bp._num(row[6])
    return bp.summarize(total, bp._num(row[10]), bp.paid_by_mode(db, [row[0]]).get(row[0]))


@router.get("/{booking_id}/payment")
@limiter.limit("60/minute")
def payment_state(request: Request, booking_id: int, client: Client = Depends(get_current_client), db: Session = Depends(get_db)):
    """Etat du paiement d'une reservation du client connecte : montants, parts reglees, choix encore proposes (la confirmation arrive par le webhook SEMOA)."""
    row = _own_booking(db, booking_id, client.id)
    pay = _payment_summary(db, row)
    return {"id": row[0], "ref": row[1], "method": row[7], "paid": pay["status"] == "paid" or str(row[8]) == "1", "payment": pay, "invoice": _open_invoice(db, booking_id)}


class PayIn(BaseModel):
    mode: str = Field(default="ALL", pattern="^(ALL|PL|BK)$")


@router.post("/{booking_id}/pay")
@limiter.limit("20/hour")
def pay_again(request: Request, booking_id: int, payload: PayIn, client: Client = Depends(get_current_client), db: Session = Depends(get_db)):
    """(Re)lance le paiement en ligne d'une reservation en attente. `mode` : ALL (tout), PL (mise en relation), BK (service).
    Seules les parts pas encore reglees sont acceptees. Renvoie le lien de paiement SEMOA."""
    row = _own_booking(db, booking_id, client.id)
    if _STATUS.get(row[9], "pending") != "pending":
        raise HTTPException(status_code=409, detail="Cette reservation ne peut plus etre payee.")
    pay = _payment_summary(db, row)
    if pay["status"] == "paid" or not pay["options"]:
        raise HTTPException(status_code=409, detail="Cette reservation est deja payee.")
    choice = next((o for o in pay["options"] if o["mode"] == payload.mode), None)
    if choice is None:
        raise HTTPException(status_code=409, detail="Ce choix de paiement n'est plus disponible pour cette reservation.")
    if not semoa.configured():
        raise HTTPException(status_code=422, detail="Le paiement en ligne n'est pas encore disponible.")
    try:
        invoice = semoa.create_booking_invoice(db, booking_id=row[0], booking_ref=row[1], amount=float(choice["amount"]), phone=row[4] or "", name=row[3] or client.client_name, vendor_id=row[2], mode=payload.mode)
    except semoa.SemoaError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    db.execute(text("UPDATE bookings SET bk_payment_method='ligne' WHERE bk_id=:i"), {"i": booking_id})
    db.commit()
    return {"id": row[0], "ref": row[1], "invoice": invoice}


class EditIn(BaseModel):
    date: str = Field(min_length=10, max_length=10)  # AAAA-MM-JJ
    time: str = Field(min_length=5, max_length=5)  # HH:MM
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=6, max_length=32)
    address: str = Field(min_length=3, max_length=300)
    info: str | None = Field(default=None, max_length=1000)


@router.patch("/{booking_id}")
@limiter.limit("30/hour")
def edit(request: Request, booking_id: int, payload: EditIn, client: Client = Depends(get_current_client), db: Session = Depends(get_db)):
    """Modifie une reservation EN ATTENTE : rendez-vous, coordonnees, adresse, precisions. Le prix, le service et le prestataire ne changent pas."""
    row = _own_booking(db, booking_id, client.id)
    if _STATUS.get(row[9], "pending") != "pending":
        raise HTTPException(status_code=409, detail="Seule une reservation en attente peut etre modifiee.")
    try:
        day = datetime.strptime(payload.date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail="Date invalide.")
    try:
        bk.validate_when(day, payload.time)
    except bk.BookingError as e:
        raise _err(e)
    phone = vf.normalize_e164(payload.phone)
    if phone is None:
        raise HTTPException(status_code=422, detail="Numero de telephone invalide.")
    address = " ".join(payload.address.split())
    db.execute(
        text(
            "UPDATE bookings SET bk_date=:d, bk_time=:t, bk_selected_time=:t, bk_client_name=:n, bk_client_phone=:p, bk_address=:a, bk_client_address=:a, bk_additional_info=:i WHERE bk_id=:b AND bk_client_id=:c"
        ),
        {"d": day, "t": payload.time, "n": " ".join(payload.name.split()), "p": phone, "a": address, "i": (payload.info or "").strip() or None, "b": booking_id, "c": client.id},
    )
    db.commit()
    sec.log_event(db, "booking_edited", role="client", account_id=client.id, ip=sec.client_ip(request), ua=sec.client_agent(request), detail=row[1])
    return {"id": booking_id, "ref": row[1], "date": day.isoformat(), "time": payload.time, "address": address}


class CancelIn(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


@router.post("/{booking_id}/cancel")
@limiter.limit("20/hour")
def cancel(request: Request, booking_id: int, payload: CancelIn, client: Client = Depends(get_current_client), db: Session = Depends(get_db)):
    row = db.execute(text("SELECT bk_service_status, bk_unique_id FROM bookings WHERE bk_id=:i AND bk_client_id=:c"), {"i": booking_id, "c": client.id}).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Reservation introuvable.")
    if _STATUS.get(row[0], "pending") != "pending":
        raise HTTPException(status_code=409, detail="Cette reservation ne peut plus etre annulee.")
    db.execute(
        text("UPDATE bookings SET bk_service_status='4', bk_if_cancelled='1', bk_cancellation_reason=:r WHERE bk_id=:i AND bk_client_id=:c"),
        {"r": (payload.reason or "Annulee par le client").strip(), "i": booking_id, "c": client.id},
    )
    db.commit()
    sec.log_event(db, "booking_cancelled", role="client", account_id=client.id, ip=sec.client_ip(request), ua=sec.client_agent(request), detail=row[1])
    return {"id": booking_id, "status": "cancelled"}


# ===================================================================== ADMINISTRATION : menu "Reservations"
def _status_of(raw) -> str:
    return _STATUS.get(raw, "pending")


def _admin_row(r) -> dict:
    return {
        "id": r["bk_id"], "ref": r["bk_unique_id"], "created_at": r["bk_created_at"].isoformat() if r["bk_created_at"] else None,
        "date": r["bk_date"].isoformat() if r["bk_date"] else None, "time": r["bk_time"], "status": _status_of(r["bk_service_status"]),
        "paid": str(r["bk_payment_status"]) == "1", "payment_method": r["bk_payment_method"], "client_id": r["bk_client_id"], "client_name": r["bk_client_name"],
        "client_phone": r["bk_client_phone"], "vendor_id": r["bk_vendor_id"], "vendor_name": r["vendor_name"], "service": r["s_title"], "qty": r["bk_qty"],
        "total": r["bk_amount_remaining"] or r["bk_total_amount"], "country": r["bk_country"], "city": r["bk_city"], "platform": r["bk_plateform"],
    }


_ADMIN_COLS = (
    "b.bk_id, b.bk_unique_id, b.bk_created_at, b.bk_date, b.bk_time, b.bk_service_status, b.bk_payment_status, b.bk_payment_method, b.bk_client_id, b.bk_client_name, "
    "b.bk_client_phone, b.bk_vendor_id, v.vendor_name, s.s_title, b.bk_qty, b.bk_total_amount, b.bk_amount_remaining, b.bk_country, b.bk_city, b.bk_plateform"
)


@router.get("/admin")
def admin_list(
    status: str | None = None, q: str = "", date_from: str | None = None, date_to: str | None = None, page: int = 1, page_size: int = 25,
    admin=Depends(require_access("bookings", write="manage")), db: Session = Depends(get_db),
):
    """Reservations du pays courant, avec filtres (statut, recherche, dates), pagination et compteurs par statut."""
    scope, params = bk.admin_scope(db, admin.country)
    where, p = [scope], dict(params)
    if q.strip():
        where.append("(b.bk_unique_id LIKE :q OR b.bk_client_name LIKE :q OR b.bk_client_phone LIKE :q OR v.vendor_name LIKE :q)")
        p["q"] = f"%{q.strip()}%"
    for key, col, op in (("date_from", "b.bk_date", ">="), ("date_to", "b.bk_date", "<=")):
        value = locals()[key]
        if value:
            try:
                p[key] = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=422, detail="Date invalide (AAAA-MM-JJ).")
            where.append(f"{col} {op} :{key}")
    base = " AND ".join(where)
    counts = {"pending": 0, "completed": 0, "cancelled": 0}
    for key, cond in bk.STATUS_SQL.items():
        counts[key] = db.execute(text(f"SELECT COUNT(*) {bk.ADMIN_FROM} WHERE {base} AND {cond}"), p).scalar() or 0
    counts["all"] = sum(counts.values())
    shown = base + (f" AND {bk.STATUS_SQL[status]}" if status in bk.STATUS_SQL else "")
    page, page_size = max(1, page), min(max(1, page_size), 100)
    rows = db.execute(
        text(f"SELECT {_ADMIN_COLS} {bk.ADMIN_FROM} WHERE {shown} ORDER BY b.bk_created_at DESC, b.bk_id DESC LIMIT :lim OFFSET :off"),
        {**p, "lim": page_size, "off": (page - 1) * page_size},
    ).mappings().all()
    total = counts[status] if status in bk.STATUS_SQL else counts["all"]
    return {"total": total, "page": page, "page_size": page_size, "counts": counts, "items": [_admin_row(r) for r in rows]}


def _admin_booking(db: Session, admin, booking_id: int):
    scope, params = bk.admin_scope(db, admin.country)
    row = db.execute(text(f"SELECT b.*, v.vendor_name, v.vendor_phone, s.s_title {bk.ADMIN_FROM} WHERE b.bk_id=:i AND {scope}"), {"i": booking_id, **params}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Reservation introuvable.")
    return row


@router.get("/admin/{booking_id}")
def admin_detail(booking_id: int, admin=Depends(require_access("bookings", write="manage")), db: Session = Depends(get_db)):
    r = _admin_booking(db, admin, booking_id)
    client = db.execute(text("SELECT client_email FROM clients WHERE client_id=:i"), {"i": r["bk_client_id"]}).scalar() if r["bk_client_id"] else None
    district = db.execute(text("SELECT district_name FROM district WHERE district_id=:i"), {"i": r["bk_district_id"]}).scalar() if r["bk_district_id"] else None

    def loads(raw):
        import json

        try:
            return json.loads(raw) if raw else []
        except ValueError:
            return []

    base = _admin_row({**r, "vendor_name": r["vendor_name"], "s_title": r["s_title"]})
    total = bp._num(r["bk_amount_remaining"]) or bp._num(r["bk_total_amount"])
    payment = bp.summarize(total, bp._num(r["bk_linking_amount"]), bp.paid_by_mode(db, [booking_id]).get(booking_id))
    invoices = [
        {"id": i[0], "reference": i[1], "mode": i[2], "amount": i[3], "created_at": i[4].isoformat() if i[4] else None, "bill_url": i[5], "paid_amount": float(i[6] or 0), "paid_at": i[7].isoformat() if i[7] else None}
        for i in db.execute(
            text(
                "SELECT i.pay_inv_id, i.pay_inv_reference, i.pay_inv_mode, i.pay_inv_amount, i.pay_inv_created_at, i.pay_inv_bill_url, COALESCE(SUM(p.prc_amount),0), MAX(p.prc_date) "
                "FROM payment_invoices i LEFT JOIN payment_records p ON p.prc_invoice_id = i.pay_inv_id WHERE i.pay_inv_owner_id=:b AND i.pay_inv_discr='booking' GROUP BY i.pay_inv_id ORDER BY i.pay_inv_id DESC"
            ),
            {"b": booking_id},
        ).fetchall()
    ]
    return {
        "payment": payment, "invoices": invoices,
        **base, "client_email": client, "vendor_phone": r["vendor_phone"], "address": r["bk_address"], "district": district, "info": r["bk_additional_info"],
        "map_link": r["bk_link_geolocation"], "latitude": float(r["bk_latitude"]) if r["bk_latitude"] is not None else None,
        "longitude": float(r["bk_longitude"]) if r["bk_longitude"] is not None else None, "options": loads(r["bk_additional_options"]),
        "coupon": r["bk_coupon_code"], "total_before_discount": r["bk_total_amount"], "linking": r["bk_linking_amount"], "cancellation_reason": r["bk_cancellation_reason"],
        "street": " ".join(x for x in (r["bk_street_number"], r["bk_street_name"]) if x) or None, "postal_code": r["bk_postal_code"],
    }


class StatusIn(BaseModel):
    status: str = Field(pattern="^(completed|cancelled)$")
    reason: str | None = Field(default=None, max_length=300)


@router.post("/admin/{booking_id}/status")
def admin_set_status(request: Request, booking_id: int, payload: StatusIn, admin=Depends(require_access("bookings", write="manage")), db: Session = Depends(get_db)):
    """Marque une reservation en attente comme terminee ou l'annule (memes valeurs que le backend Trankyl : '2' / '4')."""
    r = _admin_booking(db, admin, booking_id)
    if _status_of(r["bk_service_status"]) != "pending":
        raise HTTPException(status_code=409, detail="Seule une reservation en attente peut changer de statut.")
    if payload.status == "completed":
        db.execute(text("UPDATE bookings SET bk_service_status='2' WHERE bk_id=:i"), {"i": booking_id})
        try:  # comme le backend Trankyl : un metier realise de plus pour le prestataire
            db.execute(text("UPDATE vendors SET vendor_jobs_count = COALESCE(vendor_jobs_count,0) + 1 WHERE vendor_id=:v"), {"v": r["bk_vendor_id"]})
        except Exception:  # noqa: BLE001
            pass
    else:
        db.execute(
            text("UPDATE bookings SET bk_service_status='4', bk_if_cancelled='1', bk_cancellation_reason=:r WHERE bk_id=:i"),
            {"r": (payload.reason or "Annulee par l'administration").strip(), "i": booking_id},
        )
    db.commit()
    sec.log_event(db, "booking_status", role="admin", account_id=admin.id, ip=sec.client_ip(request), ua=sec.client_agent(request), detail=f"{r['bk_unique_id']} -> {payload.status}")
    return {"id": booking_id, "status": payload.status}


class AdminBookingEdit(BaseModel):
    date: str | None = Field(default=None, description="AAAA-MM-JJ")
    time: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=500)
    info: str | None = Field(default=None, max_length=1000)
    client_name: str | None = Field(default=None, max_length=255)
    client_phone: str | None = Field(default=None, max_length=50)


@router.put("/admin/{booking_id}")
def admin_edit(request: Request, booking_id: int, payload: AdminBookingEdit, admin=Depends(require_access("bookings", write="manage")), db: Session = Depends(get_db)):
    """Corrige les informations pratiques d'une reservation EN ATTENTE (date, heure, adresse, consignes, coordonnees du client).
    Les montants, le service et le prestataire ne se modifient pas ici : ils sont deja facturés."""
    r = _admin_booking(db, admin, booking_id)
    if _status_of(r["bk_service_status"]) != "pending":
        raise HTTPException(status_code=409, detail="Seule une reservation en attente peut etre modifiee.")
    sets: dict = {}
    if payload.date:
        try:
            sets["bk_date"] = datetime.strptime(payload.date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=422, detail="Date invalide (AAAA-MM-JJ).")
    for field, col in (("time", "bk_time"), ("address", "bk_address"), ("info", "bk_additional_info"), ("client_name", "bk_client_name"), ("client_phone", "bk_client_phone")):
        value = getattr(payload, field)
        if value is not None:
            sets[col] = value.strip()
    if not sets:
        raise HTTPException(status_code=422, detail="Rien a modifier.")
    db.execute(text("UPDATE bookings SET " + ", ".join(f"{c}=:{c}" for c in sets) + " WHERE bk_id=:_i"), {**sets, "_i": booking_id})
    db.commit()
    sec.log_event(db, "booking_edited", role="admin", account_id=admin.id, ip=sec.client_ip(request), ua=sec.client_agent(request), detail=f"{r['bk_unique_id']} : {', '.join(sets)}")
    return {"id": booking_id}


@router.delete("/admin/{booking_id}", status_code=204)
def admin_delete(request: Request, booking_id: int, admin=Depends(require_access("bookings", write="manage")), db: Session = Depends(get_db)):
    """Supprime une reservation SANS aucun paiement (saisie erronee, doublon). Une reservation payee ou terminee est conservee : on l'annule."""
    r = _admin_booking(db, admin, booking_id)
    paid = db.execute(
        text("SELECT 1 FROM payment_records p JOIN payment_invoices i ON i.pay_inv_id=p.prc_invoice_id WHERE i.pay_inv_owner_id=:b AND i.pay_inv_discr='booking' LIMIT 1"), {"b": booking_id}
    ).first()
    if paid or str(r["bk_payment_status"]) == "1" or _status_of(r["bk_service_status"]) == "completed":
        raise HTTPException(status_code=409, detail="Cette reservation a ete payee ou terminee : elle ne peut pas etre supprimee. Annulez-la pour la conserver dans l'historique.")
    try:
        db.execute(text("DELETE FROM payment_invoices WHERE pay_inv_owner_id=:b AND pay_inv_discr='booking'"), {"b": booking_id})
        db.execute(text("DELETE FROM bookings WHERE bk_id=:b"), {"b": booking_id})
        db.commit()
    except Exception:  # noqa: BLE001  (lignes liees : avis, notes, factures...)
        db.rollback()
        raise HTTPException(status_code=409, detail="Cette reservation est liee a d'autres donnees (avis, factures...) : annulez-la plutot que de la supprimer.")
    sec.log_event(db, "booking_deleted", role="admin", account_id=admin.id, ip=sec.client_ip(request), ua=sec.client_agent(request), detail=r["bk_unique_id"])
