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

import bcrypt
from typing import Optional
from fastapi import FastAPI, Request, Depends, Form
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
            "voorraad_totaal": voorraad_totaal,
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
async def admin(
    request: Request,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    products = db.query(models.Product).order_by(models.Product.active.desc(), models.Product.name).all()
    locations = db.query(models.Location).order_by(models.Location.active.desc(), models.Location.name).all()
    ontvangers = db.query(models.Ontvanger).order_by(models.Ontvanger.actief.desc(), models.Ontvanger.naam).all()
    eenheden = db.query(models.Eenheid).order_by(models.Eenheid.actief.desc(), models.Eenheid.naam).all()
    actieve_eenheden = [e for e in eenheden if e.actief]

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "user": user,
            "products": products,
            "locations": locations,
            "ontvangers": ontvangers,
            "eenheden": eenheden,
            "actieve_eenheden": actieve_eenheden,
            "success": success,
            "error": error,
        },
    )


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
    return RedirectResponse("/admin?success=ontvanger_added", status_code=302)


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
    return RedirectResponse("/admin", status_code=302)


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
    return RedirectResponse("/admin", status_code=302)


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
    return RedirectResponse("/admin?success=eenheid_added", status_code=302)


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
    return RedirectResponse("/admin", status_code=302)


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
    return RedirectResponse("/admin", status_code=302)


# ── Product bewerken / verwijderen ─────────────────────────────────────────────

