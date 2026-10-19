"""API generique des ressources d'administration declarees dans `services/admin_resources.py`."""
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import forbidden, get_admin_ctx
from app.db.session import get_db
from app.services import admin_resources as ar

router = APIRouter()


def _res(key: str, request: Request, admin) -> ar.Resource:
    try:
        res = ar.get(key)
    except ar.ResourceError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    if res.hidden:
        raise HTTPException(status_code=404, detail="Ressource inconnue.")
    action = "view" if request.method in ("GET", "HEAD", "OPTIONS") else "manage"
    perm = f"academy.{res.perm}.{action}"
    if not admin.access.has(perm):  # type: ignore[attr-defined]
        raise forbidden(perm)
    return res


def _fail(e: ar.ResourceError):
    raise HTTPException(status_code=e.status, detail=e.message)


def _select_sql(res: ar.Resource, db: Session) -> tuple[str, list[str]]:
    cols = ar.columns_of(db, res.table)
    extras = []
    for f in res.fields:
        if f.lookup and f.name in cols:
            ref = ar.get(f.lookup)
            label = (ref.label_sql or f"t.{ref.label_col}").replace("t.", "r.")
            extras.append(f"(SELECT {label} FROM {ref.table} r WHERE r.{ref.pk} = t.{f.name} LIMIT 1) AS `{f.name}__label`")
    return ", ".join(["t.*", *extras, *res.list_extra]), sorted(cols)


def _row(res: ar.Resource, raw: dict) -> dict:
    row = {k: ar.jsonable(v) for k, v in raw.items() if k not in res.hide_cols}
    row["_id"] = row.get(res.pk)
    row["_actions"] = [a.key for a in res.actions if a.when is None or a.when(row)]
    row["_can_delete"] = res.allow_delete and (res.can_delete is None or res.can_delete(row))
    return row


# --------------------------------------------------------------------------- meta
@router.get("/{key}/meta")
def meta(key: str, request: Request, admin=Depends(get_admin_ctx)):
    res = _res(key, request, admin)
    can_write = admin.access.has(f"academy.{res.perm}.manage")  # type: ignore[attr-defined]

    def fdict(f: ar.Field) -> dict:
        return {
            "name": f.name, "label": f.label, "kind": f.kind, "required": f.required, "options": [{"value": v, "label": l} for v, l in (f.options or [])], "lookup": f.lookup,
            "default": f.default, "help": f.help, "readonly": f.readonly, "create_only": f.create_only, "max": f.max, "on": f.on, "off": f.off, "upper": f.upper,
        }

    return {
        "key": res.key, "title": res.title, "singular": res.singular, "description": res.description, "pk": res.pk,
        "fields": [fdict(f) for f in res.fields if f.in_form and not f.readonly],
        "columns": [{"key": f.name, "label": f.label, "kind": f.list_kind or ("text" if not f.lookup else "lookup"), "lookup": bool(f.lookup), "options": [{"value": v, "label": l} for v, l in (f.options or [])], "width": f.width}
                    for f in res.fields if f.in_list],
        "filters": [{"key": fl["key"], "label": fl["label"], "options": [{"value": v, "label": l} for v, l in fl.get("options", [])], "lookup": fl.get("lookup")} for fl in res.filters],
        "search": bool(res.search), "has_created": bool(res.created_col), "created_col": res.created_col,
        "can": {"create": res.allow_create and can_write, "update": res.allow_update and can_write, "delete": res.allow_delete and can_write, "actions": can_write},
        "actions": [{"key": a.key, "label": a.label, "tone": a.tone, "confirm": a.confirm} for a in res.actions],
    }


