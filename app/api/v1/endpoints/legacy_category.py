"""Catalogue categories / sous-categories — meme chemins, memes parametres et meme format de reponse que l'ancien backend
Trankyl (Node) : `GET /category/list|vendors|subcategories|subcategories-vendors` -> `{"data": [...], "status": "200"}`.

Les applications Trankyl (site, applis client et prestataire) n'ont qu'a viser l'API Academy (`<hote>/api/v1`) au lieu du
backend Node. Lecture seule et publique : ce sont des donnees de catalogue."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter()


def _rows(db: Session, sql: str, params: dict | None = None) -> list[dict]:
    return [dict(r) for r in db.execute(text(sql), params or {}).mappings().all()]


def _exists(db: Session, sql: str, params: dict) -> bool:
    return db.execute(text(sql + " LIMIT 1"), params).first() is not None


def _out(rows: list[dict]) -> dict:
    return {"data": jsonable_encoder(rows), "status": "200"}


def _fr_copy(row: dict, key_fr: str, key_en: str, lang: str) -> None:
    if lang == "fr":  # comportement historique : en francais, le nom « anglais » est aussi le nom francais
        row[key_en] = row.get(key_fr)


def _unities(db: Session, row: dict) -> list[dict]:
    try:
        ids = json.loads(row.get("subcat_extention") or "null")
    except (TypeError, ValueError):
        return []
    if not isinstance(ids, list) or not ids:
        return []
    keys = {f"u{i}": str(v) for i, v in enumerate(ids)}
    marks = ", ".join(f":{k}" for k in keys)
    return jsonable_encoder(_rows(db, f"SELECT * FROM service_unities WHERE sv_unit_id IN ({marks})", keys))


@router.get("/list")
def categories(lang: str = "fr", city_id: str | None = None, country_id: str | None = None, serviceType: str | None = None, db: Session = Depends(get_db)):
    out: list[dict] = []
    if serviceType:
        rows = _rows(
            db,
            "SELECT categories.*, COUNT(DISTINCT vendors.vendor_id) AS vendor_count, COUNT(DISTINCT bookings.bk_id) AS booking_count FROM categories "
            "INNER JOIN sub_categories ON sub_categories.subcat_cat_id = categories.cat_id INNER JOIN services ON services.s_subcat_id = sub_categories.subcat_id "
            "JOIN vendors ON services.s_vendor_id = vendors.vendor_id LEFT JOIN bookings ON bookings.bk_service_id = services.s_id AND bookings.bk_service_status = '4' "
            "WHERE services.s_type IN (:t, '2') AND services.s_city_id = :city AND services.s_country_id = :country AND vendors.vendor_is_active = 1 AND services.s_sub_services != '' "
            "GROUP BY categories.cat_id ORDER BY booking_count DESC, vendor_count DESC",
            {"t": serviceType, "city": city_id or "", "country": country_id or ""},
        )
        for row in rows:
            if city_id:
                row["if_available"] = _exists(
                    db,
                    "SELECT 1 FROM sub_categories INNER JOIN services ON services.s_subcat_id = sub_categories.subcat_id JOIN vendors ON services.s_vendor_id = vendors.vendor_id "
                    "WHERE sub_categories.subcat_cat_id = :c AND services.s_city_id = :city AND services.s_country_id = :country AND vendors.vendor_is_active = 1 "
                    "AND services.s_type IN (:t, '2') AND services.s_sub_services != ''",
                    {"c": str(row["cat_id"]), "city": city_id, "country": country_id or "", "t": serviceType},
                )
            _fr_copy(row, "cat_name_fr", "cat_name_en", lang)
            out.append(row)
    return _out(out)


@router.get("/vendors")
def categories_vendors(lang: str = "fr", city_id: str | None = None, country_id: str | None = None, serviceType: str | None = None, db: Session = Depends(get_db)):
    if serviceType:
        rows = _rows(
            db,
            "SELECT DISTINCT categories.* FROM categories INNER JOIN sub_categories ON sub_categories.subcat_cat_id = categories.cat_id "
            "INNER JOIN services ON services.s_subcat_id = sub_categories.subcat_id WHERE services.s_type IN (:t, '2') AND services.s_city_id = :city "
            "AND services.s_country_id = :country ORDER BY cat_order ASC",
            {"t": serviceType, "city": city_id or "", "country": country_id or ""},
        )
    else:
        rows = _rows(db, "SELECT * FROM categories ORDER BY cat_order ASC")
    for row in rows:
        if city_id:
            row["if_available"] = _exists(
                db,
                "SELECT 1 FROM sub_categories INNER JOIN services ON services.s_subcat_id = sub_categories.subcat_id WHERE sub_categories.subcat_cat_id = :c "
                "AND services.s_city_id = :city AND services.s_country_id = :country",
                {"c": str(row["cat_id"]), "city": city_id, "country": country_id or ""},
            )
        _fr_copy(row, "cat_name_fr", "cat_name_en", lang)
    return _out(rows)


@router.get("/subcategories")
def sub_categories(category_id: str, lang: str = "fr", city_id: str | None = None, serviceType: str | None = None, db: Session = Depends(get_db)):
    rows = _rows(
        db,
        "SELECT sub_categories.*, COUNT(DISTINCT vendors.vendor_id) AS vendor_count, COUNT(DISTINCT bookings.bk_id) AS booking_count FROM sub_categories "
        "INNER JOIN services ON services.s_subcat_id = sub_categories.subcat_id JOIN vendors ON services.s_vendor_id = vendors.vendor_id "
        "LEFT JOIN bookings ON bookings.bk_service_id = services.s_id AND bookings.bk_service_status = '4' "
        "WHERE services.s_city_id = :city AND services.s_type IN (:t, '2') AND subcat_cat_id = :c AND vendors.vendor_is_active = 1 AND services.s_sub_services != '' "
        "GROUP BY sub_categories.subcat_id ORDER BY booking_count DESC, vendor_count DESC",
        {"city": city_id or "", "t": serviceType or "", "c": category_id},
    )
    for row in rows:
        row["ifvendor_avai"] = _exists(
            db, "SELECT 1 FROM services WHERE services.s_subcat_id = :s AND services.s_city_id = :city AND services.s_sub_services != ''", {"s": str(row["subcat_id"]), "city": city_id or ""}
        )
        _fr_copy(row, "subcat_name_fr", "subcat_name_en", lang)
        row["unities"] = _unities(db, row)
    return _out(rows)


@router.get("/subcategories-vendors")
def sub_categories_vendors(category_id: str, lang: str = "fr", city_id: str | None = None, serviceType: str | None = None, db: Session = Depends(get_db)):
    if serviceType:
        rows = _rows(
            db,
            "SELECT DISTINCT sub_categories.* FROM sub_categories INNER JOIN services ON services.s_subcat_id = sub_categories.subcat_id "
            "WHERE services.s_type IN (:t, '2') AND subcat_cat_id = :c ORDER BY sub_categories.subcat_id DESC",
            {"t": serviceType, "c": category_id},
        )
    else:
        rows = _rows(db, "SELECT * FROM sub_categories WHERE subcat_cat_id = :c ORDER BY subcat_id DESC", {"c": category_id})
    for row in rows:
        row["ifvendor_avai"] = _exists(
            db, "SELECT 1 FROM services INNER JOIN vendors ON services.s_vendor_id = vendors.vendor_id WHERE services.s_subcat_id = :s AND vendors.vendor_city_id = :city",
            {"s": str(row["subcat_id"]), "city": city_id or ""},
        )
        _fr_copy(row, "subcat_name_fr", "subcat_name_en", lang)
        row["unities"] = _unities(db, row)
    return _out(rows)
