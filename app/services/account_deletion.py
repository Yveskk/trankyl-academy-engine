"""Suppression de compte prestataire en trois temps (pratique des grandes plateformes) :

1. **Controles** : pas de suppression tant qu'il reste des missions ou des demandes de devis en cours.
2. **Delai de reflexion** (`GRACE_DAYS` jours) : le compte est desactive et disparait du site, mais une simple reconnexion
   (mot de passe correct) annule la suppression et remet en ligne les services qui l'etaient.
3. **Anonymisation** a l'echeance : les donnees personnelles sont effacees ; les reservations, paiements, avis et abonnements
   sont CONSERVES (obligations comptables, litiges, historique des clients) mais ne designent plus qu'un « Ancien prestataire »."""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.api.v1.endpoints.directory import clear_directory_cache
from app.db.session import SessionLocal
from app.services.home import invalidate_home_cache

_log = logging.getLogger("account_deletion")

GRACE_DAYS = 30
ANON_NAME = "Ancien prestataire"
PENDING_BOOKING = "(b.bk_service_status IS NULL OR b.bk_service_status IN ('0','1'))"


def _refresh() -> None:
    clear_directory_cache()
    invalidate_home_cache()


# --------------------------------------------------------------------------- controles
def blockers(db: Session, vendor_id: int) -> list[dict]:
    """Ce qui empeche la suppression tant que ce n'est pas termine."""
    out: list[dict] = []
    n = db.execute(text(f"SELECT COUNT(*) FROM bookings b WHERE b.bk_vendor_id=:v AND {PENDING_BOOKING}"), {"v": vendor_id}).scalar() or 0
    if n:
        out.append({"key": "bookings", "count": int(n), "label": f"{n} mission(s) en cours ou à venir à terminer ou annuler", "href": "/prestataire/demandes"})
    q = db.execute(text("SELECT COUNT(*) FROM academy_quote_requests WHERE vendor_id=:v AND status='new'"), {"v": vendor_id}).scalar() or 0
    if q:
        out.append({"key": "quotes", "count": int(q), "label": f"{q} demande(s) de devis sans réponse", "href": "/prestataire/devis"})
    return out


def pending_row(db: Session, vendor_id: int):
    return db.execute(text("SELECT id, scheduled_for FROM academy_account_deletions WHERE vendor_id=:v AND status='pending' ORDER BY id DESC LIMIT 1"), {"v": vendor_id}).first()


def status(db: Session, vendor_id: int) -> dict:
    sub = db.execute(text("SELECT MAX(subs_end_date) FROM subscriptions WHERE subs_vendor_id=:v AND subs_is_active=1 AND subs_end_date>=:n"), {"v": vendor_id, "n": datetime.utcnow()}).scalar()
    return {"grace_days": GRACE_DAYS, "blockers": blockers(db, vendor_id), "active_subscription_until": sub.isoformat() if sub else None}


# --------------------------------------------------------------------------- demande
def request_deletion(db: Session, vendor_id: int) -> datetime:
    """Desactive le compte et programme l'anonymisation. Les services visibles sont memorises pour une eventuelle reactivation."""
    now = datetime.utcnow()
    due = now + timedelta(days=GRACE_DAYS)
    if row := pending_row(db, vendor_id):
        return row[1]
    visible = [r[0] for r in db.execute(text("SELECT s_id FROM services WHERE s_vendor_id=:v AND s_is_active='1'"), {"v": str(vendor_id)}).fetchall()]
    was = db.execute(text("SELECT vendor_is_active FROM vendors WHERE vendor_id=:v"), {"v": vendor_id}).scalar()
    db.execute(
        text("INSERT INTO academy_account_deletions (vendor_id, status, requested_at, scheduled_for, restore_services, was_active) VALUES (:v, 'pending', :n, :d, :s, :w)"),
        {"v": vendor_id, "n": now, "d": due, "s": json.dumps(visible), "w": was},
    )
    db.execute(text("UPDATE services SET s_is_active='0' WHERE s_vendor_id=:v"), {"v": str(vendor_id)})
    db.execute(text("UPDATE vendors SET vendor_account_deleted=1, vendor_is_active='0' WHERE vendor_id=:v"), {"v": vendor_id})
    db.commit()
    _refresh()
    return due


