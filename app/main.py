
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from calendar import monthrange
from fastapi import FastAPI, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from .database import Base, engine, get_db
from .models import Property, Floor, Room, Bed, Resident, RentCycle, Payment
from .migrations import run_sqlite_migrations
from .billing import create_first_cycle, ensure_current_and_next_cycles, cycle_balance, refresh_cycle_status
import os
import sqlite3
import shutil
import hmac
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

BASE = Path(__file__).resolve().parent
APP_ENV = os.getenv("APP_ENV", "development").lower()
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
if APP_ENV == "production" and len(SESSION_SECRET) < 32:
    raise RuntimeError("Set SESSION_SECRET to a random value of at least 32 characters in the hosting environment.")
if not SESSION_SECRET:
    SESSION_SECRET = "local-development-only-change-before-deploying"
AUTH_SERIALIZER = URLSafeTimedSerializer(SESSION_SECRET, salt="hostelos-owner-login")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
app = FastAPI(title="HostelOS", version="2.0.0")
app.mount("/static", StaticFiles(directory=BASE/"static"), name="static")
templates = Jinja2Templates(directory=BASE/"templates")

@app.middleware("http")
async def owner_login_required(request: Request, call_next):
    path = request.url.path
    if path in ("/login", "/health") or path.startswith("/static/"):
        return await call_next(request)
    token = request.cookies.get("hostelos_owner_session", "")
    authenticated = False
    if token:
        try:
            payload = AUTH_SERIALIZER.loads(token, max_age=12 * 60 * 60)
            authenticated = payload.get("email") == ADMIN_EMAIL and bool(ADMIN_EMAIL)
        except (BadSignature, SignatureExpired):
            authenticated = False
    if not authenticated:
        return RedirectResponse(url="/login", status_code=303)
    return await call_next(request)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": request.query_params.get("error")})

@app.post("/login")
def login(email: str = Form(...), password: str = Form(...)):
    email_value = email.strip().lower()
    valid = bool(ADMIN_EMAIL and ADMIN_PASSWORD) and hmac.compare_digest(email_value, ADMIN_EMAIL) and hmac.compare_digest(password, ADMIN_PASSWORD)
    if not valid:
        return RedirectResponse("/login?error=1", status_code=303)
    token = AUTH_SERIALIZER.dumps({"email": ADMIN_EMAIL})
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("hostelos_owner_session", token, max_age=12 * 60 * 60,
                        httponly=True, secure=(APP_ENV == "production"),
                        samesite="lax", path="/")
    return response

@app.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("hostelos_owner_session", path="/")
    return response

@app.on_event("startup")
def startup():
    run_sqlite_migrations()
    Base.metadata.create_all(bind=engine)
    # Existing legacy rows are retained. Seed only an empty database.
    from .database import SessionLocal
    db = SessionLocal()
    try:
        if db.query(Property).count() == 0:
            p = Property(name="My Hostel", city="Hyderabad")
            db.add(p); db.flush()
            f = Floor(name="Ground Floor", property_id=p.id)
            db.add(f); db.commit()
        ensure_current_and_next_cycles(db)
    finally:
        db.close()

def money(v): return Decimal(str(v or 0))

@app.get("/backup")
def backup_page(request: Request):
    cloud_database = engine.dialect.name != "sqlite"
    return templates.TemplateResponse("backup.html", {"request": request, "active_page": "backup", "today": date.today(), "cloud_database": cloud_database})

@app.get("/backup/download")
def download_backup():
    if engine.dialect.name != "sqlite":
        raise HTTPException(status_code=409, detail="For cloud PostgreSQL, use the database provider's backup and recovery tools.")
    db_path = Path.cwd() / "hostelos.db"
    if not db_path.exists():
        raise HTTPException(status_code=404, detail="Database file not found")
    backup_dir = Path.cwd() / "backups"
    backup_dir.mkdir(exist_ok=True)
    snapshot = backup_dir / f"hostelos_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    source = sqlite3.connect(str(db_path))
    destination = sqlite3.connect(str(snapshot))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return FileResponse(path=str(snapshot), filename=snapshot.name, media_type="application/vnd.sqlite3")