@app.get("/admin/product/{product_id}/edit")
async def admin_edit_product(product_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        return RedirectResponse("/admin", status_code=302)

    eenheden = db.query(models.Eenheid).filter(models.Eenheid.actief == True).order_by(models.Eenheid.naam).all()
    return templates.TemplateResponse(
        "admin_edit_product.html",
        {"request": request, "user": user, "product": product, "eenheden": eenheden},
    )


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
    return RedirectResponse("/admin?success=product_updated", status_code=302)


@app.post("/admin/product/{product_id}/delete")
async def admin_delete_product(product_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        return RedirectResponse("/admin", status_code=302)

    heeft_entries = db.query(models.HarvestEntry).filter(models.HarvestEntry.product_id == product_id).first()
    if heeft_entries:
        return RedirectResponse("/admin?error=product_heeft_entries", status_code=302)

    db.delete(product)
    db.commit()
    return RedirectResponse("/admin?success=product_deleted", status_code=302)


# ── Locatie bewerken / verwijderen ─────────────────────────────────────────────

@app.get("/admin/location/{location_id}/edit")
async def admin_edit_location(location_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    location = db.query(models.Location).filter(models.Location.id == location_id).first()
    if not location:
        return RedirectResponse("/admin", status_code=302)

    return templates.TemplateResponse(
        "admin_edit_location.html",
        {"request": request, "user": user, "location": location},
    )


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
    return RedirectResponse("/admin?success=location_updated", status_code=302)


@app.post("/admin/location/{location_id}/delete")
async def admin_delete_location(location_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    location = db.query(models.Location).filter(models.Location.id == location_id).first()
    if not location:
        return RedirectResponse("/admin", status_code=302)

    heeft_entries = db.query(models.HarvestEntry).filter(models.HarvestEntry.location_id == location_id).first()
    heeft_uitgiftes = db.query(models.Uitgifte).filter(models.Uitgifte.location_id == location_id).first()
    if heeft_entries or heeft_uitgiftes:
        return RedirectResponse("/admin?error=location_heeft_registraties", status_code=302)

    db.delete(location)
    db.commit()
    return RedirectResponse("/admin?success=location_deleted", status_code=302)


# ── Ontvanger bewerken / verwijderen ───────────────────────────────────────────

@app.get("/admin/ontvanger/{ontvanger_id}/edit")
async def admin_edit_ontvanger(ontvanger_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    ontvanger = db.query(models.Ontvanger).filter(models.Ontvanger.id == ontvanger_id).first()
    if not ontvanger:
        return RedirectResponse("/admin", status_code=302)

    return templates.TemplateResponse(
        "admin_edit_ontvanger.html",
        {"request": request, "user": user, "ontvanger": ontvanger},
    )


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
    return RedirectResponse("/admin?success=ontvanger_updated", status_code=302)


@app.post("/admin/ontvanger/{ontvanger_id}/delete")
async def admin_delete_ontvanger(ontvanger_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    ontvanger = db.query(models.Ontvanger).filter(models.Ontvanger.id == ontvanger_id).first()
    if not ontvanger:
        return RedirectResponse("/admin", status_code=302)

    heeft_uitgiftes = db.query(models.Uitgifte).filter(models.Uitgifte.ontvanger == ontvanger.naam).first()
    if heeft_uitgiftes:
        return RedirectResponse("/admin?error=ontvanger_heeft_uitgiftes", status_code=302)

    db.delete(ontvanger)
    db.commit()
    return RedirectResponse("/admin?success=ontvanger_deleted", status_code=302)


# ── Eenheid bewerken / verwijderen ─────────────────────────────────────────────

@app.get("/admin/eenheid/{eenheid_id}/edit")
async def admin_edit_eenheid(eenheid_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    eenheid = db.query(models.Eenheid).filter(models.Eenheid.id == eenheid_id).first()
    if not eenheid:
        return RedirectResponse("/admin", status_code=302)

    return templates.TemplateResponse(
        "admin_edit_eenheid.html",
        {"request": request, "user": user, "eenheid": eenheid},
    )


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
    return RedirectResponse("/admin?success=eenheid_updated", status_code=302)


@app.post("/admin/eenheid/{eenheid_id}/delete")
async def admin_delete_eenheid(eenheid_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    eenheid = db.query(models.Eenheid).filter(models.Eenheid.id == eenheid_id).first()
    if not eenheid:
        return RedirectResponse("/admin", status_code=302)

    heeft_producten = db.query(models.Product).filter(models.Product.eenheid_id == eenheid_id).first()
    if heeft_producten:
        return RedirectResponse("/admin?error=eenheid_heeft_producten", status_code=302)

    db.delete(eenheid)
    db.commit()
    return RedirectResponse("/admin?success=eenheid_deleted", status_code=302)


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
    producten = db.query(models.Product).filter(models.Product.active == True).order_by(models.Product.name).all()
    conserveringsmethoden = db.query(models.Conserveringsmethode).filter(models.Conserveringsmethode.actief == True).order_by(models.Conserveringsmethode.naam).all()
    alle_conserveringsmethoden = db.query(models.Conserveringsmethode).order_by(models.Conserveringsmethode.naam).all()

    return templates.TemplateResponse(
        "beheer_houdbaarheid.html",
        {
            "request": request,
            "user": user,
            "records": records,
            "producten": producten,
            "conserveringsmethoden": conserveringsmethoden,
            "alle_conserveringsmethoden": alle_conserveringsmethoden,
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
async def beheer_conserveringsmethode_edit(methode_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    methode = db.query(models.Conserveringsmethode).filter(models.Conserveringsmethode.id == methode_id).first()
    if not methode:
        return RedirectResponse("/beheer/houdbaarheid", status_code=302)

    in_gebruik = db.query(models.HarvestEntry).filter(
        models.HarvestEntry.conserveringsmethode_id == methode_id
    ).count() > 0 or db.query(models.ProductHoudbaarheid).filter(
        models.ProductHoudbaarheid.conserveringsmethode_id == methode_id
    ).count() > 0

    return templates.TemplateResponse(
        "beheer_conserveringsmethode_edit.html",
        {"request": request, "user": user, "methode": methode, "in_gebruik": in_gebruik},
    )


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

    return templates.TemplateResponse(
        "beheer_geschiedenis.html",
        {
            "request": request,
            "user": user,
            "tab": tab if tab in ("registraties", "uitgiftes") else "registraties",
            "registraties": registraties,
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