def cancel_if_pending(db: Session, vendor_id: int) -> bool:
    """Reconnexion pendant le delai : le compte et ses services redeviennent comme avant. Renvoie True si une suppression a ete annulee."""
    try:
        row = db.execute(text("SELECT id, restore_services, was_active FROM academy_account_deletions WHERE vendor_id=:v AND status='pending' ORDER BY id DESC LIMIT 1"), {"v": vendor_id}).first()
    except Exception:  # noqa: BLE001  (table absente : migration 0015 non appliquee) -> la connexion ne doit jamais en dependre
        db.rollback()
        _log.warning("Table academy_account_deletions absente : lancez `alembic upgrade head`.")
        return False
    if not row:
        return False
    claimed = db.execute(text("UPDATE academy_account_deletions SET status='cancelled', cancelled_at=:n WHERE id=:i AND status='pending'"), {"n": datetime.utcnow(), "i": row[0]}).rowcount
    if not claimed:  # l'anonymisation est passee entre-temps
        db.rollback()
        return False
    try:
        ids = [int(i) for i in json.loads(row[1] or "[]")]
    except ValueError:
        ids = []
    if ids:
        db.execute(text("UPDATE services SET s_is_active='1' WHERE s_vendor_id=:v AND s_id IN :ids").bindparams(bindparam("ids", expanding=True)), {"v": str(vendor_id), "ids": ids})
    db.execute(text("UPDATE vendors SET vendor_account_deleted=0, vendor_is_active=:a WHERE vendor_id=:v"), {"a": row[2] if row[2] not in (None, "", "0") else "1", "v": vendor_id})
    db.commit()
    _refresh()
    return True


# --------------------------------------------------------------------------- anonymisation
def _try(db: Session, sql: str, params: dict) -> None:
    """Table ou colonne absente d'une base ancienne : on passe, sans faire echouer le reste."""
    try:
        db.execute(text(sql), params)
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        _log.info("anonymisation ignoree (%s) : %s", sql[:60], e)


def _scrub(db: Session, table: str, key: str, key_value, values: dict) -> None:
    """UPDATE n'ecrivant que les colonnes qui existent reellement dans cette base (le schema partage varie d'un environnement a l'autre)."""
    have = {r[0] for r in db.execute(text("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:t"), {"t": table}).fetchall()}
    cols = {c: v for c, v in values.items() if c in have}
    if not cols or key not in have:
        return
    sets = ", ".join(f"{c}=:c_{i}" for i, c in enumerate(cols))
    try:
        db.execute(text(f"UPDATE {table} SET {sets} WHERE {key}=:_k"), {**{f"c_{i}": v for i, v in enumerate(cols.values())}, "_k": key_value})
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        raise


_VENDOR_NULL = (
    "vendor_family_name vendor_short_name vendor_email vendor_password vendor_token vendor_image vendor_address vendor_street_name vendor_street_number vendor_postal_code vendor_geolocation "
    "vendor_latitude vendor_longitude vendor_sex vendor_dob vendor_birth_date vendor_bio vendor_notes vendor_identification_number vendor_files vendor_slug vendor_whatsapp_list_on_phone "
    "vendor_emergency_contact_name vendor_emergency_contact_phone vendor_emergency_contact_relation vendor_emergency_contact_id_file company_name"
).split()
_ENROLL_NULL = (
    "enroll_family_name enroll_sex enroll_dob enroll_phone enroll_email enroll_address enroll_geolocation enroll_bio enroll_company_name enroll_id_number enroll_id_file enroll_id_file_verso "
    "enroll_diploma_file enroll_diploma_files enroll_cv_file enroll_cv_files enroll_photo enroll_rc_file enroll_casier_file enroll_cef_files approve_family_name approve_phone approve_email "
    "approve_address approve_geolocation approve_id_number approve_id_file approve_photo approve_bio"
).split()