@app.post("/backup/restore")
async def restore_backup(file: UploadFile = File(...)):
    if engine.dialect.name != "sqlite":
        raise HTTPException(status_code=409, detail="SQLite restore is disabled on cloud PostgreSQL.")
    if not file.filename or not file.filename.lower().endswith((".db", ".sqlite", ".sqlite3")):
        return RedirectResponse("/backup?error=filetype", 303)
    temp_path = Path.cwd() / "restore_upload.tmp"
    live_path = Path.cwd() / "hostelos.db"
    backup_dir = Path.cwd() / "backups"
    backup_dir.mkdir(exist_ok=True)
    size = 0
    try:
        with temp_path.open("wb") as target:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk: break
                size += len(chunk)
                if size > 100 * 1024 * 1024: raise ValueError("Backup exceeds 100 MB")
                target.write(chunk)
        with temp_path.open("rb") as uploaded:
            if size < 100 or uploaded.read(16) != b"SQLite format 3\\x00":
                raise ValueError("Not a SQLite database")
        check = sqlite3.connect(f"file:{temp_path.resolve()}?mode=ro", uri=True)
        try:
            integrity = check.execute("PRAGMA integrity_check").fetchone()
            tables = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if not integrity or integrity[0] != "ok" or not {"residents","rooms","rent_cycles","payments"}.issubset(tables):
                raise ValueError("Invalid HostelOS database")
        finally:
            check.close()
        if live_path.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(live_path, backup_dir / f"before_restore_{stamp}.db")
        engine.dispose()
        os.replace(temp_path, live_path)
        return RedirectResponse("/backup?restored=1", 303)
    except Exception:
        if temp_path.exists(): temp_path.unlink()
        return RedirectResponse("/backup?error=restore", 303)
    finally:
        await file.close()

@app.get("/")
def dashboard(request: Request, db: Session=Depends(get_db)):
    today = date.today()
    month_start = today.replace(day=1)
    collected = db.query(func.coalesce(func.sum(Payment.amount),0)).filter(Payment.paid_on >= month_start, Payment.paid_on <= today).scalar() or 0
    active = db.query(Resident).filter(Resident.status=="Active").count()
    cycles = db.query(RentCycle).join(Resident).filter(Resident.status=="Active").all()
    dues = Decimal("0"); due_count=0
    for c in cycles:
        bal = cycle_balance(db,c)
        if bal > 0:
            dues += bal
            if c.due_date <= today: due_count += 1
        refresh_cycle_status(db,c,today)
    db.commit()
    recent = db.query(Payment).options(joinedload(Payment.resident)).order_by(Payment.paid_on.desc(),Payment.id.desc()).limit(6).all()
    upcoming = db.query(RentCycle).options(joinedload(RentCycle.resident)).join(Resident).filter(Resident.status=="Active", RentCycle.due_date >= today).order_by(RentCycle.due_date).limit(6).all()
    return templates.TemplateResponse("dashboard.html", {"request":request,"active_page":"dashboard",
        "collected":money(collected),"dues":dues,"tenants":active,"fees_due":due_count,
        "recent":recent,"upcoming":upcoming,"today":today})

@app.get("/rooms")
def rooms_page(request:Request, db:Session=Depends(get_db)):
    properties=db.query(Property).all()
    rooms=db.query(Room).options(joinedload(Room.beds),joinedload(Room.floor),joinedload(Room.property)).order_by(Room.room_number).all()
    return templates.TemplateResponse("rooms.html",{"request":request,"active_page":"rooms","properties":properties,"rooms":rooms})

@app.post("/rooms")
def add_room(room_number:str=Form(...), property_id:int=Form(...), floor_name:str=Form("Ground Floor"),
             capacity:int=Form(...), room_type:str=Form("Shared"), db:Session=Depends(get_db)):
    prop=db.get(Property,property_id)
    if not prop or not room_number.strip() or capacity<1 or capacity>20:
        return RedirectResponse("/rooms?error=invalid",303)
    if db.query(Room).filter_by(property_id=property_id,room_number=room_number.strip()).first():
        return RedirectResponse("/rooms?error=duplicate",303)
    floor=db.query(Floor).filter_by(property_id=property_id,name=floor_name.strip()).first()
    if not floor:
        floor=Floor(name=floor_name.strip() or "Ground Floor",property_id=property_id); db.add(floor); db.flush()
    room=Room(room_number=room_number.strip(),property_id=property_id,floor_id=floor.id,
              capacity=capacity,room_type=room_type,monthly_rent=0)
    db.add(room); db.flush()
    for n in range(1,capacity+1): db.add(Bed(bed_number=f"B{n}",room_id=room.id,status="Available"))
    db.commit()
    return RedirectResponse("/rooms",303)

@app.post("/rooms/{room_id}/delete")
def remove_room(room_id:int,db:Session=Depends(get_db)):
    room=db.get(Room,room_id)
    if room and not db.query(Resident).filter(Resident.room_id==room_id,Resident.status=="Active").first():
        db.delete(room); db.commit()
    return RedirectResponse("/rooms",303)

