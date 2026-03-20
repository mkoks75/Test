import io
import csv
import datetime
from datetime import timedelta

import bcrypt
from fastapi import FastAPI, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

import models
import database
from database import get_db
from auth import get_current_user, authenticate_user, create_access_token
from config import ACCESS_TOKEN_EXPIRE_MINUTES, USERS

# Maak database tabellen aan
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
async def startup():
    """Migreer schema-wijzigingen en hardcoded gebruikers naar de database."""
    # Voeg nieuwe kolommen toe aan bestaande databases (SQLite ondersteunt geen automatische migratie)
    from sqlalchemy import text
    with database.engine.connect() as conn:
        try:
            pragma = conn.execute(text("PRAGMA table_info(harvest_entries)")).fetchall()
            col_names = [row[1] for row in pragma]
            if "houdbaar_tot" not in col_names:
                conn.execute(text("ALTER TABLE harvest_entries ADD COLUMN houdbaar_tot DATE"))
            if "volgnummer" not in col_names:
                conn.execute(text("ALTER TABLE harvest_entries ADD COLUMN volgnummer INTEGER"))
            conn.commit()
        except Exception:
            pass  # Tabel bestaat nog niet; create_all regelt dit

        # Migreer uitgiftes tabel (aangemaakt via create_all, maar voor zekerheid)
        try:
            conn.execute(text("SELECT 1 FROM uitgiftes LIMIT 1"))
        except Exception:
            pass  # Wordt aangemaakt door create_all

    # Migreer hardcoded gebruikers uit config.py naar de database
    db = database.SessionLocal()
    try:
        for username, user_data in USERS.items():
            existing = db.query(models.User).filter(models.User.username == username).first()
            if not existing:
                db_user = models.User(
                    username=username,
                    hashed_password=user_data["hashed_password"],
                )
                db.add(db_user)
        db.commit()
    finally:
        db.close()


# ── Authenticatie ──────────────────────────────────────────────────────────────

@app.get("/login")
async def login_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    user = authenticate_user(username, password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Ongeldige gebruikersnaam of wachtwoord"},
        )
    token = create_access_token(
        {"sub": username}, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        "access_token", token, httponly=True, max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("access_token")
    return response


# ── Dashboard ──────────────────────────────────────────────────────────────────

@app.get("/")
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    # Totaaloverzicht per locatie + product (oogst minus uitgifte)
    harvest_results = (
        db.query(
            models.Location.id.label("location_id"),
            models.Location.name.label("location_name"),
            models.Product.id.label("product_id"),
            models.Product.name.label("product_name"),
            models.Product.unit.label("unit"),
            func.sum(models.HarvestEntry.quantity).label("total"),
        )
        .select_from(models.HarvestEntry)
        .join(models.Product, models.HarvestEntry.product_id == models.Product.id)
        .join(models.Location, models.HarvestEntry.location_id == models.Location.id)
        .group_by(
            models.Location.id,
            models.Location.name,
            models.Product.id,
            models.Product.name,
            models.Product.unit,
        )
        .order_by(models.Location.name, models.Product.name)
        .all()
    )

    uitgifte_results = (
        db.query(
            models.Uitgifte.product_id,
            models.Uitgifte.location_id,
            func.sum(models.Uitgifte.quantity).label("total"),
        )
        .group_by(models.Uitgifte.product_id, models.Uitgifte.location_id)
        .all()
    )
    uitgifte_map = {(r.product_id, r.location_id): r.total for r in uitgifte_results}

    inventory: dict[str, list] = {}
    for row in harvest_results:
        uitgegeven = uitgifte_map.get((row.product_id, row.location_id), 0)
        net = row.total - uitgegeven
        if row.location_name not in inventory:
            inventory[row.location_name] = []
        inventory[row.location_name].append(
            {"product": row.product_name, "unit": row.unit, "total": net}
        )

    # Detailoverzicht per locatie: individuele entries met volgnummer en houdbaarheidsdatum
    entries = (
        db.query(models.HarvestEntry)
        .join(models.Product, models.HarvestEntry.product_id == models.Product.id)
        .join(models.Location, models.HarvestEntry.location_id == models.Location.id)
        .order_by(models.Location.name, models.Product.name, models.HarvestEntry.volgnummer)
        .all()
    )

    location_entries: dict[str, list] = {}
    for entry in entries:
        loc = entry.location.name
        if loc not in location_entries:
            location_entries[loc] = []
        location_entries[loc].append(entry)

    today = datetime.date.today()
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "inventory": inventory,
            "location_entries": location_entries,
            "today_date": today,
            "bijna_verlopen_date": today + datetime.timedelta(days=30),
        },
    )


