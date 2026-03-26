import io
import csv
import datetime
import logging
import secrets
import smtplib
from urllib.parse import quote
from datetime import timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests as http_requests

import bcrypt
from typing import Optional
from fastapi import FastAPI, Request, Depends, Form
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

import models
import database
from database import get_db
from auth import get_current_user, authenticate_user, create_access_token
from config import ACCESS_TOKEN_EXPIRE_MINUTES, USERS, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, APP_URL

# Maak database tabellen aan
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals["now"] = datetime.datetime.now()


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
            if "gewijzigd_door" not in col_names:
                conn.execute(text("ALTER TABLE harvest_entries ADD COLUMN gewijzigd_door TEXT"))
            if "gewijzigd_op" not in col_names:
                conn.execute(text("ALTER TABLE harvest_entries ADD COLUMN gewijzigd_op DATETIME"))
            if "uitgegeven" not in col_names:
                conn.execute(text("ALTER TABLE harvest_entries ADD COLUMN uitgegeven BOOLEAN DEFAULT 0"))
            if "uitgegeven_op" not in col_names:
                conn.execute(text("ALTER TABLE harvest_entries ADD COLUMN uitgegeven_op DATETIME"))
            if "uitgegeven_aan" not in col_names:
                conn.execute(text("ALTER TABLE harvest_entries ADD COLUMN uitgegeven_aan TEXT"))
            if "conserveringsmethode_id" not in col_names:
                conn.execute(text("ALTER TABLE harvest_entries ADD COLUMN conserveringsmethode_id INTEGER REFERENCES conserveringsmethoden(id)"))
            conn.commit()
        except Exception:
            pass  # Tabel bestaat nog niet; create_all regelt dit

        # Migreer users tabel: voeg email kolom toe indien nog niet aanwezig
        try:
            pragma_users = conn.execute(text("PRAGMA table_info(users)")).fetchall()
            user_col_names = [row[1] for row in pragma_users]
            if "email" not in user_col_names:
                conn.execute(text("ALTER TABLE users ADD COLUMN email TEXT"))
            conn.commit()
        except Exception:
            pass

        # Migreer uitgiftes tabel (aangemaakt via create_all, maar voor zekerheid)
        try:
            conn.execute(text("SELECT 1 FROM uitgiftes LIMIT 1"))
        except Exception:
            pass  # Wordt aangemaakt door create_all

        # Ontvangers tabel wordt aangemaakt door create_all; geen extra migratie nodig

        # Maak shop_items tabel aan
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS shop_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    barcode TEXT,
                    name TEXT NOT NULL,
                    brand TEXT,
                    quantity_per_unit REAL DEFAULT 1,
                    unit TEXT DEFAULT 'stuks',
                    image_url TEXT,
                    owner TEXT NOT NULL,
                    stock INTEGER DEFAULT 0,
                    houdbaar_tot DATE,
                    date_added DATE,
                    entered_by TEXT NOT NULL
                )
            """))
            conn.commit()
        except Exception:
            pass

        # Maak shop_uitgiftes tabel aan
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS shop_uitgiftes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shop_item_id INTEGER NOT NULL REFERENCES shop_items(id),
                    quantity INTEGER NOT NULL,
                    date DATE,
                    entered_by TEXT NOT NULL
                )
            """))
            conn.commit()
        except Exception:
            pass

        # Maak product_cache tabel aan
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS product_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    barcode TEXT NOT NULL UNIQUE,
                    name TEXT,
                    brand TEXT,
                    quantity REAL,
                    unit TEXT,
                    image_url TEXT,
                    cached_at DATETIME
                )
            """))
            conn.commit()
        except Exception:
            pass

        # Migreer products tabel: voeg eenheid_id kolom toe indien nog niet aanwezig
        try:
            pragma_products = conn.execute(text("PRAGMA table_info(products)")).fetchall()
            product_col_names = [row[1] for row in pragma_products]
            if "eenheid_id" not in product_col_names:
                conn.execute(text("ALTER TABLE products ADD COLUMN eenheid_id INTEGER REFERENCES eenheden(id)"))
            conn.commit()
        except Exception:
            pass

        # Maak product_houdbaarheid tabel aan / migreer naar conserveringsmethode
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS product_houdbaarheid (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL REFERENCES products(id),
                    conserveringsmethode_id INTEGER REFERENCES conserveringsmethoden(id),
                    houdbaarheid_maanden INTEGER NOT NULL,
                    actief BOOLEAN NOT NULL DEFAULT 1
                )
            """))
            conn.commit()
        except Exception:
            pass

        # Voeg conserveringsmethode_id toe aan bestaande product_houdbaarheid indien ontbreekt
        try:
            pragma_ph = conn.execute(text("PRAGMA table_info(product_houdbaarheid)")).fetchall()
            ph_col_names = [row[1] for row in pragma_ph]
            if "conserveringsmethode_id" not in ph_col_names:
                conn.execute(text("ALTER TABLE product_houdbaarheid ADD COLUMN conserveringsmethode_id INTEGER REFERENCES conserveringsmethoden(id)"))
            conn.commit()
        except Exception:
            pass

        # Verwijder locatie_id uit product_houdbaarheid (SQLite: tabel herbouwen)
        try:
            pragma_ph2 = conn.execute(text("PRAGMA table_info(product_houdbaarheid)")).fetchall()
            ph_col_names2 = [row[1] for row in pragma_ph2]
            if "locatie_id" in ph_col_names2:
                conn.execute(text("""
                    CREATE TABLE product_houdbaarheid_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_id INTEGER NOT NULL REFERENCES products(id),
                        conserveringsmethode_id INTEGER REFERENCES conserveringsmethoden(id),
                        houdbaarheid_maanden INTEGER NOT NULL,
                        actief BOOLEAN NOT NULL DEFAULT 1
                    )
                """))
                conn.execute(text("""
                    INSERT INTO product_houdbaarheid_new
                        (id, product_id, conserveringsmethode_id, houdbaarheid_maanden, actief)
                    SELECT id, product_id, conserveringsmethode_id, houdbaarheid_maanden, actief
                    FROM product_houdbaarheid
                """))
                conn.execute(text("DROP TABLE product_houdbaarheid"))
                conn.execute(text("ALTER TABLE product_houdbaarheid_new RENAME TO product_houdbaarheid"))
                conn.commit()
        except Exception as e:
            print(f"Migratie product_houdbaarheid: {e}")

    # Standaard conserveringsmethoden aanmaken als de tabel leeg is
    db = database.SessionLocal()
    try:
        if db.query(models.Conserveringsmethode).count() == 0:
            standaard_methoden = [
                "Invriezen", "Inmaken in zuur", "Fermenteren", "Drogen",
                "Inmaken in olie", "Konfijten", "Vacuümverpakken",
                "Koud bewaren", "Op kamertemperatuur",
            ]
            for naam in standaard_methoden:
                db.add(models.Conserveringsmethode(naam=naam, actief=True))
            db.commit()
    finally:
        db.close()

    # Standaard eenheden aanmaken als de tabel leeg is
    db = database.SessionLocal()
    try:
        if db.query(models.Eenheid).count() == 0:
            standaard_eenheden = [
                models.Eenheid(naam="kg", etiket_per_stuk=False, actief=True),
                models.Eenheid(naam="gram", etiket_per_stuk=False, actief=True),
                models.Eenheid(naam="liter", etiket_per_stuk=False, actief=True),
                models.Eenheid(naam="stuks", etiket_per_stuk=True, actief=True),
                models.Eenheid(naam="pot", etiket_per_stuk=True, actief=True),
                models.Eenheid(naam="krat", etiket_per_stuk=True, actief=True),
                models.Eenheid(naam="bundel", etiket_per_stuk=True, actief=True),
            ]
            for e in standaard_eenheden:
                db.add(e)
            db.commit()

        # Migreer bestaande producten: koppel unit string aan eenheid
        producten_zonder_eenheid = db.query(models.Product).filter(models.Product.eenheid_id == None).all()
        for product in producten_zonder_eenheid:
            if product.unit:
                eenheid = db.query(models.Eenheid).filter(
                    models.Eenheid.naam == product.unit
                ).first()
                if not eenheid:
                    # Maak een nieuwe eenheid aan voor onbekende unit strings
                    eenheid = models.Eenheid(naam=product.unit, etiket_per_stuk=False, actief=True)
                    db.add(eenheid)
                    db.flush()
                product.eenheid_id = eenheid.id
        db.commit()
    finally:
        db.close()

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

    # Zorg dat Hinke en Maarten als ontvangers bestaan
    db = database.SessionLocal()
    try:
        for naam in ["Hinke", "Maarten"]:
            bestaand = db.query(models.Ontvanger).filter(
                func.lower(models.Ontvanger.naam) == naam.lower()
            ).first()
            if not bestaand:
                db.add(models.Ontvanger(naam=naam, actief=True))
        db.commit()
    finally:
        db.close()


# ── Authenticatie ──────────────────────────────────────────────────────────────

@app.get("/login")
async def login_page(request: Request, next: str = "/"):
    user = get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None, "next": next})


@app.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/"),
):
    user = authenticate_user(username, password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Ongeldige gebruikersnaam of wachtwoord", "next": next},
        )
    token = create_access_token(
        {"sub": username}, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    # Veiligheidscheck: alleen interne redirects toestaan
    redirect_to = next if (next and next.startswith("/")) else "/"
    response = RedirectResponse(redirect_to, status_code=302)
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

    # Detailoverzicht per locatie: individuele entries met volgnummer en houdbaarheidsdatum (alleen niet-uitgegeven)
    entries = (
        db.query(models.HarvestEntry)
        .join(models.Product, models.HarvestEntry.product_id == models.Product.id)
        .join(models.Location, models.HarvestEntry.location_id == models.Location.id)
        .filter(models.HarvestEntry.uitgegeven == False)
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

    # Stats voor dashboard kaartjes
    week_start = str(today - datetime.timedelta(days=today.weekday()))
    registraties_week = db.query(func.count(models.HarvestEntry.id)).filter(
        models.HarvestEntry.date >= week_start
    ).scalar() or 0
    uitgiftes_week = db.query(func.count(models.Uitgifte.id)).filter(
        models.Uitgifte.date >= week_start
    ).scalar() or 0
    total_producten = sum(1 for items in inventory.values() for item in items if item["total"] > 0)
    total_locaties = len([loc for loc, items in inventory.items() if any(item["total"] > 0 for item in items)])

    producten_in_voorraad = db.query(func.count(models.HarvestEntry.id)).filter(
        models.HarvestEntry.uitgegeven == False
    ).scalar() or 0

    bijna_verlopen_cutoff = today + datetime.timedelta(days=30)
    kort_houdbaar_count = db.query(func.count(models.HarvestEntry.id)).filter(
        models.HarvestEntry.uitgegeven == False,
        models.HarvestEntry.houdbaar_tot != None,
        models.HarvestEntry.houdbaar_tot <= bijna_verlopen_cutoff,
    ).scalar() or 0

    # Urgent: verlopen binnen 3 dagen
    drie_dagen = today + datetime.timedelta(days=3)
    urgent_items = (
        db.query(models.HarvestEntry)
        .join(models.Product, models.HarvestEntry.product_id == models.Product.id)
        .filter(
            models.HarvestEntry.uitgegeven == False,
            models.HarvestEntry.houdbaar_tot != None,
            models.HarvestEntry.houdbaar_tot >= today,
            models.HarvestEntry.houdbaar_tot <= drie_dagen,
        )
        .order_by(models.HarvestEntry.houdbaar_tot.asc())
        .all()
    )

    # Bijna verlopen binnen 7 dagen
    zeven_dagen = today + datetime.timedelta(days=7)
    bijna_verlopen_7d = (
        db.query(models.HarvestEntry)
        .join(models.Product, models.HarvestEntry.product_id == models.Product.id)
        .join(models.Location, models.HarvestEntry.location_id == models.Location.id)
        .filter(
            models.HarvestEntry.uitgegeven == False,
            models.HarvestEntry.houdbaar_tot != None,
            models.HarvestEntry.houdbaar_tot >= today,
            models.HarvestEntry.houdbaar_tot <= zeven_dagen,
        )
        .order_by(models.HarvestEntry.houdbaar_tot.asc())
        .all()
    )

    # Totaaloverzicht voorraad: groepeer per product per conserveringsmethode
    voorraad_totaal_rows = (
        db.query(
            models.Product.name.label("product_naam"),
            models.Conserveringsmethode.naam.label("conserveringsmethode_naam"),
            func.sum(models.HarvestEntry.quantity).label("totaal"),
            models.Product.unit.label("unit"),
            models.Eenheid.naam.label("eenheid_naam"),
        )
        .select_from(models.HarvestEntry)
        .join(models.Product, models.HarvestEntry.product_id == models.Product.id)
        .outerjoin(models.Conserveringsmethode, models.HarvestEntry.conserveringsmethode_id == models.Conserveringsmethode.id)
        .outerjoin(models.Eenheid, models.Product.eenheid_id == models.Eenheid.id)
        .filter(models.HarvestEntry.uitgegeven == False)
        .group_by(
            models.Product.id,
            models.Product.name,
            models.Product.unit,
            models.Eenheid.naam,
            models.HarvestEntry.conserveringsmethode_id,
            models.Conserveringsmethode.naam,
        )
        .order_by(models.Product.name, models.Conserveringsmethode.naam)
        .all()
    )
    voorraad_totaal = [
        {
            "product": r.product_naam,
            "conserveringsmethode": r.conserveringsmethode_naam or "Niet opgegeven",
            "totaal": r.totaal,
            "eenheid": r.eenheid_naam or r.unit or "",
        }
        for r in voorraad_totaal_rows
        if r.totaal and r.totaal > 0
    ]

    # Top 5 winkelproducten die binnenkort verlopen (eigen voorraad)
    shop_cutoff = today + datetime.timedelta(days=30)
    shop_bijna_verlopen = (
        db.query(models.ShopItem)
        .filter(
            models.ShopItem.owner == user,
            models.ShopItem.stock > 0,
            models.ShopItem.houdbaar_tot != None,
            models.ShopItem.houdbaar_tot <= shop_cutoff,
        )
        .order_by(models.ShopItem.houdbaar_tot.asc())
        .limit(5)
        .all()
    )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "inventory": inventory,
            "location_entries": location_entries,
            "today_date": today,
            "bijna_verlopen_date": bijna_verlopen_cutoff,
            "bijna_verlopen_7d": bijna_verlopen_7d,
            "urgent_items": urgent_items,
            "voorraad_totaal": voorraad_totaal,
            "shop_bijna_verlopen": shop_bijna_verlopen,
            "stats": {
                "total_producten": total_producten,
                "total_locaties": total_locaties,
                "registraties_week": registraties_week,
                "uitgiftes_week": uitgiftes_week,
                "producten_in_voorraad": producten_in_voorraad,
                "kort_houdbaar_count": kort_houdbaar_count,
            },
        },
    )