# --------------------------------------------------------------------------- liste
@router.get("/{key}")
def list_rows(key: str, request: Request, q: str = "", page: int = 1, page_size: int = 20, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    res = _res(key, request, admin)
    try:
        select, cols = _select_sql(res, db)
    except ar.ResourceError as e:
        _fail(e)
    where, params = [], {}
    base = res.base_where
    if res.scope:
        clause, p = res.scope(db, admin.country)
        where.append(clause)
        params.update(p)
    for fl in res.filters:
        value = request.query_params.get(f"f_{fl['key']}")
        if value in (None, ""):
            continue
        if fl.get("sql"):
            clause = fl["sql"].get(value)
            if clause:
                where.append(clause)
                if fl.get("replaces_base"):
                    base = ""
        elif fl.get("column"):
            where.append(f"{fl['column']} = :f_{fl['key']}")
            params[f"f_{fl['key']}"] = value
    if base:
        where.append(base)
    if q.strip() and res.search:
        where.append("(" + " OR ".join(f"t.{c} LIKE :q" for c in res.search if c in cols) + ")")
        params["q"] = f"%{q.strip()}%"
    wsql = (" WHERE " + " AND ".join(where)) if where else ""
    page, page_size = max(1, page), min(max(1, page_size), 100)
    total = db.execute(text(f"SELECT COUNT(*) FROM {res.table} t{wsql}"), params).scalar() or 0
    order = res.order or f"t.{res.pk} DESC"
    rows = db.execute(text(f"SELECT {select} FROM {res.table} t{wsql} ORDER BY {order} LIMIT :lim OFFSET :off"), {**params, "lim": page_size, "off": (page - 1) * page_size}).mappings().all()
    return {"items": [_row(res, dict(r)) for r in rows], "total": total, "page": page, "page_size": page_size}


# --------------------------------------------------------------------------- listes deroulantes
@router.get("/{key}/options")
def options(key: str, q: str = "", limit: int = 500, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    """Valeurs proposees dans les champs « lookup » (nom + identifiant). Donnees non sensibles : tout administrateur peut les lire."""
    try:
        res = ar.get(key)
        ar.columns_of(db, res.table)
    except ar.ResourceError as e:
        _fail(e)
    where, params = [], {}
    if res.scope:
        clause, p = res.scope(db, admin.country)
        where.append(clause)
        params.update(p)
    if q.strip():
        where.append(f"{res.label_sql or 't.' + res.label_col} LIKE :q")
        params["q"] = f"%{q.strip()}%"
    wsql = (" WHERE " + " AND ".join(where)) if where else ""
    order = res.order or f"t.{res.label_col}"
    rows = db.execute(text(f"SELECT t.{res.pk}, {res.label_sql or 't.' + res.label_col} FROM {res.table} t{wsql} ORDER BY {order} LIMIT :lim"), {**params, "lim": min(max(limit, 1), 1000)}).fetchall()
    return [{"value": str(r[0]), "label": str(r[1])} for r in rows]


# --------------------------------------------------------------------------- ecriture
def _clean(db: Session, res: ar.Resource, payload: dict, creating: bool, current: dict | None = None) -> dict:
    data: dict = {}
    for f in res.fields:
        if f.readonly or not f.in_form or (f.create_only and not creating):
            continue
        if f.name not in payload:
            if creating and f.default is not None:
                data[f.name] = f.default
            elif creating and f.required:
                raise ar.ResourceError(f"« {f.label} » est obligatoire.")
            continue
        v = payload[f.name]
        if isinstance(v, str):
            v = v.strip()
        if f.kind == "switch":
            v = f.on if v in (True, 1, "1", "true", "on", f.on) else f.off
        elif v in (None, ""):
            if f.required:
                raise ar.ResourceError(f"« {f.label} » est obligatoire.")
            v = None
        elif f.kind == "number":
            try:
                n = float(str(v).replace(",", ".").replace(" ", ""))
            except ValueError:
                raise ar.ResourceError(f"« {f.label} » doit être un nombre.")
            v = int(n) if n == int(n) else n
        elif f.kind == "select" and f.options is not None:
            if str(v) not in {o[0] for o in f.options}:
                raise ar.ResourceError(f"Valeur invalide pour « {f.label} ».")
        elif f.kind == "email" and not ar.EMAIL.match(str(v)):
            raise ar.ResourceError("Adresse e-mail invalide.")
        if isinstance(v, str):
            if f.upper:
                v = v.upper()
            if f.max and len(v) > f.max:
                raise ar.ResourceError(f"« {f.label} » est trop long ({f.max} caractères maximum).")
        if f.lookup and v not in (None, ""):
            ref = ar.get(f.lookup)
            if not db.execute(text(f"SELECT 1 FROM {ref.table} WHERE {ref.pk}=:v"), {"v": v}).first():
                raise ar.ResourceError(f"« {f.label} » : valeur inconnue.")
        if f.unique and v not in (None, ""):
            same = db.execute(text(f"SELECT {res.pk} FROM {res.table} WHERE {f.name}=:v"), {"v": v}).first()
            if same and (creating or str(same[0]) != str((current or {}).get(res.pk))):
                raise ar.ResourceError(f"« {f.label} » existe déjà.", 409)
        data[f.name] = v
    if res.before_save:
        data = res.before_save(db, data, creating)
    return data


@router.post("/{key}", status_code=201)
def create(key: str, request: Request, payload: dict = Body(...), admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    res = _res(key, request, admin)
    if not res.allow_create:
        raise HTTPException(status_code=405, detail="Création impossible.")
    try:
        cols = ar.columns_of(db, res.table)
        data = _clean(db, res, payload, True)
        if res.scope and res.key == "cities" and not data.get("city_country_id"):
            data["city_country_id"] = ar.country_id(db, admin.country)
        if res.create_handler:
            res.create_handler(db, data, admin)
            db.commit()
            return {"ok": True}
        if res.created_col and res.created_col in cols:
            data[res.created_col] = datetime.utcnow()
        data = {k: v for k, v in data.items() if k in cols}
        db.execute(text(f"INSERT INTO {res.table} ({', '.join(data)}) VALUES ({', '.join(':' + k for k in data)})"), data)
        new_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        db.commit()
    except ar.ResourceError as e:
        db.rollback()
        _fail(e)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Enregistrement refusé : une valeur existe déjà ou une référence est invalide.")
    return {"ok": True, "id": new_id}


def _load(db: Session, res: ar.Resource, item_id: str, admin) -> dict:
    where = [f"t.{res.pk} = :id"]
    params: dict = {"id": item_id}
    if res.scope:
        clause, p = res.scope(db, admin.country)
        where.append(clause)
        params.update(p)
    row = db.execute(text(f"SELECT t.* FROM {res.table} t WHERE {' AND '.join(where)}"), params).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Élément introuvable.")
    return dict(row)


@router.put("/{key}/{item_id}")
def update(key: str, item_id: str, request: Request, payload: dict = Body(...), admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    res = _res(key, request, admin)
    if not res.allow_update:
        raise HTTPException(status_code=405, detail="Modification impossible.")
    current = _load(db, res, item_id, admin)
    try:
        cols = ar.columns_of(db, res.table)
        data = {k: v for k, v in _clean(db, res, payload, False, current).items() if k in cols}
        if data:
            db.execute(text(f"UPDATE {res.table} SET {', '.join(f'{k}=:{k}' for k in data)} WHERE {res.pk}=:__id"), {**data, "__id": item_id})
        db.commit()
    except ar.ResourceError as e:
        db.rollback()
        _fail(e)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Enregistrement refusé : une valeur existe déjà ou une référence est invalide.")
    return {"ok": True}


@router.delete("/{key}/{item_id}")
def delete(key: str, item_id: str, request: Request, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    res = _res(key, request, admin)
    if not res.allow_delete:
        raise HTTPException(status_code=405, detail="Suppression impossible.")
    row = _load(db, res, item_id, admin)
    if res.can_delete and not res.can_delete(row):
        raise HTTPException(status_code=409, detail="Cet élément ne peut pas être supprimé.")
    for table, column, label in res.dependents:
        try:
            n = db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {column}=:v"), {"v": item_id}).scalar() or 0
        except Exception:  # noqa: BLE001 - table absente de cette base : rien ne depend de l'element
            db.rollback()
            n = 0
        if n:
            raise HTTPException(status_code=409, detail=f"Suppression impossible : {n} {label} en dépendent. Désactivez-le plutôt.")
    try:
        if res.delete_handler:
            res.delete_handler(db, row, admin)
        else:
            db.execute(text(f"DELETE FROM {res.table} WHERE {res.pk}=:i"), {"i": item_id})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Suppression impossible : cet élément est utilisé ailleurs. Désactivez-le plutôt.")
    return {"ok": True}


@router.post("/{key}/{item_id}/actions/{action}")
def run_action(key: str, item_id: str, action: str, request: Request, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    res = _res(key, request, admin)
    act = next((a for a in res.actions if a.key == action), None)
    if act is None:
        raise HTTPException(status_code=404, detail="Action inconnue.")
    row = _load(db, res, item_id, admin)
    if act.when and not act.when(row):
        raise HTTPException(status_code=409, detail="Cette action n'est pas disponible pour cet élément.")
    try:
        message = act.handler(db, row, admin)
        db.commit()
    except ar.ResourceError as e:
        db.rollback()
        _fail(e)
    return {"ok": True, "message": message}


# --------------------------------------------------------------------------- codes de parrainage : utilisateurs
@router.get("/referrals/{item_id}/users")
def referral_users(item_id: str, request: Request, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    res = _res("referrals", request, admin)
    row = _load(db, res, item_id, admin)
    cols = ar.columns_of(db, "clients")
    if "client_referral_code" not in cols:
        return []
    rows = db.execute(
        text("SELECT client_id, client_unique_id, client_name, client_family_name, client_email, client_phone FROM clients WHERE client_referral_code=:c ORDER BY client_id DESC LIMIT 200"),
        {"c": row["rc_code"]},
    ).mappings().all()
    return [{k: ar.jsonable(v) for k, v in r.items()} for r in rows]