def anonymize(db: Session, vendor_id: int) -> None:
    p = {"v": vendor_id, "vs": str(vendor_id)}
    _scrub(db, "vendors", "vendor_id", vendor_id, {**{c: None for c in _VENDOR_NULL}, "vendor_name": ANON_NAME, "vendor_phone": f"deleted-{vendor_id}", "vendor_is_active": "0", "vendor_account_deleted": 1})
    # Dossier d'enrolement : pieces et coordonnees effacees ; le contrat signe est garde comme preuve de l'accord.
    _scrub(db, "vendor_enrollments", "enroll_vendor_id", vendor_id, {**{c: None for c in _ENROLL_NULL}, "enroll_name": ANON_NAME, "approve_name": ANON_NAME})
    _try(db, "UPDATE academy_provider_profiles SET headline=NULL, about=NULL, cover_image_url=NULL, zone_label=NULL, services_note=NULL, services_note_en=NULL, public_slug=NULL WHERE vendor_id=:v", p)
    _try(db, "DELETE FROM academy_provider_media WHERE vendor_id=:v", p)
    _try(db, "DELETE FROM academy_provider_availability WHERE vendor_id=:v", p)
    _try(db, "DELETE FROM emergency_contacts WHERE emco_vendor_id=:v", p)
    _try(db, "UPDATE academy_reviews SET reply=NULL WHERE vendor_id=:v", p)
    _try(db, "UPDATE services SET s_is_active='0', s_is_deleted='1', s_image=NULL, s_notes='' WHERE s_vendor_id=:vs", p)
    _try(db, "UPDATE academy_quote_requests SET vendor_name=:n WHERE vendor_id=:v", {**p, "n": ANON_NAME})
    _try(db, "DELETE FROM notifications WHERE noti_vendor_id=:v", p)
    db.commit()


def purge_due(db: Session | None = None) -> int:
    """Anonymise les comptes dont le delai est ecoule. Sur sans conflit entre plusieurs processus : chaque ligne est « reservee » avant traitement."""
    own = db is None
    db = db or SessionLocal()
    done = 0
    try:
        rows = db.execute(text("SELECT id, vendor_id FROM academy_account_deletions WHERE status='pending' AND scheduled_for<=:n ORDER BY id LIMIT 50"), {"n": datetime.utcnow()}).fetchall()
        for rid, vid in rows:
            if not db.execute(text("UPDATE academy_account_deletions SET status='processing' WHERE id=:i AND status='pending'"), {"i": rid}).rowcount:
                db.rollback()
                continue
            db.commit()
            try:
                anonymize(db, int(vid))
                db.execute(text("UPDATE academy_account_deletions SET status='done', anonymized_at=:n WHERE id=:i"), {"n": datetime.utcnow(), "i": rid})
                db.commit()
                done += 1
            except Exception:  # noqa: BLE001
                db.rollback()
                db.execute(text("UPDATE academy_account_deletions SET status='pending' WHERE id=:i"), {"i": rid})  # reessaye au prochain passage
                db.commit()
                _log.exception("anonymisation du prestataire %s echouee", vid)
        if done:
            _refresh()
    finally:
        if own:
            db.close()
    return done


def start_scheduler(interval_seconds: int = 6 * 3600) -> None:
    """Passage periodique en arriere-plan (au demarrage puis toutes les 6 h)."""

    def loop() -> None:
        time.sleep(30)  # laisse l'application demarrer
        while True:
            try:
                n = purge_due()
                if n:
                    _log.info("%s compte(s) anonymise(s)", n)
            except Exception:  # noqa: BLE001
                _log.exception("passage d'anonymisation echoue (table absente ? lancez les migrations)")
            time.sleep(interval_seconds)

    threading.Thread(target=loop, name="account-purge", daemon=True).start()