@app.get("/tenants")
def tenants_page(request:Request, status:str="All", q:str="", room_id:int=None, db:Session=Depends(get_db)):
    query=db.query(Resident).options(joinedload(Resident.room),joinedload(Resident.bed))
    if status in ("Active", "Inactive"):
        query=query.filter(Resident.status==status)
    search_term=q.strip()
    if search_term:
        pattern=f"%{search_term}%"
        query=query.filter((Resident.full_name.ilike(pattern)) | (Resident.phone.ilike(pattern)))
    if room_id:
        query=query.filter(Resident.room_id==room_id)
    tenants=query.order_by(Resident.status,Resident.full_name).all()
    rooms=db.query(Room).options(joinedload(Room.beds),joinedload(Room.property)).order_by(Room.room_number).all()
    active_count=db.query(Resident).filter(Resident.status=="Active").count()
    former_count=db.query(Resident).filter(Resident.status=="Inactive").count()
    return templates.TemplateResponse("tenants.html",{"request":request,"active_page":"tenants","tenants":tenants,"rooms":rooms,"today_iso":date.today().isoformat(),"status_filter":status,"active_count":active_count,"former_count":former_count,"search_query":search_term,"selected_room_id":room_id})

@app.get("/tenants/{tenant_id}")
def tenant_history(tenant_id:int, request:Request, db:Session=Depends(get_db)):
    tenant=db.query(Resident).options(joinedload(Resident.room),joinedload(Resident.bed)).filter(Resident.id==tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    cycles=db.query(RentCycle).options(joinedload(RentCycle.payments)).filter(RentCycle.resident_id==tenant_id).order_by(RentCycle.cycle_number.desc()).all()
    total_paid=sum((Decimal(str(p.amount)) for c in cycles for p in c.payments), Decimal("0"))
    outstanding=sum((cycle_balance(db,c) for c in cycles), Decimal("0"))
    return templates.TemplateResponse("tenant_history.html",{"request":request,"active_page":"tenants","tenant":tenant,"cycles":cycles,"total_paid":total_paid,"outstanding":outstanding})

@app.post("/tenants")
def add_tenant(full_name:str=Form(...),phone:str=Form(...),joining_date:str=Form(...),
               monthly_rent:str=Form(...),room_id:int=Form(...),bed_id:int=Form(...),db:Session=Depends(get_db)):
    try:
        joined=date.fromisoformat(joining_date); rent=Decimal(monthly_rent)
        if rent<=0 or len("".join(x for x in phone if x.isdigit()))<10: raise ValueError()
    except (ValueError,InvalidOperation):
        return RedirectResponse("/tenants?error=invalid",303)
    bed=db.get(Bed,bed_id); room=db.get(Room,room_id)
    if not bed or not room or bed.room_id!=room.id or bed.status!="Available":
        return RedirectResponse("/tenants?error=bed",303)
    if joined>date.today(): return RedirectResponse("/tenants?error=future",303)
    tenant=Resident(full_name=full_name.strip(),phone=phone.strip(),joining_date=joined,
        rent_due_day=joined.day,monthly_rent=rent,status="Active",room_id=room.id,bed_id=bed.id)
    db.add(tenant); bed.status="Occupied"; db.flush()
    create_first_cycle(db,tenant)
    return RedirectResponse("/tenants",303)


@app.get("/tenants/{tenant_id}/edit")
def edit_tenant_page(tenant_id: int, request: Request, db: Session=Depends(get_db)):
    tenant = db.query(Resident).options(joinedload(Resident.room), joinedload(Resident.bed)).filter(Resident.id==tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    rooms = db.query(Room).options(joinedload(Room.beds), joinedload(Room.property)).order_by(Room.room_number).all()
    available_beds = []
    for room in rooms:
        for bed in room.beds:
            if bed.status == "Available" or (tenant.status == "Active" and bed.id == tenant.bed_id):
                available_beds.append({"id": bed.id, "room_id": room.id, "room_number": room.room_number, "bed_number": bed.bed_number, "status": bed.status})
    return templates.TemplateResponse("tenant_edit.html", {
        "request": request, "active_page": "tenants", "tenant": tenant,
        "rooms": rooms, "available_beds": available_beds, "today": date.today()
    })

@app.post("/tenants/{tenant_id}/edit")
def update_tenant(tenant_id: int, full_name: str=Form(...), phone: str=Form(...),
                 monthly_rent: str=Form(...), room_id: int=Form(None), bed_id: int=Form(None),
                 db: Session=Depends(get_db)):
    tenant = db.get(Resident, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    name = full_name.strip()
    phone_value = phone.strip()
    try:
        rent = Decimal(monthly_rent)
        if not name or len("".join(ch for ch in phone_value if ch.isdigit())) < 10 or rent <= 0:
            raise ValueError()
    except (ValueError, InvalidOperation):
        return RedirectResponse(f"/tenants/{tenant_id}/edit?error=invalid", 303)

    old_rent = Decimal(str(tenant.monthly_rent))
    tenant.full_name = name
    tenant.phone = phone_value
    tenant.monthly_rent = rent

    if tenant.status == "Active":
        new_bed = db.get(Bed, bed_id) if bed_id else None
        new_room = db.get(Room, room_id) if room_id else None
        if not new_bed or not new_room or new_bed.room_id != new_room.id:
            return RedirectResponse(f"/tenants/{tenant_id}/edit?error=bed", 303)
        if new_bed.status != "Available" and new_bed.id != tenant.bed_id:
            return RedirectResponse(f"/tenants/{tenant_id}/edit?error=bed", 303)
        if tenant.bed_id != new_bed.id:
            old_bed = db.get(Bed, tenant.bed_id) if tenant.bed_id else None
            if old_bed:
                old_bed.status = "Available"
            new_bed.status = "Occupied"
            tenant.bed_id = new_bed.id
            tenant.room_id = new_room.id

        # Preserve all existing/current rent history. Only unstarted future cycles
        # without payments inherit the updated monthly rent.
        if rent != old_rent:
            future_cycles = db.query(RentCycle).filter(
                RentCycle.resident_id == tenant.id,
                RentCycle.cycle_start > date.today()
            ).all()
            for cycle in future_cycles:
                if not db.query(Payment.id).filter(Payment.cycle_id == cycle.id).first():
                    cycle.amount = rent

    db.commit()
    return RedirectResponse(f"/tenants/{tenant_id}", 303)

@app.post("/tenants/{tenant_id}/checkout")
def checkout(tenant_id:int,db:Session=Depends(get_db)):
    tenant=db.get(Resident,tenant_id)
    if tenant and tenant.status=="Active":
        tenant.status="Inactive"
        tenant.checkout_date=date.today()
        if tenant.bed_id:
            bed=db.get(Bed,tenant.bed_id)
            if bed: bed.status="Available"
        db.commit()
    return RedirectResponse("/tenants",303)

@app.get("/fees")
def fees_page(request:Request, q:str="", room_id:int=None, db:Session=Depends(get_db)):
    ensure_current_and_next_cycles(db)
    query=db.query(RentCycle).options(joinedload(RentCycle.resident).joinedload(Resident.room),joinedload(RentCycle.payments)).join(Resident)
    search_term=q.strip()
    if search_term:
        pattern=f"%{search_term}%"
        query=query.filter((Resident.full_name.ilike(pattern)) | (Resident.phone.ilike(pattern)))
    if room_id:
        query=query.filter(Resident.room_id==room_id)
    cycles=query.order_by(RentCycle.due_date.desc()).all()
    rows=[]
    for c in cycles:
        bal=cycle_balance(db,c); refresh_cycle_status(db,c)
        if bal > 0:
            rows.append({"cycle":c,"balance":bal})
    rooms=db.query(Room).order_by(Room.room_number).all()
    db.commit()
    return templates.TemplateResponse("fees.html",{"request":request,"active_page":"fees","rows":rows,"rooms":rooms,"search_query":search_term,"selected_room_id":room_id})

@app.post("/fees/{cycle_id}/status")
def update_cycle_status(cycle_id: int, status: str = Form(...), db: Session = Depends(get_db)):
    cycle = db.get(RentCycle, cycle_id)
    if not cycle:
        raise HTTPException(status_code=404, detail="Rent cycle not found")

    if status == "Paid":
        balance = cycle_balance(db, cycle)
        if balance > 0:
            db.add(Payment(
                resident_id=cycle.resident_id,
                cycle_id=cycle.id,
                amount=balance,
                paid_on=date.today(),
                method="Manual",
                reference="Marked paid by admin"
            ))
    elif status == "Not Paid":
        # The admin's explicit Not Paid selection resets this cycle to unpaid.
        # Remove payments allocated to this cycle so the displayed balance is accurate.
        db.query(Payment).filter(Payment.cycle_id == cycle.id).delete(synchronize_session=False)
    else:
        raise HTTPException(status_code=400, detail="Invalid payment status")

    db.flush()
    refresh_cycle_status(db, cycle)
    db.commit()
    return RedirectResponse("/fees", status_code=303)

@app.get("/health")
def health():
    return {"app":"HostelOS","status":"ok","version":"1.0.0"}