# ── Nieuwe oogst ───────────────────────────────────────────────────────────────

@app.get("/harvest/new")
async def harvest_new(
    request: Request,
    db: Session = Depends(get_db),
    success: int = 0,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    products = (
        db.query(models.Product)
        .filter(models.Product.active == True)
        .order_by(models.Product.name)
        .all()
    )
    locations = (
        db.query(models.Location)
        .filter(models.Location.active == True)
        .order_by(models.Location.name)
        .all()
    )
    today = datetime.date.today().isoformat()

    return templates.TemplateResponse(
        "harvest_new.html",
        {
            "request": request,
            "user": user,
            "products": products,
            "locations": locations,
            "today": today,
            "success": success == 1,
        },
    )


@app.post("/harvest/new")
async def harvest_new_post(
    request: Request,
    db: Session = Depends(get_db),
    product_id: int = Form(...),
    location_id: int = Form(...),
    quantity: float = Form(...),
    date: str = Form(...),
    note: str = Form(default=""),
    houdbaar_tot: str = Form(default=""),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    # Volgnummer: laatste volgnummer voor dit product + 1
    max_volgnummer = (
        db.query(func.max(models.HarvestEntry.volgnummer))
        .filter(models.HarvestEntry.product_id == product_id)
        .scalar()
    )
    volgnummer = (max_volgnummer or 0) + 1

    houdbaar_tot_date = None
    if houdbaar_tot.strip():
        try:
            houdbaar_tot_date = datetime.date.fromisoformat(houdbaar_tot.strip())
        except ValueError:
            pass

    entry = models.HarvestEntry(
        product_id=product_id,
        location_id=location_id,
        quantity=quantity,
        date=date,
        entered_by=user,
        note=note.strip() or None,
        created_at=datetime.datetime.utcnow(),
        houdbaar_tot=houdbaar_tot_date,
        volgnummer=volgnummer,
    )
    db.add(entry)
    db.commit()
    return RedirectResponse("/harvest/new?success=1", status_code=302)


# ── Geschiedenis ───────────────────────────────────────────────────────────────

@app.get("/history")
async def history(
    request: Request,
    db: Session = Depends(get_db),
    product_id: int = None,
    date_from: str = None,
    date_to: str = None,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    query = (
        db.query(models.HarvestEntry)
        .join(models.Product, models.HarvestEntry.product_id == models.Product.id)
        .join(models.Location, models.HarvestEntry.location_id == models.Location.id)
    )
    if product_id:
        query = query.filter(models.HarvestEntry.product_id == product_id)
    if date_from:
        query = query.filter(models.HarvestEntry.date >= date_from)
    if date_to:
        query = query.filter(models.HarvestEntry.date <= date_to)

    entries = query.order_by(
        models.HarvestEntry.date.desc(), models.HarvestEntry.created_at.desc()
    ).all()
    products = db.query(models.Product).order_by(models.Product.name).all()

    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "user": user,
            "entries": entries,
            "products": products,
            "filter_product_id": product_id,
            "filter_date_from": date_from or "",
            "filter_date_to": date_to or "",
        },
    )


@app.get("/history/export")
async def history_export(
    request: Request,
    db: Session = Depends(get_db),
    product_id: int = None,
    date_from: str = None,
    date_to: str = None,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    query = (
        db.query(models.HarvestEntry)
        .join(models.Product, models.HarvestEntry.product_id == models.Product.id)
        .join(models.Location, models.HarvestEntry.location_id == models.Location.id)
    )
    if product_id:
        query = query.filter(models.HarvestEntry.product_id == product_id)
    if date_from:
        query = query.filter(models.HarvestEntry.date >= date_from)
    if date_to:
        query = query.filter(models.HarvestEntry.date <= date_to)

    entries = query.order_by(
        models.HarvestEntry.date.desc(), models.HarvestEntry.created_at.desc()
    ).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        ["Datum", "Product", "Locatie", "Hoeveelheid", "Eenheid", "Ingevoerd door", "Notitie", "Aangemaakt op"]
    )
    for e in entries:
        writer.writerow([
            e.date,
            e.product.name,
            e.location.name,
            e.quantity,
            e.product.unit,
            e.entered_by,
            e.note or "",
            e.created_at.strftime("%Y-%m-%d %H:%M") if e.created_at else "",
        ])

    filename = f"oogst_export_{datetime.date.today().isoformat()}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),  # utf-8-sig voor Excel-compatibiliteit
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Bijna verlopen ─────────────────────────────────────────────────────────────

@app.get("/verlopen")
async def verlopen(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    today = datetime.date.today()
    cutoff = today + datetime.timedelta(days=30)

    entries = (
        db.query(models.HarvestEntry)
        .join(models.Product, models.HarvestEntry.product_id == models.Product.id)
        .join(models.Location, models.HarvestEntry.location_id == models.Location.id)
        .filter(models.HarvestEntry.houdbaar_tot != None)
        .filter(models.HarvestEntry.houdbaar_tot <= cutoff)
        .order_by(models.HarvestEntry.houdbaar_tot.asc())
        .all()
    )

    return templates.TemplateResponse(
        "verlopen.html",
        {
            "request": request,
            "user": user,
            "entries": entries,
            "today": today,
        },
    )


# ── Account beheer ─────────────────────────────────────────────────────────────

@app.get("/account")
async def account(request: Request, success: str = None, error: str = None):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        "account.html",
        {"request": request, "user": user, "success": success, "error": error},
    )


@app.post("/account/username")
async def account_username(
    request: Request,
    db: Session = Depends(get_db),
    new_username: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    new_username = new_username.strip()
    if not new_username:
        return RedirectResponse("/account?error=gebruikersnaam_leeg", status_code=302)

    if new_username == user:
        return RedirectResponse("/account?error=zelfde_gebruikersnaam", status_code=302)

    existing = db.query(models.User).filter(models.User.username == new_username).first()
    if existing:
        return RedirectResponse("/account?error=gebruikersnaam_bezet", status_code=302)

    db_user = db.query(models.User).filter(models.User.username == user).first()
    db_user.username = new_username
    db.commit()

    # Token ongeldig maken: uitloggen zodat gebruiker opnieuw inlogt
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("access_token")
    return response


@app.post("/account/password")
async def account_password(
    request: Request,
    db: Session = Depends(get_db),
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password2: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    db_user = db.query(models.User).filter(models.User.username == user).first()

    if not bcrypt.checkpw(current_password.encode(), db_user.hashed_password.encode()):
        return RedirectResponse("/account?error=huidig_wachtwoord_fout", status_code=302)

    if new_password != new_password2:
        return RedirectResponse("/account?error=wachtwoorden_komen_niet_overeen", status_code=302)

    if len(new_password) < 6:
        return RedirectResponse("/account?error=wachtwoord_te_kort", status_code=302)

    db_user.hashed_password = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    db.commit()
    return RedirectResponse("/account?success=wachtwoord_gewijzigd", status_code=302)


# ── Admin ──────────────────────────────────────────────────────────────────────

@app.get("/admin")
async def admin(
    request: Request,
    db: Session = Depends(get_db),
    success: str = None,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    products = db.query(models.Product).order_by(models.Product.active.desc(), models.Product.name).all()
    locations = db.query(models.Location).order_by(models.Location.active.desc(), models.Location.name).all()

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "user": user,
            "products": products,
            "locations": locations,
            "success": success,
        },
    )


@app.post("/admin/product/add")
async def admin_add_product(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    unit: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    product = models.Product(name=name.strip(), unit=unit.strip(), active=True)
    db.add(product)
    db.commit()
    return RedirectResponse("/admin?success=product_added", status_code=302)


@app.post("/admin/product/{product_id}/deactivate")
async def admin_deactivate_product(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if product:
        product.active = False
        db.commit()
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/product/{product_id}/activate")
async def admin_activate_product(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if product:
        product.active = True
        db.commit()
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/location/add")
async def admin_add_location(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    location = models.Location(name=name.strip(), active=True)
    db.add(location)
    db.commit()
    return RedirectResponse("/admin?success=location_added", status_code=302)


@app.post("/admin/location/{location_id}/deactivate")
async def admin_deactivate_location(
    location_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    location = db.query(models.Location).filter(models.Location.id == location_id).first()
    if location:
        location.active = False
        db.commit()
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/location/{location_id}/activate")
async def admin_activate_location(
    location_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    location = db.query(models.Location).filter(models.Location.id == location_id).first()
    if location:
        location.active = True
        db.commit()
    return RedirectResponse("/admin", status_code=302)


# ── Uitgifte ───────────────────────────────────────────────────────────────────

def _beschikbare_voorraad(db: Session, product_id: int, location_id: int) -> float:
    harvest_total = (
        db.query(func.sum(models.HarvestEntry.quantity))
        .filter(
            models.HarvestEntry.product_id == product_id,
            models.HarvestEntry.location_id == location_id,
        )
        .scalar()
    ) or 0.0
    uitgifte_total = (
        db.query(func.sum(models.Uitgifte.quantity))
        .filter(
            models.Uitgifte.product_id == product_id,
            models.Uitgifte.location_id == location_id,
        )
        .scalar()
    ) or 0.0
    return harvest_total - uitgifte_total


@app.get("/uitgifte/new")
async def uitgifte_new(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    products = (
        db.query(models.Product)
        .filter(models.Product.active == True)
        .order_by(models.Product.name)
        .all()
    )
    locations = (
        db.query(models.Location)
        .filter(models.Location.active == True)
        .order_by(models.Location.name)
        .all()
    )
    ontvangers = [
        r[0]
        for r in db.query(models.Uitgifte.ontvanger).distinct().order_by(models.Uitgifte.ontvanger).all()
    ]
    today = datetime.date.today().isoformat()

    return templates.TemplateResponse(
        "uitgifte_new.html",
        {
            "request": request,
            "user": user,
            "products": products,
            "locations": locations,
            "ontvangers": ontvangers,
            "today": today,
            "error": None,
            "form": {},
        },
    )


@app.post("/uitgifte/new")
async def uitgifte_new_post(
    request: Request,
    db: Session = Depends(get_db),
    product_id: int = Form(...),
    location_id: int = Form(...),
    quantity: float = Form(...),
    ontvanger: str = Form(...),
    date: str = Form(...),
    note: str = Form(default=""),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    beschikbaar = _beschikbare_voorraad(db, product_id, location_id)

    if quantity > beschikbaar:
        product = db.query(models.Product).filter(models.Product.id == product_id).first()
        unit = product.unit if product else ""
        products = (
            db.query(models.Product).filter(models.Product.active == True).order_by(models.Product.name).all()
        )
        locations = (
            db.query(models.Location).filter(models.Location.active == True).order_by(models.Location.name).all()
        )
        ontvangers = [
            r[0]
            for r in db.query(models.Uitgifte.ontvanger).distinct().order_by(models.Uitgifte.ontvanger).all()
        ]
        return templates.TemplateResponse(
            "uitgifte_new.html",
            {
                "request": request,
                "user": user,
                "products": products,
                "locations": locations,
                "ontvangers": ontvangers,
                "today": date,
                "error": f"Onvoldoende voorraad. Beschikbaar: {beschikbaar:g} {unit}",
                "form": {
                    "product_id": product_id,
                    "location_id": location_id,
                    "quantity": quantity,
                    "ontvanger": ontvanger,
                    "date": date,
                    "note": note,
                },
            },
        )

    uitgifte = models.Uitgifte(
        product_id=product_id,
        location_id=location_id,
        quantity=quantity,
        ontvanger=ontvanger.strip(),
        date=date,
        entered_by=user,
        note=note.strip() or None,
        created_at=datetime.datetime.utcnow(),
    )
    db.add(uitgifte)
    db.commit()
    return RedirectResponse("/", status_code=302)


@app.get("/uitgiftes")
async def uitgiftes(
    request: Request,
    db: Session = Depends(get_db),
    ontvanger: str = None,
    date_from: str = None,
    date_to: str = None,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    query = (
        db.query(models.Uitgifte)
        .join(models.Product, models.Uitgifte.product_id == models.Product.id)
        .join(models.Location, models.Uitgifte.location_id == models.Location.id)
    )
    if ontvanger:
        query = query.filter(models.Uitgifte.ontvanger == ontvanger)
    if date_from:
        query = query.filter(models.Uitgifte.date >= date_from)
    if date_to:
        query = query.filter(models.Uitgifte.date <= date_to)

    entries = query.order_by(models.Uitgifte.date.desc(), models.Uitgifte.created_at.desc()).all()

    # Totaal per ontvanger per product
    totaal_query = (
        db.query(
            models.Uitgifte.ontvanger,
            models.Product.name.label("product_name"),
            models.Product.unit.label("unit"),
            func.sum(models.Uitgifte.quantity).label("total"),
        )
        .join(models.Product, models.Uitgifte.product_id == models.Product.id)
        .group_by(models.Uitgifte.ontvanger, models.Product.id, models.Product.name, models.Product.unit)
        .order_by(models.Uitgifte.ontvanger, models.Product.name)
    )
    if ontvanger:
        totaal_query = totaal_query.filter(models.Uitgifte.ontvanger == ontvanger)
    if date_from:
        totaal_query = totaal_query.filter(models.Uitgifte.date >= date_from)
    if date_to:
        totaal_query = totaal_query.filter(models.Uitgifte.date <= date_to)

    totaal_rows = totaal_query.all()
    totaal_per_ontvanger: dict[str, list] = {}
    for r in totaal_rows:
        if r.ontvanger not in totaal_per_ontvanger:
            totaal_per_ontvanger[r.ontvanger] = []
        totaal_per_ontvanger[r.ontvanger].append(
            {"product": r.product_name, "unit": r.unit, "total": r.total}
        )

    alle_ontvangers = [
        r[0]
        for r in db.query(models.Uitgifte.ontvanger).distinct().order_by(models.Uitgifte.ontvanger).all()
    ]

    return templates.TemplateResponse(
        "uitgiftes.html",
        {
            "request": request,
            "user": user,
            "entries": entries,
            "totaal_per_ontvanger": totaal_per_ontvanger,
            "alle_ontvangers": alle_ontvangers,
            "filter_ontvanger": ontvanger or "",
            "filter_date_from": date_from or "",
            "filter_date_to": date_to or "",
        },
    )


@app.get("/uitgiftes/export")
async def uitgiftes_export(
    request: Request,
    db: Session = Depends(get_db),
    ontvanger: str = None,
    date_from: str = None,
    date_to: str = None,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    query = (
        db.query(models.Uitgifte)
        .join(models.Product, models.Uitgifte.product_id == models.Product.id)
        .join(models.Location, models.Uitgifte.location_id == models.Location.id)
    )
    if ontvanger:
        query = query.filter(models.Uitgifte.ontvanger == ontvanger)
    if date_from:
        query = query.filter(models.Uitgifte.date >= date_from)
    if date_to:
        query = query.filter(models.Uitgifte.date <= date_to)

    entries = query.order_by(models.Uitgifte.date.desc(), models.Uitgifte.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Datum", "Product", "Locatie", "Hoeveelheid", "Eenheid", "Ontvanger", "Ingevoerd door", "Notitie"])
    for e in entries:
        writer.writerow([
            e.date,
            e.product.name,
            e.location.name,
            e.quantity,
            e.product.unit,
            e.ontvanger,
            e.entered_by,
            e.note or "",
        ])

    filename = f"uitgifte_export_{datetime.date.today().isoformat()}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