# ── Zoeken ─────────────────────────────────────────────────────────────────────

@app.get("/zoek")
async def zoek(request: Request, db: Session = Depends(get_db), q: str = "", format: str = "html"):
    user = get_current_user(request)
    if not user:
        if format == "json":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return RedirectResponse("/login", status_code=302)

    today = datetime.date.today()
    cutoff = today + datetime.timedelta(days=30)

    entries = []
    if q and len(q) >= 2:
        from sqlalchemy import func as sqlfunc
        entries = (
            db.query(models.HarvestEntry)
            .join(models.Product, models.HarvestEntry.product_id == models.Product.id)
            .join(models.Location, models.HarvestEntry.location_id == models.Location.id)
            .filter(models.HarvestEntry.uitgegeven == False)
            .filter(sqlfunc.lower(models.Product.name).contains(q.lower()))
            .order_by(
                (models.HarvestEntry.houdbaar_tot == None).asc(),
                models.HarvestEntry.houdbaar_tot.asc(),
            )
            .all()
        )

    if format == "json":
        results = []
        for e in entries:
            eenheid = e.product.eenheid.naam if e.product.eenheid else (e.product.unit or "")
            results.append({
                "id": e.id,
                "volgnummer": e.volgnummer,
                "product": e.product.name,
                "locatie": e.location.name,
                "quantity": e.quantity,
                "eenheid": eenheid,
                "houdbaar_tot": e.houdbaar_tot.isoformat() if e.houdbaar_tot else None,
                "houdbaar_tot_display": e.houdbaar_tot.strftime("%d-%m-%Y") if e.houdbaar_tot else None,
                "kort_houdbaar": bool(e.houdbaar_tot and e.houdbaar_tot <= cutoff),
            })
        return JSONResponse({"results": results, "q": q, "count": len(results)})

    return templates.TemplateResponse(
        "zoek.html",
        {
            "request": request,
            "user": user,
            "entries": entries,
            "q": q,
            "today": today,
            "cutoff": cutoff,
        },
    )


@app.get("/zoek/suggesties")
async def zoek_suggesties(request: Request, db: Session = Depends(get_db), q: str = ""):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not q or len(q) < 2:
        return JSONResponse({"suggesties": []})
    producten = (
        db.query(models.Product.name)
        .filter(models.Product.active == True)
        .filter(func.lower(models.Product.name).contains(q.lower()))
        .order_by(models.Product.name)
        .limit(8)
        .all()
    )
    return JSONResponse({"suggesties": [p.name for p in producten]})


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
    eenheden = (
        db.query(models.Eenheid)
        .filter(models.Eenheid.actief == True)
        .order_by(models.Eenheid.naam)
        .all()
    )
    conserveringsmethoden = (
        db.query(models.Conserveringsmethode)
        .filter(models.Conserveringsmethode.actief == True)
        .order_by(models.Conserveringsmethode.naam)
        .all()
    )
    today = datetime.date.today().isoformat()

    # Bouw een dict product_id -> eenheid naam voor JavaScript
    import json
    product_eenheden = {
        str(p.id): (p.eenheid.naam if p.eenheid else p.unit or "")
        for p in products
    }
    product_etiket_per_stuk = {
        str(p.id): bool(p.eenheid and p.eenheid.etiket_per_stuk)
        for p in products
    }

    return templates.TemplateResponse(
        "harvest_new.html",
        {
            "request": request,
            "user": user,
            "products": products,
            "locations": locations,
            "conserveringsmethoden": conserveringsmethoden,
            "eenheden": eenheden,
            "today": today,
            "success": success == 1,
            "product_eenheden_json": json.dumps(product_eenheden),
            "product_etiket_per_stuk_json": json.dumps(product_etiket_per_stuk),
        },
    )


