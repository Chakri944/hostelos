import os
import calendar
from datetime import date, datetime
from decimal import Decimal
import httpx
from sqlalchemy.orm import Session
from sqlalchemy import func
from .models import Resident, Invoice, Payment, ReminderLog

def month_key(day: date) -> str:
    return day.strftime("%Y-%m")

def month_due_date(year: int, month: int, due_day: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(max(int(due_day), 1), last_day))

def ensure_monthly_invoices(db: Session, today: date):
    key = month_key(today)
    residents = db.query(Resident).filter(Resident.status == "Active").all()
    created = 0
    for resident in residents:
        exists = db.query(Invoice).filter(
            Invoice.resident_id == resident.id, Invoice.billing_month == key
        ).first()
        if not exists:
            due = month_due_date(today.year, today.month, resident.rent_due_day or 5)
            db.add(Invoice(resident_id=resident.id, billing_month=key,
                           amount=resident.monthly_rent, due_date=due, status="Pending"))
            created += 1
    if created:
        db.commit()
    return created

def invoice_balance(db: Session, invoice: Invoice) -> Decimal:
    paid = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.invoice_id == invoice.id
    ).scalar() or 0
    # Legacy payments without invoice_id are intentionally not auto-allocated.
    return max(Decimal("0"), Decimal(str(invoice.amount)) - Decimal(str(paid)))

def due_reminder_settings(db: Session):
    # Editable defaults: 3 days before, on due date, 3 days overdue, then weekly.
    from .models import ReminderSetting
    row = db.query(ReminderSetting).first()
    if not row:
        row = ReminderSetting(days_before=3, send_on_due=True, first_overdue_days=3,
                             repeat_every_days=7, enabled=True)
        db.add(row)
        db.commit()
    return row

async def send_whatsapp(phone: str, message: str):
    token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    template = os.getenv("WHATSAPP_TEMPLATE_NAME", "rent_due_reminder").strip()
    language = os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en").strip()
    if not token or not phone_id:
        return False, None, "WhatsApp credentials are not configured"
    # Business-initiated WhatsApp notifications must use an approved template.
    # Template parameters: resident name, amount, due date, status/payment instruction.
    parts = message.split("|")
    params = [{"type": "text", "text": p.strip()} for p in parts]
    payload = {
        "messaging_product": "whatsapp", "to": phone, "type": "template",
        "template": {"name": template, "language": {"code": language},
                     "components": [{"type": "body", "parameters": params}]}
    }
    url = f"https://graph.facebook.com/v22.0/{phone_id}/messages"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=payload,
                headers={"Authorization": f"Bearer {token}"})
        data = response.json()
        if response.is_success:
            msg_id = (data.get("messages") or [{}])[0].get("id")
            return True, msg_id, None
        return False, None, str(data.get("error", data))[:500]
    except Exception as exc:
        return False, None, str(exc)[:500]

def reminder_type_for(today: date, due: date, settings):
    delta = (due - today).days
    if delta == settings.days_before:
        return "Before due"
    if delta == 0 and settings.send_on_due:
        return "Due today"
    if delta < 0:
        overdue = -delta
        if overdue == settings.first_overdue_days:
            return "Overdue"
        if overdue > settings.first_overdue_days and settings.repeat_every_days > 0:
            if (overdue - settings.first_overdue_days) % settings.repeat_every_days == 0:
                return "Overdue follow-up"
    return None

async def run_daily_reminders(db: Session, today: date | None = None):
    today = today or date.today()
    created = ensure_monthly_invoices(db, today)
    settings = due_reminder_settings(db)
    if not settings.enabled:
        return {"invoices_created": created, "active_invoices": 0, "eligible": 0,
                "sent": 0, "failed": 0, "skipped": 0,
                "reasons": {"automation_disabled": 1}}
    sent = failed = skipped = eligible = 0
    invoices = db.query(Invoice).join(Resident).filter(Resident.status == "Active").all()
    reasons = {"no_active_invoices": 0, "reminders_disabled": 0,
               "already_paid": 0, "not_scheduled_today": 0, "already_attempted": 0}
    for invoice in invoices:
        resident = invoice.resident
        if not resident.reminder_enabled:
            skipped += 1
            reasons["reminders_disabled"] += 1
            continue
        balance = invoice_balance(db, invoice)
        if balance <= 0:
            invoice.status = "Paid"
            skipped += 1
            reasons["already_paid"] += 1
            continue
        invoice.status = "Overdue" if today > invoice.due_date else "Pending"
        kind = reminder_type_for(today, invoice.due_date, settings)
        if not kind:
            skipped += 1
            reasons["not_scheduled_today"] += 1
            continue
        eligible += 1
        already = db.query(ReminderLog).filter(
            ReminderLog.invoice_id == invoice.id,
            ReminderLog.scheduled_for == today,
            ReminderLog.reminder_type == kind,
            ReminderLog.status.in_(["Sent", "Queued"])
        ).first()
        if already:
            skipped += 1
            reasons["already_attempted"] += 1
            continue
        phone = "".join(ch for ch in resident.phone if ch.isdigit())
        if len(phone) == 10:
            phone = "91" + phone
        due_text = invoice.due_date.strftime("%d %b %Y")
        # Body template placeholders: name, amount, due date, balance.
        message = f"{resident.full_name}|₹{balance:.2f}|{due_text}|₹{balance:.2f}"
        log = ReminderLog(resident_id=resident.id, invoice_id=invoice.id,
            scheduled_for=today, reminder_type=kind, recipient=phone,
            message=message, status="Queued")
        db.add(log)
        db.commit()
        ok, provider_id, error = await send_whatsapp(phone, message)
        log.status = "Sent" if ok else "Failed"
        log.provider_message_id = provider_id
        log.error = error
        log.sent_at = datetime.now() if ok else None
        db.commit()
        if ok: sent += 1
        else: failed += 1
    db.commit()
    return {"invoices_created": created, "active_invoices": len(invoices),
            "eligible": eligible, "sent": sent, "failed": failed,
            "skipped": skipped, "reasons": reasons}