@app.post("/harvest/new")
async def harvest_new_post(
    request: Request,
    db: Session = Depends(get_db),
    product_id: int = Form(...),
    location_id: int = Form(...),
    conserveringsmethode_id: Optional[int] = Form(default=None),
    quantity: Optional[float] = Form(None),
    date: str = Form(...),
    note: str = Form(default=""),
    houdbaar_tot: str = Form(default=""),
    aantal_stuks: int = Form(default=1),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    houdbaar_tot_date = None
    if houdbaar_tot.strip():
        try:
            houdbaar_tot_date = datetime.date.fromisoformat(houdbaar_tot.strip())
        except ValueError:
            pass

    # Controleer of het product etiket_per_stuk heeft
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    is_etiket_per_stuk = bool(product and product.eenheid and product.eenheid.etiket_per_stuk)

    # Volgnummer startpunt: laatste volgnummer voor dit product
    max_volgnummer = (
        db.query(func.max(models.HarvestEntry.volgnummer))
        .filter(models.HarvestEntry.product_id == product_id)
        .scalar()
    )
    basis_volgnummer = (max_volgnummer or 0) + 1

    if is_etiket_per_stuk and aantal_stuks > 1:
        # Maak N aparte entries aan, elk met quantity=1
        entries = []
        for i in range(aantal_stuks):
            entry = models.HarvestEntry(
                product_id=product_id,
                location_id=location_id,
                conserveringsmethode_id=conserveringsmethode_id or None,
                quantity=1.0,
                date=date,
                entered_by=user,
                note=note.strip() or None,
                created_at=datetime.datetime.utcnow(),
                houdbaar_tot=houdbaar_tot_date,
                volgnummer=basis_volgnummer + i,
            )
            db.add(entry)
            entries.append(entry)
        db.commit()
        for e in entries:
            db.refresh(e)
        ids = ",".join(str(e.id) for e in entries)
        return RedirectResponse(f"/harvest/confirm-batch?ids={ids}", status_code=302)
    else:
        # Maak 1 entry aan zoals voorheen
        # Bij etiket_per_stuk met 1 stuk: quantity=1 als er geen waarde is
        effective_quantity = quantity if quantity is not None else (1.0 if is_etiket_per_stuk else None)
        entry = models.HarvestEntry(
            product_id=product_id,
            location_id=location_id,
            conserveringsmethode_id=conserveringsmethode_id or None,
            quantity=effective_quantity,
            date=date,
            entered_by=user,
            note=note.strip() or None,
            created_at=datetime.datetime.utcnow(),
            houdbaar_tot=houdbaar_tot_date,
            volgnummer=basis_volgnummer,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return RedirectResponse(f"/harvest/confirm/{entry.id}", status_code=302)


# ── Snel product toevoegen (AJAX) ──────────────────────────────────────────────

@app.post("/product/snel-toevoegen")
async def product_snel_toevoegen(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"detail": "Niet ingelogd"}, status_code=401)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"detail": "Ongeldige invoer"}, status_code=400)

    naam = (data.get("naam") or "").strip()
    eenheid_id = data.get("eenheid_id")

    if not naam:
        return JSONResponse({"detail": "Productnaam mag niet leeg zijn"}, status_code=400)
    if not eenheid_id:
        return JSONResponse({"detail": "Eenheid is verplicht"}, status_code=400)

    eenheid = db.query(models.Eenheid).filter(models.Eenheid.id == eenheid_id).first()
    if not eenheid:
        return JSONResponse({"detail": "Eenheid niet gevonden"}, status_code=400)

    product = models.Product(
        name=naam,
        unit=eenheid.naam,
        eenheid_id=eenheid.id,
        active=True,
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    return JSONResponse({
        "id": product.id,
        "naam": product.name,
        "eenheid_id": eenheid.id,
        "eenheid_naam": eenheid.naam,
        "etiket_per_stuk": eenheid.etiket_per_stuk,
    })


# ── Bevestiging na opslaan oogst ───────────────────────────────────────────────

@app.get("/harvest/confirm/{entry_id}")
async def harvest_confirm(entry_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    entry = db.query(models.HarvestEntry).filter(models.HarvestEntry.id == entry_id).first()
    if not entry:
        return RedirectResponse("/", status_code=302)

    today = datetime.date.today()
    qr_url = f"https://mountainsense.nl/scan/{entry.id}"

    return templates.TemplateResponse(
        "harvest_confirm.html",
        {
            "request": request,
            "user": user,
            "entry": entry,
            "today": today,
            "qr_url": qr_url,
        },
    )


@app.get("/harvest/confirm-batch")
async def harvest_confirm_batch(request: Request, ids: str = "", db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    try:
        id_list = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        return RedirectResponse("/", status_code=302)

    entries = (
        db.query(models.HarvestEntry)
        .filter(models.HarvestEntry.id.in_(id_list))
        .order_by(models.HarvestEntry.volgnummer)
        .all()
    )
    if not entries:
        return RedirectResponse("/", status_code=302)

    today = datetime.date.today()
    entries_data = [
        {
            "entry": e,
            "qr_url": f"https://mountainsense.nl/scan/{e.id}",
        }
        for e in entries
    ]

    return templates.TemplateResponse(
        "harvest_confirm_batch.html",
        {
            "request": request,
            "user": user,
            "entries_data": entries_data,
            "today": today,
            "eerste_entry": entries[0],
        },
    )


# ── Label herdruk ──────────────────────────────────────────────────────────────

@app.get("/harvest/label/{entry_id}")
async def harvest_label(entry_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(f"/login?next=/harvest/label/{entry_id}", status_code=302)

    entry = db.query(models.HarvestEntry).filter(models.HarvestEntry.id == entry_id).first()
    if not entry:
        return RedirectResponse("/beheer/geschiedenis", status_code=302)

    today = datetime.date.today()
    qr_url = f"https://mountainsense.nl/scan/{entry.id}"

    return templates.TemplateResponse(
        "harvest_label.html",
        {
            "request": request,
            "user": user,
            "entry": entry,
            "today": today,
            "qr_url": qr_url,
        },
    )


# ── Oogst bewerken ─────────────────────────────────────────────────────────────

@app.get("/harvest/edit/{entry_id}")
async def harvest_edit(entry_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    entry = db.query(models.HarvestEntry).filter(models.HarvestEntry.id == entry_id).first()
    if not entry:
        return RedirectResponse("/beheer/geschiedenis", status_code=302)

    products = db.query(models.Product).order_by(models.Product.name).all()
    locations = db.query(models.Location).order_by(models.Location.name).all()

    return templates.TemplateResponse(
        "harvest_edit.html",
        {
            "request": request,
            "user": user,
            "entry": entry,
            "products": products,
            "locations": locations,
        },
    )


@app.post("/harvest/edit/{entry_id}")
async def harvest_edit_post(
    entry_id: int,
    request: Request,
    db: Session = Depends(get_db),
    product_id: int = Form(...),
    location_id: int = Form(...),
    quantity: float = Form(...),
    date: str = Form(...),
    houdbaar_tot: str = Form(default=""),
    note: str = Form(default=""),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    entry = db.query(models.HarvestEntry).filter(models.HarvestEntry.id == entry_id).first()
    if not entry:
        return RedirectResponse("/beheer/geschiedenis", status_code=302)

    houdbaar_tot_date = None
    if houdbaar_tot.strip():
        try:
            houdbaar_tot_date = datetime.date.fromisoformat(houdbaar_tot.strip())
        except ValueError:
            pass

    entry.product_id = product_id
    entry.location_id = location_id
    entry.quantity = quantity
    entry.date = date
    entry.houdbaar_tot = houdbaar_tot_date
    entry.note = note.strip() or None
    entry.gewijzigd_door = user
    entry.gewijzigd_op = datetime.datetime.utcnow()

    db.commit()
    return RedirectResponse("/beheer/geschiedenis", status_code=302)


@app.post("/harvest/delete/{entry_id}")
async def harvest_delete(entry_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    entry = db.query(models.HarvestEntry).filter(models.HarvestEntry.id == entry_id).first()
    if not entry:
        return RedirectResponse("/beheer/geschiedenis", status_code=302)

    # Blokkeer verwijderen als er uitgiftes aan gekoppeld zijn
    gekoppeld = db.query(models.Uitgifte).filter(models.Uitgifte.harvest_entry_id == entry_id).first()
    if gekoppeld:
        return RedirectResponse(
            f"/harvest/edit/{entry_id}?error=heeft_uitgiftes", status_code=302
        )

    db.delete(entry)
    db.commit()
    return RedirectResponse("/beheer/geschiedenis", status_code=302)


# ── Geschiedenis (redirect naar nieuw gecombineerd overzicht) ──────────────────

@app.get("/history")
async def history_redirect(request: Request):
    return RedirectResponse("/beheer/geschiedenis", status_code=301)


@app.get("/history_legacy_unused")
async def history_legacy(
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
async def history_export_redirect(request: Request):
    return RedirectResponse("/beheer/geschiedenis/export/registraties", status_code=301)


@app.get("/history/export_legacy_unused")
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
        .filter(models.HarvestEntry.uitgegeven == False)
        .order_by(models.HarvestEntry.houdbaar_tot.asc())
        .all()
    )

    # Winkelproducten bijna verlopen
    shop_entries = (
        db.query(models.ShopItem)
        .filter(
            models.ShopItem.owner == user,
            models.ShopItem.stock > 0,
            models.ShopItem.houdbaar_tot != None,
            models.ShopItem.houdbaar_tot <= cutoff,
        )
        .order_by(models.ShopItem.houdbaar_tot.asc())
        .all()
    )

    return templates.TemplateResponse(
        "verlopen.html",
        {
            "request": request,
            "user": user,
            "entries": entries,
            "shop_entries": shop_entries,
            "today": today,
        },
    )


# ── Account beheer ─────────────────────────────────────────────────────────────

@app.get("/account")
async def account(request: Request, db: Session = Depends(get_db), success: str = None, error: str = None):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    db_user = db.query(models.User).filter(models.User.username == user).first()
    return templates.TemplateResponse(
        "account.html",
        {
            "request": request,
            "user": user,
            "success": success,
            "error": error,
            "current_user_email": db_user.email if db_user else None,
        },
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


@app.post("/account/email")
async def account_email(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(default=""),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    email = email.strip().lower()

    if email:
        import re
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            return RedirectResponse("/account?error=email_ongeldig", status_code=302)
        bestaand = db.query(models.User).filter(
            models.User.email == email,
            models.User.username != user,
        ).first()
        if bestaand:
            return RedirectResponse("/account?error=email_bezet", status_code=302)

    db_user = db.query(models.User).filter(models.User.username == user).first()
    db_user.email = email if email else None
    db.commit()
    return RedirectResponse("/account?success=email_gewijzigd", status_code=302)


# ── Wachtwoord vergeten ────────────────────────────────────────────────────────

def _stuur_reset_email(to_email: str, reset_url: str):
    """Stuur wachtwoord-reset email via SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Wachtwoord resetten - Boerderij Voorraad"
    msg["From"] = SMTP_FROM
    msg["To"] = to_email

    tekst = f"""Hallo,

Je hebt een verzoek ingediend om je wachtwoord te resetten voor Boerderij Voorraad.

Klik op de onderstaande link om een nieuw wachtwoord in te stellen:
{reset_url}

Deze link is 1 uur geldig.

Als je dit verzoek niet hebt ingediend, kun je deze e-mail negeren.

Met vriendelijke groet,
Boerderij Voorraad
"""
    msg.attach(MIMEText(tekst, "plain", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        if SMTP_USER and SMTP_PASSWORD:
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM, to_email, msg.as_string())


@app.get("/wachtwoord-vergeten")
async def wachtwoord_vergeten(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(
        "wachtwoord_vergeten.html",
        {"request": request, "verzonden": False},
    )


@app.post("/wachtwoord-vergeten")
async def wachtwoord_vergeten_post(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
):
    # Toon altijd neutrale melding (ook als email niet bestaat)
    email = email.strip().lower()
    db_user = db.query(models.User).filter(models.User.email == email).first()
    if db_user and SMTP_HOST:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        reset_token = models.PasswordResetToken(
            user_id=db_user.id,
            token=token,
            expires_at=expires_at,
            used=False,
        )
        db.add(reset_token)
        db.commit()
        reset_url = f"{APP_URL}/wachtwoord-reset/{token}"
        try:
            _stuur_reset_email(email, reset_url)
        except Exception as e:
            logging.error(f"SMTP fout: {e}")

    return templates.TemplateResponse(
        "wachtwoord_vergeten.html",
        {"request": request, "verzonden": True},
    )


@app.get("/wachtwoord-reset/{token}")
async def wachtwoord_reset(token: str, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=302)

    reset_token = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.token == token,
        models.PasswordResetToken.used == False,
        models.PasswordResetToken.expires_at > datetime.datetime.utcnow(),
    ).first()

    if not reset_token:
        return templates.TemplateResponse(
            "wachtwoord_reset.html",
            {"request": request, "token": token, "ongeldig": True, "error": None},
        )

    return templates.TemplateResponse(
        "wachtwoord_reset.html",
        {"request": request, "token": token, "ongeldig": False, "error": None},
    )


@app.post("/wachtwoord-reset/{token}")
async def wachtwoord_reset_post(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
    nieuw_wachtwoord: str = Form(...),
    nieuw_wachtwoord2: str = Form(...),
):
    reset_token = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.token == token,
        models.PasswordResetToken.used == False,
        models.PasswordResetToken.expires_at > datetime.datetime.utcnow(),
    ).first()

    if not reset_token:
        return templates.TemplateResponse(
            "wachtwoord_reset.html",
            {"request": request, "token": token, "ongeldig": True, "error": None},
        )

    if nieuw_wachtwoord != nieuw_wachtwoord2:
        return templates.TemplateResponse(
            "wachtwoord_reset.html",
            {"request": request, "token": token, "ongeldig": False, "error": "wachtwoorden_komen_niet_overeen"},
        )

    if len(nieuw_wachtwoord) < 6:
        return templates.TemplateResponse(
            "wachtwoord_reset.html",
            {"request": request, "token": token, "ongeldig": False, "error": "wachtwoord_te_kort"},
        )

    db_user = db.query(models.User).filter(models.User.id == reset_token.user_id).first()
    db_user.hashed_password = bcrypt.hashpw(nieuw_wachtwoord.encode(), bcrypt.gensalt()).decode()
    reset_token.used = True
    db.commit()

    response = RedirectResponse("/login?success=wachtwoord_gereset", status_code=302)
    return response


# ── Admin ──────────────────────────────────────────────────────────────────────

@app.get("/admin")
async def admin(request: Request):
    return RedirectResponse("/beheer/producten", status_code=302)


@app.post("/admin/product/add")
async def admin_add_product(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    eenheid_id: int = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    eenheid = db.query(models.Eenheid).filter(models.Eenheid.id == eenheid_id).first()
    unit_naam = eenheid.naam if eenheid else ""
    product = models.Product(name=name.strip(), unit=unit_naam, eenheid_id=eenheid_id, active=True)
    db.add(product)
    db.commit()
    return RedirectResponse("/beheer/producten?success=product_added", status_code=302)


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
    return RedirectResponse("/beheer/producten", status_code=302)


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
    return RedirectResponse("/beheer/producten", status_code=302)


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
    return RedirectResponse("/beheer/locaties?success=location_added", status_code=302)


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
    return RedirectResponse("/beheer/locaties", status_code=302)


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
    return RedirectResponse("/beheer/locaties", status_code=302)


@app.post("/admin/ontvanger/add")
async def admin_add_ontvanger(
    request: Request,
    db: Session = Depends(get_db),
    naam: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    ontvanger = models.Ontvanger(naam=naam.strip(), actief=True)
    db.add(ontvanger)
    db.commit()
    return RedirectResponse("/beheer/personen?success=persoon_added", status_code=302)


@app.post("/admin/ontvanger/{ontvanger_id}/deactivate")
async def admin_deactivate_ontvanger(
    ontvanger_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    ontvanger = db.query(models.Ontvanger).filter(models.Ontvanger.id == ontvanger_id).first()
    if ontvanger:
        ontvanger.actief = False
        db.commit()
    return RedirectResponse("/beheer/personen", status_code=302)


@app.post("/admin/ontvanger/{ontvanger_id}/activate")
async def admin_activate_ontvanger(
    ontvanger_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    ontvanger = db.query(models.Ontvanger).filter(models.Ontvanger.id == ontvanger_id).first()
    if ontvanger:
        ontvanger.actief = True
        db.commit()
    return RedirectResponse("/beheer/personen", status_code=302)


# ── Eenheden beheer ────────────────────────────────────────────────────────────

@app.post("/admin/eenheid/add")
async def admin_add_eenheid(
    request: Request,
    db: Session = Depends(get_db),
    naam: str = Form(...),
    etiket_per_stuk: str = Form(default=""),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    eenheid = models.Eenheid(
        naam=naam.strip(),
        etiket_per_stuk=bool(etiket_per_stuk),
        actief=True,
    )
    db.add(eenheid)
    db.commit()
    return RedirectResponse("/beheer/eenheden?success=eenheid_added", status_code=302)


@app.post("/admin/eenheid/{eenheid_id}/deactivate")
async def admin_deactivate_eenheid(
    eenheid_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    eenheid = db.query(models.Eenheid).filter(models.Eenheid.id == eenheid_id).first()
    if eenheid:
        eenheid.actief = False
        db.commit()
    return RedirectResponse("/beheer/eenheden", status_code=302)


@app.post("/admin/eenheid/{eenheid_id}/activate")
async def admin_activate_eenheid(
    eenheid_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    eenheid = db.query(models.Eenheid).filter(models.Eenheid.id == eenheid_id).first()
    if eenheid:
        eenheid.actief = True
        db.commit()
    return RedirectResponse("/beheer/eenheden", status_code=302)


# ── Product bewerken / verwijderen ─────────────────────────────────────────────

@app.get("/admin/product/{product_id}/edit")
async def admin_edit_product(product_id: int, request: Request):
    return RedirectResponse(f"/beheer/producten/edit/{product_id}", status_code=302)


@app.post("/admin/product/{product_id}/edit")
async def admin_edit_product_post(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    eenheid_id: int = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if product:
        eenheid = db.query(models.Eenheid).filter(models.Eenheid.id == eenheid_id).first()
        product.name = name.strip()
        product.eenheid_id = eenheid_id
        if eenheid:
            product.unit = eenheid.naam
        db.commit()
    return RedirectResponse("/beheer/producten?success=product_updated", status_code=302)


@app.post("/admin/product/{product_id}/delete")
async def admin_delete_product(product_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        return RedirectResponse("/beheer/producten", status_code=302)

    heeft_entries = db.query(models.HarvestEntry).filter(models.HarvestEntry.product_id == product_id).first()
    if heeft_entries:
        return RedirectResponse("/beheer/producten?error=product_heeft_entries", status_code=302)

    db.delete(product)
    db.commit()
    return RedirectResponse("/beheer/producten?success=product_deleted", status_code=302)


# ── Locatie bewerken / verwijderen ─────────────────────────────────────────────

@app.get("/admin/location/{location_id}/edit")
async def admin_edit_location(location_id: int, request: Request):
    return RedirectResponse(f"/beheer/locaties/edit/{location_id}", status_code=302)


@app.post("/admin/location/{location_id}/edit")
async def admin_edit_location_post(
    location_id: int,
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    location = db.query(models.Location).filter(models.Location.id == location_id).first()
    if location:
        location.name = name.strip()
        db.commit()
    return RedirectResponse("/beheer/locaties?success=location_updated", status_code=302)


@app.post("/admin/location/{location_id}/delete")
async def admin_delete_location(location_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    location = db.query(models.Location).filter(models.Location.id == location_id).first()
    if not location:
        return RedirectResponse("/beheer/locaties", status_code=302)

    heeft_entries = db.query(models.HarvestEntry).filter(models.HarvestEntry.location_id == location_id).first()
    heeft_uitgiftes = db.query(models.Uitgifte).filter(models.Uitgifte.location_id == location_id).first()
    if heeft_entries or heeft_uitgiftes:
        return RedirectResponse("/beheer/locaties?error=location_heeft_registraties", status_code=302)

    db.delete(location)
    db.commit()
    return RedirectResponse("/beheer/locaties?success=location_deleted", status_code=302)


# ── Ontvanger bewerken / verwijderen ───────────────────────────────────────────

@app.get("/admin/ontvanger/{ontvanger_id}/edit")
async def admin_edit_ontvanger(ontvanger_id: int, request: Request):
    return RedirectResponse(f"/beheer/personen/edit/{ontvanger_id}", status_code=302)


@app.post("/admin/ontvanger/{ontvanger_id}/edit")
async def admin_edit_ontvanger_post(
    ontvanger_id: int,
    request: Request,
    db: Session = Depends(get_db),
    naam: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    ontvanger = db.query(models.Ontvanger).filter(models.Ontvanger.id == ontvanger_id).first()
    if ontvanger:
        ontvanger.naam = naam.strip()
        db.commit()
    return RedirectResponse("/beheer/personen?success=persoon_updated", status_code=302)


@app.post("/admin/ontvanger/{ontvanger_id}/delete")
async def admin_delete_ontvanger(ontvanger_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    ontvanger = db.query(models.Ontvanger).filter(models.Ontvanger.id == ontvanger_id).first()
    if not ontvanger:
        return RedirectResponse("/beheer/personen", status_code=302)

    heeft_uitgiftes = db.query(models.Uitgifte).filter(models.Uitgifte.ontvanger == ontvanger.naam).first()
    if heeft_uitgiftes:
        return RedirectResponse("/beheer/personen?error=persoon_heeft_uitgiftes", status_code=302)

    db.delete(ontvanger)
    db.commit()
    return RedirectResponse("/beheer/personen?success=persoon_deleted", status_code=302)


# ── Eenheid bewerken / verwijderen ─────────────────────────────────────────────

@app.get("/admin/eenheid/{eenheid_id}/edit")
async def admin_edit_eenheid(eenheid_id: int, request: Request):
    return RedirectResponse(f"/beheer/eenheden/edit/{eenheid_id}", status_code=302)


@app.post("/admin/eenheid/{eenheid_id}/edit")
async def admin_edit_eenheid_post(
    eenheid_id: int,
    request: Request,
    db: Session = Depends(get_db),
    naam: str = Form(...),
    etiket_per_stuk: str = Form(default=""),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    eenheid = db.query(models.Eenheid).filter(models.Eenheid.id == eenheid_id).first()
    if eenheid:
        eenheid.naam = naam.strip()
        eenheid.etiket_per_stuk = bool(etiket_per_stuk)
        db.commit()
    return RedirectResponse("/beheer/eenheden?success=eenheid_updated", status_code=302)


@app.post("/admin/eenheid/{eenheid_id}/delete")
async def admin_delete_eenheid(eenheid_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    eenheid = db.query(models.Eenheid).filter(models.Eenheid.id == eenheid_id).first()
    if not eenheid:
        return RedirectResponse("/beheer/eenheden", status_code=302)

    heeft_producten = db.query(models.Product).filter(models.Product.eenheid_id == eenheid_id).first()
    if heeft_producten:
        return RedirectResponse("/beheer/eenheden?error=eenheid_heeft_producten", status_code=302)

    db.delete(eenheid)
    db.commit()
    return RedirectResponse("/beheer/eenheden?success=eenheid_deleted", status_code=302)


# ── Houdbaarheid beheer ────────────────────────────────────────────────────────

import calendar as _calendar

def _add_months(dt: datetime.date, months: int) -> datetime.date:
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, _calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


@app.get("/api/houdbaarheid")
async def api_houdbaarheid(
    request: Request,
    db: Session = Depends(get_db),
    product_id: int = None,
    conserveringsmethode_id: int = None,
):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    if not product_id or not conserveringsmethode_id:
        return JSONResponse({"gevonden": False})

    record = db.query(models.ProductHoudbaarheid).filter(
        models.ProductHoudbaarheid.product_id == product_id,
        models.ProductHoudbaarheid.conserveringsmethode_id == conserveringsmethode_id,
        models.ProductHoudbaarheid.actief == True,
    ).first()

    if not record:
        return JSONResponse({"gevonden": False})

    houdbaar_tot = _add_months(datetime.date.today(), record.houdbaarheid_maanden)
    return JSONResponse({
        "gevonden": True,
        "maanden": record.houdbaarheid_maanden,
        "houdbaar_tot": houdbaar_tot.isoformat(),
    })


@app.get("/beheer/houdbaarheid")
async def beheer_houdbaarheid(
    request: Request,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    records = (
        db.query(models.ProductHoudbaarheid)
        .join(models.Product, models.ProductHoudbaarheid.product_id == models.Product.id)
        .outerjoin(models.Conserveringsmethode, models.ProductHoudbaarheid.conserveringsmethode_id == models.Conserveringsmethode.id)
        .order_by(models.Product.name, models.Conserveringsmethode.naam)
        .all()
    )

    methoden = db.query(models.Conserveringsmethode).order_by(models.Conserveringsmethode.naam).all()
    producten = db.query(models.Product).order_by(models.Product.name).all()

    return templates.TemplateResponse(
        "beheer_houdbaarheid.html",
        {
            "request": request,
            "user": user,
            "records": records,
            "methoden": methoden,
            "producten": producten,
            "success": success,
            "error": error,
        },
    )


@app.post("/beheer/houdbaarheid/add")
async def beheer_houdbaarheid_add(
    request: Request,
    db: Session = Depends(get_db),
    product_id: int = Form(...),
    conserveringsmethode_id: int = Form(...),
    houdbaarheid_maanden: int = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    # Controleer op dubbele combinatie
    bestaand = db.query(models.ProductHoudbaarheid).filter(
        models.ProductHoudbaarheid.product_id == product_id,
        models.ProductHoudbaarheid.conserveringsmethode_id == conserveringsmethode_id,
    ).first()
    if bestaand:
        return RedirectResponse("/beheer/houdbaarheid?error=dubbel", status_code=302)

    if houdbaarheid_maanden < 1:
        return RedirectResponse("/beheer/houdbaarheid?error=ongeldig", status_code=302)

    record = models.ProductHoudbaarheid(
        product_id=product_id,
        conserveringsmethode_id=conserveringsmethode_id,
        houdbaarheid_maanden=houdbaarheid_maanden,
        actief=True,
    )
    db.add(record)
    db.commit()
    return RedirectResponse("/beheer/houdbaarheid?success=toegevoegd", status_code=302)


@app.get("/beheer/houdbaarheid/edit/{record_id}")
async def beheer_houdbaarheid_edit(record_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    record = db.query(models.ProductHoudbaarheid).filter(models.ProductHoudbaarheid.id == record_id).first()
    if not record:
        return RedirectResponse("/beheer/houdbaarheid", status_code=302)

    return templates.TemplateResponse(
        "beheer_houdbaarheid_edit.html",
        {"request": request, "user": user, "record": record},
    )


@app.post("/beheer/houdbaarheid/edit/{record_id}")
async def beheer_houdbaarheid_edit_post(
    record_id: int,
    request: Request,
    db: Session = Depends(get_db),
    houdbaarheid_maanden: int = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    record = db.query(models.ProductHoudbaarheid).filter(models.ProductHoudbaarheid.id == record_id).first()
    if record:
        record.houdbaarheid_maanden = houdbaarheid_maanden
        db.commit()
    return RedirectResponse("/beheer/houdbaarheid?success=bijgewerkt", status_code=302)


@app.post("/beheer/houdbaarheid/delete/{record_id}")
async def beheer_houdbaarheid_delete(record_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    record = db.query(models.ProductHoudbaarheid).filter(models.ProductHoudbaarheid.id == record_id).first()
    if record:
        db.delete(record)
        db.commit()
    return RedirectResponse("/beheer/houdbaarheid?success=verwijderd", status_code=302)


# ── Conserveringsmethoden beheer ────────────────────────────────────────────────

@app.post("/beheer/conserveringsmethode/add")
async def beheer_conserveringsmethode_add(
    request: Request,
    db: Session = Depends(get_db),
    naam: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    naam = naam.strip()
    if not naam:
        return RedirectResponse("/beheer/houdbaarheid?error=lege_naam", status_code=302)

    bestaand = db.query(models.Conserveringsmethode).filter(
        func.lower(models.Conserveringsmethode.naam) == naam.lower()
    ).first()
    if bestaand:
        return RedirectResponse("/beheer/houdbaarheid?error=dubbele_methode", status_code=302)

    db.add(models.Conserveringsmethode(naam=naam, actief=True))
    db.commit()
    return RedirectResponse("/beheer/houdbaarheid?success=methode_toegevoegd", status_code=302)


@app.get("/beheer/conserveringsmethode/edit/{methode_id}")
async def beheer_conserveringsmethode_edit_redirect(methode_id: int, request: Request):
    return RedirectResponse(f"/beheer/conservering/edit/{methode_id}", status_code=302)


@app.post("/beheer/conserveringsmethode/edit/{methode_id}")
async def beheer_conserveringsmethode_edit_post(
    methode_id: int,
    request: Request,
    db: Session = Depends(get_db),
    naam: str = Form(...),
    actief: str = Form(default=""),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    methode = db.query(models.Conserveringsmethode).filter(models.Conserveringsmethode.id == methode_id).first()
    if methode:
        methode.naam = naam.strip()
        methode.actief = actief == "on"
        db.commit()
    return RedirectResponse("/beheer/houdbaarheid?success=methode_bijgewerkt", status_code=302)


@app.post("/beheer/conserveringsmethode/delete/{methode_id}")
async def beheer_conserveringsmethode_delete(methode_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    in_gebruik = db.query(models.HarvestEntry).filter(
        models.HarvestEntry.conserveringsmethode_id == methode_id
    ).count() > 0 or db.query(models.ProductHoudbaarheid).filter(
        models.ProductHoudbaarheid.conserveringsmethode_id == methode_id
    ).count() > 0

    if in_gebruik:
        return RedirectResponse("/beheer/houdbaarheid?error=methode_in_gebruik", status_code=302)

    methode = db.query(models.Conserveringsmethode).filter(models.Conserveringsmethode.id == methode_id).first()
    if methode:
        db.delete(methode)
        db.commit()
    return RedirectResponse("/beheer/houdbaarheid?success=methode_verwijderd", status_code=302)


# ── QR Scan lookup ─────────────────────────────────────────────────────────────

@app.get("/scan/{entry_id}")
async def scan_entry(entry_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(f"/login?next=/scan/{entry_id}", status_code=302)

    entry = db.query(models.HarvestEntry).filter(models.HarvestEntry.id == entry_id).first()
    if not entry:
        return templates.TemplateResponse(
            "scan_entry.html",
            {"request": request, "user": user, "entry": None, "not_found": True},
        )

    today = datetime.date.today()
    return templates.TemplateResponse(
        "scan_entry.html",
        {
            "request": request,
            "user": user,
            "entry": entry,
            "not_found": False,
            "today": today,
        },
    )


@app.get("/scan/{entry_id}/uitgifte")
async def scan_uitgifte_form(entry_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(f"/login?next=/scan/{entry_id}/uitgifte", status_code=302)

    entry = db.query(models.HarvestEntry).filter(models.HarvestEntry.id == entry_id).first()
    if not entry or entry.uitgegeven:
        return RedirectResponse(f"/scan/{entry_id}", status_code=302)

    alle_ontvangers = (
        db.query(models.Ontvanger)
        .filter(models.Ontvanger.actief == True)
        .order_by(models.Ontvanger.naam)
        .all()
    )
    _snelkeuze = {"hinke", "maarten"}
    ontvangers_snelkeuze = [o for o in alle_ontvangers if o.naam.lower() in _snelkeuze]
    ontvangers_overig = [o for o in alle_ontvangers if o.naam.lower() not in _snelkeuze]
    today_str = datetime.date.today().isoformat()
    today_date = datetime.date.today()

    return templates.TemplateResponse(
        "scan_uitgifte.html",
        {
            "request": request,
            "user": user,
            "entry": entry,
            "ontvangers_snelkeuze": ontvangers_snelkeuze,
            "ontvangers_overig": ontvangers_overig,
            "today": today_str,
            "today_date": today_date,
            "error": None,
        },
    )


@app.post("/scan/{entry_id}/uitgifte")
async def scan_uitgifte_post(
    entry_id: int,
    request: Request,
    db: Session = Depends(get_db),
    ontvanger_keuze: str = Form(default=""),
    date: str = Form(...),
    note: str = Form(default=""),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(f"/login?next=/scan/{entry_id}/uitgifte", status_code=302)

    entry = db.query(models.HarvestEntry).filter(models.HarvestEntry.id == entry_id).first()
    if not entry or entry.uitgegeven:
        return RedirectResponse(f"/scan/{entry_id}", status_code=302)

    if not ontvanger_keuze.strip():
        alle_ontvangers = (
            db.query(models.Ontvanger).filter(models.Ontvanger.actief == True).order_by(models.Ontvanger.naam).all()
        )
        _snelkeuze = {"hinke", "maarten"}
        return templates.TemplateResponse(
            "scan_uitgifte.html",
            {
                "request": request,
                "user": user,
                "entry": entry,
                "ontvangers_snelkeuze": [o for o in alle_ontvangers if o.naam.lower() in _snelkeuze],
                "ontvangers_overig": [o for o in alle_ontvangers if o.naam.lower() not in _snelkeuze],
                "today": date,
                "today_date": datetime.date.today(),
                "error": "Selecteer een ontvanger.",
            },
        )

    db_ontvanger = db.query(models.Ontvanger).filter(models.Ontvanger.id == int(ontvanger_keuze)).first()
    ontvanger_naam = db_ontvanger.naam if db_ontvanger else ontvanger_keuze

    # Maak uitgifte record aan
    uitgifte = models.Uitgifte(
        harvest_entry_id=entry.id,
        product_id=entry.product_id,
        location_id=entry.location_id,
        quantity=entry.quantity,
        ontvanger=ontvanger_naam,
        date=date,
        entered_by=user,
        note=note.strip() or None,
        created_at=datetime.datetime.utcnow(),
    )
    db.add(uitgifte)

    # Markeer entry als uitgegeven
    entry.uitgegeven = True
    entry.uitgegeven_op = datetime.datetime.utcnow()
    entry.uitgegeven_aan = ontvanger_naam

    db.commit()

    return templates.TemplateResponse(
        "scan_uitgifte_succes.html",
        {
            "request": request,
            "user": user,
            "entry": entry,
            "ontvanger": ontvanger_naam,
            "date": date,
        },
    )


# ── QR Scanner pagina ──────────────────────────────────────────────────────────

@app.get("/uitgifte/scan")
async def uitgifte_scan(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login?next=/uitgifte/scan", status_code=302)
    return templates.TemplateResponse(
        "uitgifte_scan.html",
        {"request": request, "user": user},
    )


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
    alle_ontvangers = (
        db.query(models.Ontvanger)
        .filter(models.Ontvanger.actief == True)
        .order_by(models.Ontvanger.naam)
        .all()
    )
    _snelkeuze = {"hinke", "maarten"}
    ontvangers_snelkeuze = [o for o in alle_ontvangers if o.naam.lower() in _snelkeuze]
    ontvangers_overig = [o for o in alle_ontvangers if o.naam.lower() not in _snelkeuze]
    today = datetime.date.today().isoformat()

    return templates.TemplateResponse(
        "uitgifte_new.html",
        {
            "request": request,
            "user": user,
            "products": products,
            "locations": locations,
            "ontvangers_snelkeuze": ontvangers_snelkeuze,
            "ontvangers_overig": ontvangers_overig,
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
    ontvanger_keuze: str = Form(default=""),
    date: str = Form(...),
    note: str = Form(default=""),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    def _haal_formulier_data():
        alle = (
            db.query(models.Ontvanger).filter(models.Ontvanger.actief == True).order_by(models.Ontvanger.naam).all()
        )
        _sk = {"hinke", "maarten"}
        return (
            db.query(models.Product).filter(models.Product.active == True).order_by(models.Product.name).all(),
            db.query(models.Location).filter(models.Location.active == True).order_by(models.Location.name).all(),
            [o for o in alle if o.naam.lower() in _sk],
            [o for o in alle if o.naam.lower() not in _sk],
        )

    if not ontvanger_keuze.strip():
        prods, locs, sk, ov = _haal_formulier_data()
        return templates.TemplateResponse(
            "uitgifte_new.html",
            {
                "request": request,
                "user": user,
                "products": prods,
                "locations": locs,
                "ontvangers_snelkeuze": sk,
                "ontvangers_overig": ov,
                "today": date,
                "error": "Selecteer een ontvanger.",
                "form": {
                    "product_id": product_id,
                    "location_id": location_id,
                    "quantity": quantity,
                    "ontvanger_keuze": "",
                    "date": date,
                    "note": note,
                },
            },
        )

    # Bepaal de ontvangernaam
    db_ontvanger = db.query(models.Ontvanger).filter(models.Ontvanger.id == int(ontvanger_keuze)).first()
    ontvanger = db_ontvanger.naam if db_ontvanger else ontvanger_keuze

    beschikbaar = _beschikbare_voorraad(db, product_id, location_id)

    if quantity > beschikbaar:
        product = db.query(models.Product).filter(models.Product.id == product_id).first()
        unit = product.unit if product else ""
        prods, locs, sk, ov = _haal_formulier_data()
        return templates.TemplateResponse(
            "uitgifte_new.html",
            {
                "request": request,
                "user": user,
                "products": prods,
                "locations": locs,
                "ontvangers_snelkeuze": sk,
                "ontvangers_overig": ov,
                "today": date,
                "error": f"Onvoldoende voorraad. Beschikbaar: {beschikbaar:g} {unit}",
                "form": {
                    "product_id": product_id,
                    "location_id": location_id,
                    "quantity": quantity,
                    "ontvanger_keuze": ontvanger_keuze,
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
async def uitgiftes_redirect(request: Request):
    return RedirectResponse("/beheer/geschiedenis?tab=uitgiftes", status_code=301)


@app.get("/uitgiftes_legacy_unused")
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
async def uitgiftes_export_redirect(request: Request):
    return RedirectResponse("/beheer/geschiedenis/export/uitgiftes", status_code=301)


@app.get("/uitgiftes/export_legacy_unused")
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


# ── Beheer: Gecombineerd Geschiedenis & Uitgiftes overzicht ────────────────────

@app.get("/beheer/geschiedenis")
async def beheer_geschiedenis(
    request: Request,
    db: Session = Depends(get_db),
    tab: str = "registraties",
    product_id: int = None,
    location_id: int = None,
    date_from: str = None,
    date_to: str = None,
    ontvanger: str = None,
    u_date_from: str = None,
    u_date_to: str = None,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    products = db.query(models.Product).order_by(models.Product.name).all()
    locations = db.query(models.Location).order_by(models.Location.name).all()

    # Registraties
    reg_query = (
        db.query(models.HarvestEntry)
        .join(models.Product, models.HarvestEntry.product_id == models.Product.id)
        .join(models.Location, models.HarvestEntry.location_id == models.Location.id)
    )
    if product_id:
        reg_query = reg_query.filter(models.HarvestEntry.product_id == product_id)
    if location_id:
        reg_query = reg_query.filter(models.HarvestEntry.location_id == location_id)
    if date_from:
        reg_query = reg_query.filter(models.HarvestEntry.date >= date_from)
    if date_to:
        reg_query = reg_query.filter(models.HarvestEntry.date <= date_to)
    registraties = reg_query.order_by(
        models.HarvestEntry.date.desc(), models.HarvestEntry.created_at.desc()
    ).all()

    # Uitgiftes
    uit_query = (
        db.query(models.Uitgifte)
        .join(models.Product, models.Uitgifte.product_id == models.Product.id)
        .join(models.Location, models.Uitgifte.location_id == models.Location.id)
    )
    if ontvanger:
        uit_query = uit_query.filter(models.Uitgifte.ontvanger == ontvanger)
    if u_date_from:
        uit_query = uit_query.filter(models.Uitgifte.date >= u_date_from)
    if u_date_to:
        uit_query = uit_query.filter(models.Uitgifte.date <= u_date_to)
    uitgifte_entries = uit_query.order_by(
        models.Uitgifte.date.desc(), models.Uitgifte.created_at.desc()
    ).all()

    # Totaal per ontvanger
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
    if u_date_from:
        totaal_query = totaal_query.filter(models.Uitgifte.date >= u_date_from)
    if u_date_to:
        totaal_query = totaal_query.filter(models.Uitgifte.date <= u_date_to)
    totaal_rows = totaal_query.all()
    totaal_per_ontvanger: dict[str, list] = {}
    for r in totaal_rows:
        if r.ontvanger not in totaal_per_ontvanger:
            totaal_per_ontvanger[r.ontvanger] = []
        totaal_per_ontvanger[r.ontvanger].append(
            {"product": r.product_name, "unit": r.unit, "total": r.total}
        )

    _ontvanger_prio = {"hinke": 0, "maarten": 1}
    totaal_per_ontvanger = dict(
        sorted(totaal_per_ontvanger.items(),
               key=lambda x: (_ontvanger_prio.get(x[0].lower(), 2), x[0].lower()))
    )

    alle_ontvangers = [
        r[0]
        for r in db.query(models.Uitgifte.ontvanger).distinct().order_by(models.Uitgifte.ontvanger).all()
    ]

    active_tab = tab if tab in ("registraties", "uitgiftes", "winkel") else "registraties"

    shop_items = []
    if active_tab == "winkel":
        shop_items = (
            db.query(models.ShopItem)
            .filter(models.ShopItem.owner == user)
            .order_by(
                models.ShopItem.houdbaar_tot.asc().nullsfirst(),
                models.ShopItem.name.asc(),
            )
            .all()
        )

    # Geaggregeerde boerderij voorraad (voor tab=registraties)
    today = datetime.date.today()
    voorraad_items = []
    if active_tab == "registraties":
        harvest_totalen = (
            db.query(
                models.Product.id.label("product_id"),
                models.Product.name.label("product_naam"),
                models.Product.unit.label("unit"),
                models.Location.id.label("location_id"),
                models.Location.name.label("locatie_naam"),
                func.sum(models.HarvestEntry.quantity).label("harvest_total"),
            )
            .select_from(models.HarvestEntry)
            .join(models.Product, models.HarvestEntry.product_id == models.Product.id)
            .join(models.Location, models.HarvestEntry.location_id == models.Location.id)
            .group_by(
                models.Product.id, models.Product.name, models.Product.unit,
                models.Location.id, models.Location.name,
            )
            .all()
        )

        uitgifte_map = {
            (r[0], r[1]): (r[2] or 0)
            for r in db.query(
                models.Uitgifte.product_id,
                models.Uitgifte.location_id,
                func.sum(models.Uitgifte.quantity),
            )
            .group_by(models.Uitgifte.product_id, models.Uitgifte.location_id)
            .all()
        }

        tht_map = {
            (r[0], r[1]): r[2]
            for r in db.query(
                models.HarvestEntry.product_id,
                models.HarvestEntry.location_id,
                func.min(models.HarvestEntry.houdbaar_tot),
            )
            .filter(
                models.HarvestEntry.uitgegeven == False,
                models.HarvestEntry.houdbaar_tot != None,
            )
            .group_by(models.HarvestEntry.product_id, models.HarvestEntry.location_id)
            .all()
        }

        for row in harvest_totalen:
            uitgegeven_totaal = uitgifte_map.get((row.product_id, row.location_id), 0)
            netto = (row.harvest_total or 0) - uitgegeven_totaal
            if netto > 0:
                eenheid = ""
                product_obj = db.query(models.Product).filter(models.Product.id == row.product_id).first()
                if product_obj:
                    eenheid = product_obj.eenheid.naam if product_obj.eenheid else (product_obj.unit or "")
                voorraad_items.append({
                    "product_id": row.product_id,
                    "product_naam": row.product_naam,
                    "locatie_id": row.location_id,
                    "locatie_naam": row.locatie_naam,
                    "voorraad": netto,
                    "eenheid": eenheid,
                    "vroegste_tht": tht_map.get((row.product_id, row.location_id)),
                })

        voorraad_items.sort(key=lambda x: (x["locatie_naam"], x["product_naam"]))

    return templates.TemplateResponse(
        "beheer_geschiedenis.html",
        {
            "request": request,
            "user": user,
            "tab": active_tab,
            "registraties": registraties,
            "voorraad_items": voorraad_items,
            "products": products,
            "locations": locations,
            "filter_product_id": product_id,
            "filter_location_id": location_id,
            "filter_date_from": date_from or "",
            "filter_date_to": date_to or "",
            "uitgifte_entries": uitgifte_entries,
            "alle_ontvangers": alle_ontvangers,
            "filter_ontvanger": ontvanger or "",
            "u_date_from": u_date_from or "",
            "u_date_to": u_date_to or "",
            "totaal_per_ontvanger": totaal_per_ontvanger,
            "shop_items": shop_items,
            "today": today,
        },
    )


@app.get("/beheer/geschiedenis/export/registraties")
async def beheer_geschiedenis_export_registraties(
    request: Request,
    db: Session = Depends(get_db),
    product_id: int = None,
    location_id: int = None,
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
    if location_id:
        query = query.filter(models.HarvestEntry.location_id == location_id)
    if date_from:
        query = query.filter(models.HarvestEntry.date >= date_from)
    if date_to:
        query = query.filter(models.HarvestEntry.date <= date_to)

    entries = query.order_by(
        models.HarvestEntry.date.desc(), models.HarvestEntry.created_at.desc()
    ).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Datum", "Entry ID", "Product", "Locatie", "Hoeveelheid", "Eenheid",
        "Houdbaar tot", "Ingevoerd door", "Gewijzigd door", "Notitie",
    ])
    for e in entries:
        writer.writerow([
            e.date,
            e.id,
            e.product.name,
            e.location.name,
            e.quantity,
            e.product.unit,
            e.houdbaar_tot.isoformat() if e.houdbaar_tot else "",
            e.entered_by,
            e.gewijzigd_door or "",
            e.note or "",
        ])

    filename = f"registraties_export_{datetime.date.today().isoformat()}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/beheer/geschiedenis/export/uitgiftes")
async def beheer_geschiedenis_export_uitgiftes(
    request: Request,
    db: Session = Depends(get_db),
    ontvanger: str = None,
    u_date_from: str = None,
    u_date_to: str = None,
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
    if u_date_from:
        query = query.filter(models.Uitgifte.date >= u_date_from)
    if u_date_to:
        query = query.filter(models.Uitgifte.date <= u_date_to)

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


# ── Uitgifte bewerken ──────────────────────────────────────────────────────────

@app.get("/beheer/uitgifte/edit/{uitgifte_id}")
async def beheer_uitgifte_edit(uitgifte_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    uitgifte = db.query(models.Uitgifte).filter(models.Uitgifte.id == uitgifte_id).first()
    if not uitgifte:
        return RedirectResponse("/beheer/geschiedenis?tab=uitgiftes", status_code=302)

    products = db.query(models.Product).order_by(models.Product.name).all()
    locations = db.query(models.Location).order_by(models.Location.name).all()
    ontvangers = db.query(models.Ontvanger).filter(models.Ontvanger.actief == True).order_by(models.Ontvanger.naam).all()

    return templates.TemplateResponse(
        "beheer_uitgifte_edit.html",
        {
            "request": request,
            "user": user,
            "uitgifte": uitgifte,
            "products": products,
            "locations": locations,
            "ontvangers": ontvangers,
        },
    )


@app.post("/beheer/uitgifte/edit/{uitgifte_id}")
async def beheer_uitgifte_edit_post(
    uitgifte_id: int,
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

    uitgifte = db.query(models.Uitgifte).filter(models.Uitgifte.id == uitgifte_id).first()
    if not uitgifte:
        return RedirectResponse("/beheer/geschiedenis?tab=uitgiftes", status_code=302)

    # Beschikbare voorraad: voeg huidige uitgifte terug toe als product/locatie gelijk is
    beschikbaar = _beschikbare_voorraad(db, product_id, location_id)
    if product_id == uitgifte.product_id and location_id == uitgifte.location_id:
        beschikbaar += uitgifte.quantity

    if quantity > beschikbaar:
        product = db.query(models.Product).filter(models.Product.id == product_id).first()
        unit = product.unit if product else ""
        return RedirectResponse(
            f"/beheer/uitgifte/edit/{uitgifte_id}?error=voorraad&beschikbaar={beschikbaar:g}&unit={quote(unit)}",
            status_code=302,
        )

    uitgifte.product_id = product_id
    uitgifte.location_id = location_id
    uitgifte.quantity = quantity
    uitgifte.ontvanger = ontvanger.strip()
    uitgifte.date = date
    uitgifte.note = note.strip() or None
    db.commit()
    return RedirectResponse("/beheer/geschiedenis?tab=uitgiftes", status_code=302)


@app.post("/beheer/uitgifte/delete/{uitgifte_id}")
async def beheer_uitgifte_delete(uitgifte_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    uitgifte = db.query(models.Uitgifte).filter(models.Uitgifte.id == uitgifte_id).first()
    if uitgifte:
        db.delete(uitgifte)
        db.commit()
    return RedirectResponse("/beheer/geschiedenis?tab=uitgiftes", status_code=302)


# ── Beheer: Producten module ────────────────────────────────────────────────────

@app.get("/beheer/producten")
async def beheer_producten(
    request: Request,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    products = db.query(models.Product).order_by(models.Product.active.desc(), models.Product.name).all()
    actieve_eenheden = db.query(models.Eenheid).filter(models.Eenheid.actief == True).order_by(models.Eenheid.naam).all()

    return templates.TemplateResponse(
        "beheer_producten.html",
        {
            "request": request,
            "user": user,
            "products": products,
            "actieve_eenheden": actieve_eenheden,
            "success": success,
            "error": error,
        },
    )


@app.post("/beheer/producten/add")
async def beheer_producten_add(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    eenheid_id: int = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    eenheid = db.query(models.Eenheid).filter(models.Eenheid.id == eenheid_id).first()
    unit_naam = eenheid.naam if eenheid else ""
    product = models.Product(name=name.strip(), unit=unit_naam, eenheid_id=eenheid_id, active=True)
    db.add(product)
    db.commit()
    return RedirectResponse("/beheer/producten?success=product_added", status_code=302)


@app.post("/beheer/producten/deactivate/{product_id}")
async def beheer_producten_deactivate(product_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if product:
        product.active = False
        db.commit()
    return RedirectResponse("/beheer/producten", status_code=302)


@app.post("/beheer/producten/activate/{product_id}")
async def beheer_producten_activate(product_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if product:
        product.active = True
        db.commit()
    return RedirectResponse("/beheer/producten", status_code=302)


@app.get("/beheer/producten/edit/{product_id}")
async def beheer_producten_edit(product_id: int, request: Request, db: Session = Depends(get_db), success: str = None, error: str = None):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        return RedirectResponse("/beheer/producten", status_code=302)

    eenheden = db.query(models.Eenheid).filter(models.Eenheid.actief == True).order_by(models.Eenheid.naam).all()

    houdbaarheid_records = (
        db.query(models.ProductHoudbaarheid)
        .outerjoin(models.Conserveringsmethode, models.ProductHoudbaarheid.conserveringsmethode_id == models.Conserveringsmethode.id)
        .filter(models.ProductHoudbaarheid.product_id == product_id)
        .order_by(models.Conserveringsmethode.naam)
        .all()
    )

    # Methoden die nog niet gebruikt zijn voor dit product
    gebruikte_methode_ids = {r.conserveringsmethode_id for r in houdbaarheid_records if r.conserveringsmethode_id}
    alle_methoden = db.query(models.Conserveringsmethode).filter(models.Conserveringsmethode.actief == True).order_by(models.Conserveringsmethode.naam).all()
    beschikbare_methoden = [m for m in alle_methoden if m.id not in gebruikte_methode_ids]

    return templates.TemplateResponse(
        "beheer_producten_edit.html",
        {
            "request": request,
            "user": user,
            "product": product,
            "eenheden": eenheden,
            "houdbaarheid_records": houdbaarheid_records,
            "beschikbare_methoden": beschikbare_methoden,
            "success": success,
            "error": error,
        },
    )


@app.post("/beheer/producten/edit/{product_id}")
async def beheer_producten_edit_post(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    eenheid_id: int = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if product:
        eenheid = db.query(models.Eenheid).filter(models.Eenheid.id == eenheid_id).first()
        product.name = name.strip()
        product.eenheid_id = eenheid_id
        if eenheid:
            product.unit = eenheid.naam
        db.commit()
    return RedirectResponse(f"/beheer/producten/edit/{product_id}?success=product_updated", status_code=302)


@app.post("/beheer/producten/delete/{product_id}")
async def beheer_producten_delete(product_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        return RedirectResponse("/beheer/producten", status_code=302)

    heeft_entries = db.query(models.HarvestEntry).filter(models.HarvestEntry.product_id == product_id).first()
    if heeft_entries:
        return RedirectResponse("/beheer/producten?error=product_heeft_entries", status_code=302)

    db.delete(product)
    db.commit()
    return RedirectResponse("/beheer/producten?success=product_deleted", status_code=302)


@app.post("/beheer/producten/houdbaarheid/add")
async def beheer_producten_houdbaarheid_add(
    request: Request,
    db: Session = Depends(get_db),
    product_id: int = Form(...),
    conserveringsmethode_id: int = Form(...),
    houdbaarheid_maanden: int = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    bestaand = db.query(models.ProductHoudbaarheid).filter(
        models.ProductHoudbaarheid.product_id == product_id,
        models.ProductHoudbaarheid.conserveringsmethode_id == conserveringsmethode_id,
    ).first()
    if bestaand:
        return RedirectResponse(f"/beheer/producten/edit/{product_id}?error=houdbaarheid_dubbel", status_code=302)

    if houdbaarheid_maanden < 1:
        return RedirectResponse(f"/beheer/producten/edit/{product_id}?error=houdbaarheid_ongeldig", status_code=302)

    record = models.ProductHoudbaarheid(
        product_id=product_id,
        conserveringsmethode_id=conserveringsmethode_id,
        houdbaarheid_maanden=houdbaarheid_maanden,
        actief=True,
    )
    db.add(record)
    db.commit()
    return RedirectResponse(f"/beheer/producten/edit/{product_id}?success=houdbaarheid_toegevoegd", status_code=302)


# ── Beheer: Locaties module ─────────────────────────────────────────────────────

@app.get("/beheer/locaties")
async def beheer_locaties(
    request: Request,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    locations = db.query(models.Location).order_by(models.Location.active.desc(), models.Location.name).all()

    return templates.TemplateResponse(
        "beheer_locaties.html",
        {
            "request": request,
            "user": user,
            "locations": locations,
            "success": success,
            "error": error,
        },
    )


@app.post("/beheer/locaties/add")
async def beheer_locaties_add(
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
    return RedirectResponse("/beheer/locaties?success=location_added", status_code=302)


@app.post("/beheer/locaties/deactivate/{location_id}")
async def beheer_locaties_deactivate(location_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    location = db.query(models.Location).filter(models.Location.id == location_id).first()
    if location:
        location.active = False
        db.commit()
    return RedirectResponse("/beheer/locaties", status_code=302)


@app.post("/beheer/locaties/activate/{location_id}")
async def beheer_locaties_activate(location_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    location = db.query(models.Location).filter(models.Location.id == location_id).first()
    if location:
        location.active = True
        db.commit()
    return RedirectResponse("/beheer/locaties", status_code=302)


@app.get("/beheer/locaties/edit/{location_id}")
async def beheer_locaties_edit(location_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    location = db.query(models.Location).filter(models.Location.id == location_id).first()
    if not location:
        return RedirectResponse("/beheer/locaties", status_code=302)

    return templates.TemplateResponse(
        "beheer_locaties_edit.html",
        {"request": request, "user": user, "location": location},
    )


@app.post("/beheer/locaties/edit/{location_id}")
async def beheer_locaties_edit_post(
    location_id: int,
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    location = db.query(models.Location).filter(models.Location.id == location_id).first()
    if location:
        location.name = name.strip()
        db.commit()
    return RedirectResponse("/beheer/locaties?success=location_updated", status_code=302)


@app.post("/beheer/locaties/delete/{location_id}")
async def beheer_locaties_delete(location_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    location = db.query(models.Location).filter(models.Location.id == location_id).first()
    if not location:
        return RedirectResponse("/beheer/locaties", status_code=302)

    heeft_entries = db.query(models.HarvestEntry).filter(models.HarvestEntry.location_id == location_id).first()
    heeft_uitgiftes = db.query(models.Uitgifte).filter(models.Uitgifte.location_id == location_id).first()
    if heeft_entries or heeft_uitgiftes:
        return RedirectResponse("/beheer/locaties?error=location_heeft_registraties", status_code=302)

    db.delete(location)
    db.commit()
    return RedirectResponse("/beheer/locaties?success=location_deleted", status_code=302)


# ── Beheer: Personen module ─────────────────────────────────────────────────────

@app.get("/beheer/personen")
async def beheer_personen(
    request: Request,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    personen = db.query(models.Ontvanger).order_by(models.Ontvanger.actief.desc(), models.Ontvanger.naam).all()

    return templates.TemplateResponse(
        "beheer_personen.html",
        {
            "request": request,
            "user": user,
            "personen": personen,
            "success": success,
            "error": error,
        },
    )


@app.post("/beheer/personen/add")
async def beheer_personen_add(
    request: Request,
    db: Session = Depends(get_db),
    naam: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    persoon = models.Ontvanger(naam=naam.strip(), actief=True)
    db.add(persoon)
    db.commit()
    return RedirectResponse("/beheer/personen?success=persoon_added", status_code=302)


@app.post("/beheer/personen/deactivate/{persoon_id}")
async def beheer_personen_deactivate(persoon_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    persoon = db.query(models.Ontvanger).filter(models.Ontvanger.id == persoon_id).first()
    if persoon:
        persoon.actief = False
        db.commit()
    return RedirectResponse("/beheer/personen", status_code=302)


@app.post("/beheer/personen/activate/{persoon_id}")
async def beheer_personen_activate(persoon_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    persoon = db.query(models.Ontvanger).filter(models.Ontvanger.id == persoon_id).first()
    if persoon:
        persoon.actief = True
        db.commit()
    return RedirectResponse("/beheer/personen", status_code=302)


@app.get("/beheer/personen/edit/{persoon_id}")
async def beheer_personen_edit(persoon_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    persoon = db.query(models.Ontvanger).filter(models.Ontvanger.id == persoon_id).first()
    if not persoon:
        return RedirectResponse("/beheer/personen", status_code=302)

    return templates.TemplateResponse(
        "beheer_personen_edit.html",
        {"request": request, "user": user, "persoon": persoon},
    )


@app.post("/beheer/personen/edit/{persoon_id}")
async def beheer_personen_edit_post(
    persoon_id: int,
    request: Request,
    db: Session = Depends(get_db),
    naam: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    persoon = db.query(models.Ontvanger).filter(models.Ontvanger.id == persoon_id).first()
    if persoon:
        persoon.naam = naam.strip()
        db.commit()
    return RedirectResponse("/beheer/personen?success=persoon_updated", status_code=302)


@app.post("/beheer/personen/delete/{persoon_id}")
async def beheer_personen_delete(persoon_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    persoon = db.query(models.Ontvanger).filter(models.Ontvanger.id == persoon_id).first()
    if not persoon:
        return RedirectResponse("/beheer/personen", status_code=302)

    heeft_uitgiftes = db.query(models.Uitgifte).filter(models.Uitgifte.ontvanger == persoon.naam).first()
    if heeft_uitgiftes:
        return RedirectResponse("/beheer/personen?error=persoon_heeft_uitgiftes", status_code=302)

    db.delete(persoon)
    db.commit()
    return RedirectResponse("/beheer/personen?success=persoon_deleted", status_code=302)


# ── Beheer: Eenheden module ─────────────────────────────────────────────────────

@app.get("/beheer/eenheden")
async def beheer_eenheden(
    request: Request,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    eenheden = db.query(models.Eenheid).order_by(models.Eenheid.actief.desc(), models.Eenheid.naam).all()

    return templates.TemplateResponse(
        "beheer_eenheden.html",
        {
            "request": request,
            "user": user,
            "eenheden": eenheden,
            "success": success,
            "error": error,
        },
    )


@app.post("/beheer/eenheden/add")
async def beheer_eenheden_add(
    request: Request,
    db: Session = Depends(get_db),
    naam: str = Form(...),
    etiket_per_stuk: str = Form(default=""),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    eenheid = models.Eenheid(
        naam=naam.strip(),
        etiket_per_stuk=bool(etiket_per_stuk),
        actief=True,
    )
    db.add(eenheid)
    db.commit()
    return RedirectResponse("/beheer/eenheden?success=eenheid_added", status_code=302)


@app.post("/beheer/eenheden/deactivate/{eenheid_id}")
async def beheer_eenheden_deactivate(eenheid_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    eenheid = db.query(models.Eenheid).filter(models.Eenheid.id == eenheid_id).first()
    if eenheid:
        eenheid.actief = False
        db.commit()
    return RedirectResponse("/beheer/eenheden", status_code=302)


@app.post("/beheer/eenheden/activate/{eenheid_id}")
async def beheer_eenheden_activate(eenheid_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    eenheid = db.query(models.Eenheid).filter(models.Eenheid.id == eenheid_id).first()
    if eenheid:
        eenheid.actief = True
        db.commit()
    return RedirectResponse("/beheer/eenheden", status_code=302)


@app.get("/beheer/eenheden/edit/{eenheid_id}")
async def beheer_eenheden_edit(eenheid_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    eenheid = db.query(models.Eenheid).filter(models.Eenheid.id == eenheid_id).first()
    if not eenheid:
        return RedirectResponse("/beheer/eenheden", status_code=302)

    return templates.TemplateResponse(
        "beheer_eenheden_edit.html",
        {"request": request, "user": user, "eenheid": eenheid},
    )


@app.post("/beheer/eenheden/edit/{eenheid_id}")
async def beheer_eenheden_edit_post(
    eenheid_id: int,
    request: Request,
    db: Session = Depends(get_db),
    naam: str = Form(...),
    etiket_per_stuk: str = Form(default=""),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    eenheid = db.query(models.Eenheid).filter(models.Eenheid.id == eenheid_id).first()
    if eenheid:
        eenheid.naam = naam.strip()
        eenheid.etiket_per_stuk = bool(etiket_per_stuk)
        db.commit()
    return RedirectResponse("/beheer/eenheden?success=eenheid_updated", status_code=302)


@app.post("/beheer/eenheden/delete/{eenheid_id}")
async def beheer_eenheden_delete(eenheid_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    eenheid = db.query(models.Eenheid).filter(models.Eenheid.id == eenheid_id).first()
    if not eenheid:
        return RedirectResponse("/beheer/eenheden", status_code=302)

    heeft_producten = db.query(models.Product).filter(models.Product.eenheid_id == eenheid_id).first()
    if heeft_producten:
        return RedirectResponse("/beheer/eenheden?error=eenheid_heeft_producten", status_code=302)

    db.delete(eenheid)
    db.commit()
    return RedirectResponse("/beheer/eenheden?success=eenheid_deleted", status_code=302)


# ── Beheer: Conservering module ─────────────────────────────────────────────────

@app.get("/beheer/conservering")
async def beheer_conservering(
    request: Request,
    success: str = None,
    error: str = None,
):
    params = {}
    if success:
        params["success"] = success
    if error:
        params["error"] = error
    qs = ("?" + "&".join(f"{k}={v}" for k, v in params.items())) if params else ""
    return RedirectResponse(f"/beheer/houdbaarheid{qs}", status_code=302)


@app.post("/beheer/conservering/add")
async def beheer_conservering_add(
    request: Request,
    db: Session = Depends(get_db),
    naam: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    naam = naam.strip()
    if not naam:
        return RedirectResponse("/beheer/houdbaarheid?error=lege_naam", status_code=302)

    bestaand = db.query(models.Conserveringsmethode).filter(
        func.lower(models.Conserveringsmethode.naam) == naam.lower()
    ).first()
    if bestaand:
        return RedirectResponse("/beheer/houdbaarheid?error=dubbele_methode", status_code=302)

    db.add(models.Conserveringsmethode(naam=naam, actief=True))
    db.commit()
    return RedirectResponse("/beheer/houdbaarheid?success=methode_toegevoegd", status_code=302)


@app.get("/beheer/conservering/edit/{methode_id}")
async def beheer_conservering_edit(methode_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    methode = db.query(models.Conserveringsmethode).filter(models.Conserveringsmethode.id == methode_id).first()
    if not methode:
        return RedirectResponse("/beheer/houdbaarheid", status_code=302)

    in_gebruik = (
        db.query(models.HarvestEntry).filter(models.HarvestEntry.conserveringsmethode_id == methode_id).count() > 0
        or db.query(models.ProductHoudbaarheid).filter(models.ProductHoudbaarheid.conserveringsmethode_id == methode_id).count() > 0
    )

    return templates.TemplateResponse(
        "beheer_conservering_edit.html",
        {"request": request, "user": user, "methode": methode, "in_gebruik": in_gebruik},
    )


@app.post("/beheer/conservering/edit/{methode_id}")
async def beheer_conservering_edit_post(
    methode_id: int,
    request: Request,
    db: Session = Depends(get_db),
    naam: str = Form(...),
    actief: str = Form(default=""),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    methode = db.query(models.Conserveringsmethode).filter(models.Conserveringsmethode.id == methode_id).first()
    if methode:
        methode.naam = naam.strip()
        methode.actief = actief == "on"
        db.commit()
    return RedirectResponse("/beheer/houdbaarheid?success=methode_bijgewerkt", status_code=302)


@app.post("/beheer/conservering/delete/{methode_id}")
async def beheer_conservering_delete(methode_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    in_gebruik = (
        db.query(models.HarvestEntry).filter(models.HarvestEntry.conserveringsmethode_id == methode_id).count() > 0
        or db.query(models.ProductHoudbaarheid).filter(models.ProductHoudbaarheid.conserveringsmethode_id == methode_id).count() > 0
    )

    if in_gebruik:
        return RedirectResponse("/beheer/houdbaarheid?error=methode_in_gebruik", status_code=302)

    methode = db.query(models.Conserveringsmethode).filter(models.Conserveringsmethode.id == methode_id).first()
    if methode:
        db.delete(methode)
        db.commit()
    return RedirectResponse("/beheer/houdbaarheid?success=methode_verwijderd", status_code=302)


# ── API: Houdbaarheid inline toevoegen ──────────────────────────────────────────

@app.post("/api/houdbaarheid/toevoegen")
async def api_houdbaarheid_toevoegen(
    request: Request,
    db: Session = Depends(get_db),
):
    import json as _json
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = await request.json()
        product_id = int(body["product_id"])
        conserveringsmethode_id = int(body["conserveringsmethode_id"])
        houdbaarheid_maanden = int(body["houdbaarheid_maanden"])
    except Exception:
        return JSONResponse({"error": "Ongeldige invoer"}, status_code=400)

    if houdbaarheid_maanden < 1:
        return JSONResponse({"error": "Houdbaarheid moet minimaal 1 maand zijn"}, status_code=400)

    bestaand = db.query(models.ProductHoudbaarheid).filter(
        models.ProductHoudbaarheid.product_id == product_id,
        models.ProductHoudbaarheid.conserveringsmethode_id == conserveringsmethode_id,
    ).first()
    if bestaand:
        # Update bestaand record in plaats van fout teruggeven
        bestaand.houdbaarheid_maanden = houdbaarheid_maanden
        db.commit()
    else:
        record = models.ProductHoudbaarheid(
            product_id=product_id,
            conserveringsmethode_id=conserveringsmethode_id,
            houdbaarheid_maanden=houdbaarheid_maanden,
            actief=True,
        )
        db.add(record)
        db.commit()

    houdbaar_tot = _add_months(datetime.date.today(), houdbaarheid_maanden)
    return JSONResponse({
        "succes": True,
        "houdbaar_tot": houdbaar_tot.isoformat(),
        "maanden": houdbaarheid_maanden,
    })


# ── Centrale invoerpagina ──────────────────────────────────────────────────────

@app.get("/invoer")
async def invoer(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login?next=/invoer", status_code=302)
    return templates.TemplateResponse("invoer.html", {"request": request, "user": user})


# ── Centrale uitgiftepagina ─────────────────────────────────────────────────────

@app.get("/uitgifte")
async def uitgifte_hub(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login?next=/uitgifte", status_code=302)
    andere = "hinke" if user.lower() == "maarten" else "maarten"
    return templates.TemplateResponse(
        "uitgifte_hub.html",
        {"request": request, "user": user, "andere": andere},
    )


# ── Voorraad (alias voor beheer/geschiedenis) ───────────────────────────────────

@app.get("/voorraad")
async def voorraad_redirect(request: Request, tab: str = "registraties"):
    return RedirectResponse(f"/beheer/geschiedenis?tab={tab}", status_code=302)


# ── Winkelvoorraad ──────────────────────────────────────────────────────────────

@app.get("/winkel")
async def winkel(request: Request, db: Session = Depends(get_db), success: str = None, error: str = None, scan: int = 0):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    today = datetime.date.today()
    items = (
        db.query(models.ShopItem)
        .filter(models.ShopItem.owner == user)
        .order_by(models.ShopItem.houdbaar_tot.asc().nullsfirst(), models.ShopItem.name.asc())
        .all()
    )

    return templates.TemplateResponse(
        "winkel.html",
        {
            "request": request,
            "user": user,
            "items": items,
            "today": today,
            "success": success,
            "error": error,
            "auto_scan": bool(scan),
        },
    )


# ── API: Open Food Facts proxy ──────────────────────────────────────────────────

@app.get("/api/shop/openfoodfacts/{barcode}")
async def openfoodfacts_proxy(barcode: str, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    # Controleer cache
    cached = db.query(models.ProductCache).filter(models.ProductCache.barcode == barcode).first()
    if cached:
        return JSONResponse({
            "name": cached.name,
            "brand": cached.brand,
            "quantity": cached.quantity,
            "unit": cached.unit,
            "image_url": cached.image_url,
        })

    try:
        resp = http_requests.get(
            f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json",
            timeout=5,
            headers={"User-Agent": "MountainSenseFarm/1.0"},
        )
        data = resp.json()
    except Exception:
        return JSONResponse({"error": "Open Food Facts niet bereikbaar"}, status_code=503)

    if data.get("status") != 1:
        return JSONResponse({"error": "Product niet gevonden"}, status_code=404)

    product = data.get("product", {})
    name = product.get("product_name_nl") or product.get("product_name") or product.get("product_name_en") or ""
    brand = product.get("brands") or ""
    image_url = product.get("image_front_url") or product.get("image_url") or ""

    # Haal quantity en unit op uit quantity_string bijv. "400 g"
    qty_str = product.get("quantity") or ""
    qty_val = None
    unit_val = "stuks"
    if qty_str:
        import re
        m = re.match(r"([\d.,]+)\s*([a-zA-Z]+)", qty_str.strip())
        if m:
            try:
                qty_val = float(m.group(1).replace(",", "."))
            except ValueError:
                pass
            unit_val = m.group(2).lower()

    # Sla op in cache
    entry = models.ProductCache(
        barcode=barcode,
        name=name,
        brand=brand,
        quantity=qty_val,
        unit=unit_val,
        image_url=image_url,
        cached_at=datetime.datetime.utcnow(),
    )
    db.merge(entry)
    db.commit()

    return JSONResponse({
        "name": name,
        "brand": brand,
        "quantity": qty_val,
        "unit": unit_val,
        "image_url": image_url,
    })


# ── API: Shop items ─────────────────────────────────────────────────────────────

@app.get("/api/shop/items")
async def api_shop_items(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    items = db.query(models.ShopItem).filter(models.ShopItem.owner == user).all()
    return JSONResponse([{
        "id": i.id,
        "barcode": i.barcode,
        "name": i.name,
        "brand": i.brand,
        "quantity_per_unit": i.quantity_per_unit,
        "unit": i.unit,
        "image_url": i.image_url,
        "stock": i.stock,
        "houdbaar_tot": i.houdbaar_tot.isoformat() if i.houdbaar_tot else None,
        "date_added": i.date_added.isoformat() if i.date_added else None,
        "entered_by": i.entered_by,
    } for i in items])


@app.post("/api/shop/items")
async def api_shop_item_toevoegen(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = await request.json()
        name = str(body["name"]).strip()
        stock = int(body.get("stock", 1))
    except Exception:
        return JSONResponse({"error": "Ongeldige invoer"}, status_code=400)

    if not name:
        return JSONResponse({"error": "Productnaam is verplicht"}, status_code=400)

    barcode = body.get("barcode") or None
    brand = body.get("brand") or None
    quantity_per_unit = float(body.get("quantity_per_unit", 1) or 1)
    unit = str(body.get("unit") or "stuks")
    image_url = body.get("image_url") or None
    houdbaar_tot = None
    if body.get("houdbaar_tot"):
        try:
            houdbaar_tot = datetime.date.fromisoformat(body["houdbaar_tot"])
        except ValueError:
            return JSONResponse({"error": "Ongeldige THT datum"}, status_code=400)

    # Zoek bestaande THT-groep (zelfde barcode + zelfde THT)
    if barcode and houdbaar_tot:
        bestaand = db.query(models.ShopItem).filter(
            models.ShopItem.owner == user,
            models.ShopItem.barcode == barcode,
            models.ShopItem.houdbaar_tot == houdbaar_tot,
        ).first()
        if bestaand:
            bestaand.stock += stock
            db.commit()
            return JSONResponse({"id": bestaand.id, "merged": True, "stock": bestaand.stock})

    item = models.ShopItem(
        barcode=barcode,
        name=name,
        brand=brand,
        quantity_per_unit=quantity_per_unit,
        unit=unit,
        image_url=image_url,
        owner=user,
        stock=stock,
        houdbaar_tot=houdbaar_tot,
        date_added=datetime.date.today(),
        entered_by=user,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return JSONResponse({"id": item.id, "merged": False, "stock": item.stock})


@app.put("/api/shop/items/{item_id}")
async def api_shop_item_bewerken(item_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    item = db.query(models.ShopItem).filter(
        models.ShopItem.id == item_id,
        models.ShopItem.owner == user,
    ).first()
    if not item:
        return JSONResponse({"error": "Niet gevonden"}, status_code=404)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Ongeldige invoer"}, status_code=400)

    if "name" in body:
        item.name = str(body["name"]).strip()
    if "brand" in body:
        item.brand = body["brand"] or None
    if "quantity_per_unit" in body:
        item.quantity_per_unit = float(body["quantity_per_unit"] or 1)
    if "unit" in body:
        item.unit = str(body["unit"] or "stuks")
    if "stock" in body:
        item.stock = int(body["stock"])
    if "houdbaar_tot" in body:
        if body["houdbaar_tot"]:
            try:
                item.houdbaar_tot = datetime.date.fromisoformat(body["houdbaar_tot"])
            except ValueError:
                return JSONResponse({"error": "Ongeldige THT datum"}, status_code=400)
        else:
            item.houdbaar_tot = None
    if "image_url" in body:
        item.image_url = body["image_url"] or None

    db.commit()
    return JSONResponse({"succes": True})


@app.delete("/api/shop/items/{item_id}")
async def api_shop_item_verwijderen(item_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    item = db.query(models.ShopItem).filter(
        models.ShopItem.id == item_id,
        models.ShopItem.owner == user,
    ).first()
    if not item:
        return JSONResponse({"error": "Niet gevonden"}, status_code=404)
    if item.stock != 0:
        return JSONResponse({"error": "Kan alleen verwijderen als voorraad 0 is"}, status_code=400)

    db.delete(item)
    db.commit()
    return JSONResponse({"succes": True})


# ── API: Shop uitgifte ──────────────────────────────────────────────────────────

@app.post("/api/shop/uitgifte")
async def api_shop_uitgifte(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = await request.json()
        shop_item_id = int(body["shop_item_id"])
        quantity = int(body.get("quantity", 1))
    except Exception:
        return JSONResponse({"error": "Ongeldige invoer"}, status_code=400)

    item = db.query(models.ShopItem).filter(
        models.ShopItem.id == shop_item_id,
        models.ShopItem.owner == user,
    ).first()
    if not item:
        return JSONResponse({"error": "Niet gevonden"}, status_code=404)

    if item.stock < quantity:
        return JSONResponse({"error": "Onvoldoende voorraad."}, status_code=400)

    item.stock -= quantity
    uitgifte = models.ShopUitgifte(
        shop_item_id=shop_item_id,
        quantity=quantity,
        date=datetime.date.today(),
        entered_by=user,
    )
    db.add(uitgifte)
    db.commit()
    return JSONResponse({"succes": True, "stock": item.stock})


# ── API: Barcode lookup ─────────────────────────────────────────────────────────

@app.get("/api/shop/barcode/{barcode}")
async def api_shop_barcode(barcode: str, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    items = (
        db.query(models.ShopItem)
        .filter(
            models.ShopItem.owner == user,
            models.ShopItem.barcode == barcode,
            models.ShopItem.stock > 0,
        )
        .order_by(models.ShopItem.houdbaar_tot.asc().nullsfirst())
        .all()
    )

    return JSONResponse([{
        "id": i.id,
        "name": i.name,
        "brand": i.brand,
        "unit": i.unit,
        "quantity_per_unit": i.quantity_per_unit,
        "image_url": i.image_url,
        "stock": i.stock,
        "houdbaar_tot": i.houdbaar_tot.isoformat() if i.houdbaar_tot else None,
    } for i in items])


# ── API: Shop zoeken ────────────────────────────────────────────────────────────

@app.get("/api/shop/search")
async def api_shop_search(request: Request, db: Session = Depends(get_db), q: str = "", owner: str = None):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    if not q or len(q) < 2:
        return JSONResponse([])

    filter_owner = owner if owner else user
    items = (
        db.query(models.ShopItem)
        .filter(
            models.ShopItem.owner == filter_owner,
            (models.ShopItem.name.ilike(f"%{q}%") | models.ShopItem.brand.ilike(f"%{q}%")),
        )
        .order_by(models.ShopItem.name.asc())
        .all()
    )

    return JSONResponse([{
        "id": i.id,
        "name": i.name,
        "brand": i.brand,
        "unit": i.unit,
        "stock": i.stock,
        "houdbaar_tot": i.houdbaar_tot.isoformat() if i.houdbaar_tot else None,
        "owner": i.owner,
        "image_url": i.image_url,
    } for i in items])


# ── API: Gecombineerd zoeken (dashboard) ────────────────────────────────────────

@app.get("/api/search")
async def api_search(
    request: Request,
    db: Session = Depends(get_db),
    q: str = "",
    sources: str = "boerderij,eigen",
):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    if not q or len(q) < 2:
        return JSONResponse({"results": [], "q": q, "count": 0})

    sources_list = [s.strip() for s in sources.split(",") if s.strip()]
    today = datetime.date.today()
    cutoff = today + datetime.timedelta(days=30)
    andere = "hinke" if user.lower() == "maarten" else "maarten"
    results = []

    if "boerderij" in sources_list:
        entries = (
            db.query(models.HarvestEntry)
            .join(models.Product, models.HarvestEntry.product_id == models.Product.id)
            .join(models.Location, models.HarvestEntry.location_id == models.Location.id)
            .filter(models.HarvestEntry.uitgegeven == False)
            .filter(func.lower(models.Product.name).contains(q.lower()))
            .order_by(
                (models.HarvestEntry.houdbaar_tot == None).asc(),
                models.HarvestEntry.houdbaar_tot.asc(),
            )
            .limit(20)
            .all()
        )
        for e in entries:
            eenheid = e.product.eenheid.naam if e.product.eenheid else (e.product.unit or "")
            results.append({
                "bron": "boerderij",
                "id": e.id,
                "naam": e.product.name,
                "hoeveelheid": e.quantity,
                "eenheid": eenheid,
                "locatie": e.location.name,
                "houdbaar_tot": e.houdbaar_tot.strftime("%d-%m-%Y") if e.houdbaar_tot else None,
                "kort_houdbaar": bool(e.houdbaar_tot and e.houdbaar_tot <= cutoff),
                "stock": None,
                "scan_id": e.id,
            })

    for bron, owner in [("eigen", user), ("andere", andere)]:
        if bron not in sources_list:
            continue
        items = (
            db.query(models.ShopItem)
            .filter(models.ShopItem.owner == owner)
            .filter(
                func.lower(models.ShopItem.name).contains(q.lower())
                | func.lower(func.coalesce(models.ShopItem.brand, "")).contains(q.lower())
            )
            .order_by(
                (models.ShopItem.houdbaar_tot == None).asc(),
                models.ShopItem.houdbaar_tot.asc(),
            )
            .limit(20)
            .all()
        )
        for i in items:
            results.append({
                "bron": bron,
                "id": i.id,
                "naam": i.name,
                "hoeveelheid": i.stock,
                "eenheid": i.unit or "stuks",
                "locatie": None,
                "houdbaar_tot": i.houdbaar_tot.strftime("%d-%m-%Y") if i.houdbaar_tot else None,
                "kort_houdbaar": bool(i.houdbaar_tot and i.houdbaar_tot <= cutoff),
                "stock": i.stock,
                "scan_id": None,
            })

    return JSONResponse({
        "results": results,
        "q": q,
        "count": len(results),
        "andere": andere,
    })


# ── Winkelproduct bewerken (dedicated pagina) ────────────────────────────────────

@app.get("/winkel/{item_id}/edit")
async def winkel_item_edit(item_id: int, request: Request, db: Session = Depends(get_db),
                           error: str = None):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    item = db.query(models.ShopItem).filter(
        models.ShopItem.id == item_id,
        models.ShopItem.owner == user,
    ).first()
    if not item:
        return RedirectResponse("/winkel", status_code=302)

    error_msg = None
    if error == "heeft_uitgiftes":
        error_msg = "Dit product kan niet worden verwijderd omdat er uitgifte-records aan gekoppeld zijn."

    return templates.TemplateResponse(
        "winkel_item_edit.html",
        {"request": request, "user": user, "item": item, "error": error_msg},
    )


@app.post("/winkel/{item_id}/edit")
async def winkel_item_edit_post(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    brand: str = Form(default=""),
    quantity_per_unit: float = Form(default=1.0),
    unit: str = Form(default="stuks"),
    stock: int = Form(...),
    houdbaar_tot: str = Form(default=""),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    item = db.query(models.ShopItem).filter(
        models.ShopItem.id == item_id,
        models.ShopItem.owner == user,
    ).first()
    if not item:
        return RedirectResponse("/winkel", status_code=302)

    houdbaar_tot_date = None
    if houdbaar_tot.strip():
        try:
            houdbaar_tot_date = datetime.date.fromisoformat(houdbaar_tot.strip())
        except ValueError:
            pass

    item.name = name.strip()
    item.brand = brand.strip() or None
    item.quantity_per_unit = quantity_per_unit
    item.unit = unit.strip() or "stuks"
    item.stock = max(0, stock)
    item.houdbaar_tot = houdbaar_tot_date
    db.commit()
    return RedirectResponse("/winkel?success=bijgewerkt", status_code=302)


@app.post("/winkel/{item_id}/delete")
async def winkel_item_delete(item_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    item = db.query(models.ShopItem).filter(
        models.ShopItem.id == item_id,
        models.ShopItem.owner == user,
    ).first()
    if not item:
        return RedirectResponse("/winkel", status_code=302)

    if item.stock != 0:
        return RedirectResponse(f"/winkel/{item_id}/edit?error=stock_niet_nul", status_code=302)

    db.delete(item)
    db.commit()
    return RedirectResponse("/winkel?success=verwijderd", status_code=302)


# ── Winkel uitgifte bewerken ────────────────────────────────────────────────────

@app.get("/winkel/uitgifte/{uitgifte_id}/edit")
async def winkel_uitgifte_edit(uitgifte_id: int, request: Request, db: Session = Depends(get_db),
                                error: str = None):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    uitgifte = db.query(models.ShopUitgifte).filter(
        models.ShopUitgifte.id == uitgifte_id,
    ).join(models.ShopItem).filter(
        models.ShopItem.owner == user,
    ).first()
    if not uitgifte:
        return RedirectResponse("/beheer/mutaties?tab=winkel", status_code=302)

    error_msg = None
    if error == "onvoldoende_voorraad":
        error_msg = "Kan niet bewerken: onvoldoende voorraad voor de nieuwe hoeveelheid."

    return templates.TemplateResponse(
        "winkel_uitgifte_edit.html",
        {"request": request, "user": user, "uitgifte": uitgifte, "error": error_msg},
    )


@app.post("/winkel/uitgifte/{uitgifte_id}/edit")
async def winkel_uitgifte_edit_post(
    uitgifte_id: int,
    request: Request,
    db: Session = Depends(get_db),
    quantity: int = Form(...),
    date: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    uitgifte = db.query(models.ShopUitgifte).filter(
        models.ShopUitgifte.id == uitgifte_id,
    ).join(models.ShopItem).filter(
        models.ShopItem.owner == user,
    ).first()
    if not uitgifte:
        return RedirectResponse("/beheer/mutaties?tab=winkel", status_code=302)

    # Pas stock aan: verschil tussen nieuwe en oude hoeveelheid
    verschil = quantity - uitgifte.quantity
    item = uitgifte.shop_item
    if item.stock - verschil < 0:
        return RedirectResponse(
            f"/winkel/uitgifte/{uitgifte_id}/edit?error=onvoldoende_voorraad", status_code=302
        )

    item.stock -= verschil
    uitgifte.quantity = quantity
    try:
        uitgifte.date = datetime.date.fromisoformat(date)
    except ValueError:
        pass
    db.commit()
    return RedirectResponse("/beheer/mutaties?tab=winkel", status_code=302)


@app.post("/winkel/uitgifte/{uitgifte_id}/delete")
async def winkel_uitgifte_delete(uitgifte_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    uitgifte = db.query(models.ShopUitgifte).filter(
        models.ShopUitgifte.id == uitgifte_id,
    ).join(models.ShopItem).filter(
        models.ShopItem.owner == user,
    ).first()
    if not uitgifte:
        return RedirectResponse("/beheer/mutaties?tab=winkel", status_code=302)

    # Zet hoeveelheid terug in voorraad
    uitgifte.shop_item.stock += uitgifte.quantity
    db.delete(uitgifte)
    db.commit()
    return RedirectResponse("/beheer/mutaties?tab=winkel", status_code=302)


# ── Beheer: Mutaties logboek ────────────────────────────────────────────────────

@app.get("/beheer/mutaties")
async def beheer_mutaties(
    request: Request,
    db: Session = Depends(get_db),
    tab: str = "boerderij",
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    active_tab = tab if tab in ("boerderij", "winkel") else "boerderij"

    boerderij_mutaties = []
    winkel_mutaties = []

    if active_tab == "boerderij":
        entries = (
            db.query(models.HarvestEntry)
            .join(models.Product, models.HarvestEntry.product_id == models.Product.id)
            .join(models.Location, models.HarvestEntry.location_id == models.Location.id)
            .order_by(models.HarvestEntry.date.desc(), models.HarvestEntry.created_at.desc())
            .all()
        )
        for e in entries:
            eenheid = e.product.eenheid.naam if e.product.eenheid else (e.product.unit or "")
            boerderij_mutaties.append({
                "type": "registratie",
                "datum": e.date,
                "product": e.product.name,
                "locatie": e.location.name,
                "hoeveelheid": e.quantity,
                "eenheid": eenheid,
                "ontvanger": None,
                "tht": e.houdbaar_tot.strftime("%d-%m-%Y") if e.houdbaar_tot else None,
                "door": e.entered_by,
                "note": e.note,
                "id": e.id,
            })

        uitgiftes = (
            db.query(models.Uitgifte)
            .join(models.Product, models.Uitgifte.product_id == models.Product.id)
            .join(models.Location, models.Uitgifte.location_id == models.Location.id)
            .order_by(models.Uitgifte.date.desc(), models.Uitgifte.created_at.desc())
            .all()
        )
        for u in uitgiftes:
            eenheid = u.product.eenheid.naam if u.product.eenheid else (u.product.unit or "")
            boerderij_mutaties.append({
                "type": "uitgifte",
                "datum": u.date,
                "product": u.product.name,
                "locatie": u.location.name,
                "hoeveelheid": u.quantity,
                "eenheid": eenheid,
                "ontvanger": u.ontvanger,
                "tht": None,
                "door": u.entered_by,
                "note": u.note,
                "id": u.id,
            })

        boerderij_mutaties.sort(key=lambda x: x["datum"], reverse=True)

    else:  # winkel
        shop_uitgiftes = (
            db.query(models.ShopUitgifte)
            .join(models.ShopItem, models.ShopUitgifte.shop_item_id == models.ShopItem.id)
            .filter(models.ShopItem.owner == user)
            .order_by(models.ShopUitgifte.date.desc())
            .all()
        )
        for su in shop_uitgiftes:
            winkel_mutaties.append({
                "id": su.id,
                "datum": su.date,
                "product": su.shop_item.name,
                "brand": su.shop_item.brand,
                "hoeveelheid": su.quantity,
                "eenheid": su.shop_item.unit or "stuks",
                "door": su.entered_by,
            })

    return templates.TemplateResponse(
        "beheer_mutaties.html",
        {
            "request": request,
            "user": user,
            "tab": active_tab,
            "boerderij_mutaties": boerderij_mutaties,
            "winkel_mutaties": winkel_mutaties,
        },
    )


@app.get("/beheer/mutaties/export/boerderij")
async def beheer_mutaties_export_boerderij(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    entries = (
        db.query(models.HarvestEntry)
        .join(models.Product, models.HarvestEntry.product_id == models.Product.id)
        .join(models.Location, models.HarvestEntry.location_id == models.Location.id)
        .order_by(models.HarvestEntry.date.desc())
        .all()
    )
    uitgiftes = (
        db.query(models.Uitgifte)
        .join(models.Product, models.Uitgifte.product_id == models.Product.id)
        .join(models.Location, models.Uitgifte.location_id == models.Location.id)
        .order_by(models.Uitgifte.date.desc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Datum", "Type", "Product", "Locatie", "Hoeveelheid", "Eenheid", "Ontvanger/THT", "Door", "Notitie"])
    for e in entries:
        eenheid = e.product.eenheid.naam if e.product.eenheid else (e.product.unit or "")
        writer.writerow([e.date, "Registratie", e.product.name, e.location.name, e.quantity, eenheid,
                         e.houdbaar_tot.isoformat() if e.houdbaar_tot else "", e.entered_by, e.note or ""])
    for u in uitgiftes:
        eenheid = u.product.eenheid.naam if u.product.eenheid else (u.product.unit or "")
        writer.writerow([u.date, "Uitgifte", u.product.name, u.location.name, u.quantity, eenheid,
                         u.ontvanger, u.entered_by, u.note or ""])

    filename = f"boerderij_mutaties_{datetime.date.today().isoformat()}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/beheer/mutaties/export/winkel")
async def beheer_mutaties_export_winkel(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    shop_uitgiftes = (
        db.query(models.ShopUitgifte)
        .join(models.ShopItem, models.ShopUitgifte.shop_item_id == models.ShopItem.id)
        .filter(models.ShopItem.owner == user)
        .order_by(models.ShopUitgifte.date.desc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Datum", "Product", "Merk", "Aantal", "Eenheid", "Door"])
    for su in shop_uitgiftes:
        writer.writerow([su.date, su.shop_item.name, su.shop_item.brand or "",
                         su.quantity, su.shop_item.unit or "stuks", su.entered_by])

    filename = f"winkel_mutaties_{datetime.date.today().isoformat()}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Dagelijkse email: bijna verlopen producten ──────────────────────────────────

def _stuur_verlopen_email(to_email: str, username: str, items_boerderij: list, items_winkel: list):
    """Stuur dagelijkse waarschuwingsmail voor producten die binnen 7 dagen verlopen."""
    if not SMTP_HOST:
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Bijna verlopen producten - MountainSense Farm"
    msg["From"] = SMTP_FROM
    msg["To"] = to_email

    regels = [f"Hallo {username},\n", "De volgende producten verlopen binnen 7 dagen:\n"]

    if items_boerderij:
        regels.append("\nBoerderijproducten:")
        for item in items_boerderij:
            tht = item["houdbaar_tot"].strftime("%d-%m-%Y") if item["houdbaar_tot"] else "—"
            regels.append(f"  - {item['product']} ({item['locatie']}) — THT {tht}")

    if items_winkel:
        regels.append("\nWinkelproducten:")
        for item in items_winkel:
            tht = item["houdbaar_tot"].strftime("%d-%m-%Y") if item["houdbaar_tot"] else "—"
            regels.append(f"  - {item['name']} — {item['stock']} stuks — THT {tht}")

    regels.append(f"\nBekijk alle bijna verlopen producten op: {APP_URL}/verlopen")
    regels.append("\nMet vriendelijke groet,\nMountainSense Farm")

    msg.attach(MIMEText("\n".join(regels), "plain", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, to_email, msg.as_string())
    except Exception as e:
        logging.error(f"SMTP fout dagelijkse mail ({to_email}): {e}")


async def _dagelijkse_verlopen_check():
    """APScheduler job: stuur per gebruiker een email voor producten die binnen 7 dagen verlopen."""
    db = database.SessionLocal()
    try:
        today = datetime.date.today()
        cutoff_7 = today + datetime.timedelta(days=7)

        gebruikers = db.query(models.User).filter(models.User.email != None).all()
        for gebruiker in gebruikers:
            if not gebruiker.email:
                continue

            # Boerderij: HarvestEntries die verlopen binnen 7 dagen
            boerderij_entries = (
                db.query(models.HarvestEntry)
                .join(models.Product, models.HarvestEntry.product_id == models.Product.id)
                .join(models.Location, models.HarvestEntry.location_id == models.Location.id)
                .filter(
                    models.HarvestEntry.entered_by == gebruiker.username,
                    models.HarvestEntry.uitgegeven == False,
                    models.HarvestEntry.houdbaar_tot != None,
                    models.HarvestEntry.houdbaar_tot >= today,
                    models.HarvestEntry.houdbaar_tot <= cutoff_7,
                )
                .all()
            )
            items_boerderij = [
                {
                    "product": e.product.name,
                    "locatie": e.location.name,
                    "houdbaar_tot": e.houdbaar_tot,
                }
                for e in boerderij_entries
            ]

            # Winkel: ShopItems die verlopen binnen 7 dagen
            winkel_items = (
                db.query(models.ShopItem)
                .filter(
                    models.ShopItem.owner == gebruiker.username,
                    models.ShopItem.stock > 0,
                    models.ShopItem.houdbaar_tot != None,
                    models.ShopItem.houdbaar_tot >= today,
                    models.ShopItem.houdbaar_tot <= cutoff_7,
                )
                .all()
            )
            items_winkel = [
                {
                    "name": i.name,
                    "stock": i.stock,
                    "houdbaar_tot": i.houdbaar_tot,
                }
                for i in winkel_items
            ]

            if items_boerderij or items_winkel:
                _stuur_verlopen_email(
                    to_email=gebruiker.email,
                    username=gebruiker.username,
                    items_boerderij=items_boerderij,
                    items_winkel=items_winkel,
                )
    finally:
        db.close()


# Start APScheduler
_scheduler = AsyncIOScheduler(timezone="Europe/Amsterdam")
_scheduler.add_job(
    _dagelijkse_verlopen_check,
    CronTrigger(hour=7, minute=0, timezone="Europe/Amsterdam"),
    id="dagelijkse_verlopen_check",
    replace_existing=True,
)
_scheduler.start()
