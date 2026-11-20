
import calendar
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import func
from .models import Resident, RentCycle, Payment

def anchored_date(year: int, month: int, anchor_day: int) -> date:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(anchor_day, last))

def cycle_dates(joining: date, cycle_number: int):
    # Cycle 1 starts on joining date; next cycle uses original joining-day anchor.
    month_index = joining.month - 1 + (cycle_number - 1)
    year = joining.year + month_index // 12
    month = month_index % 12 + 1
    start = anchored_date(year, month, joining.day)
    next_index = month_index + 1
    next_year = joining.year + next_index // 12
    next_month = next_index % 12 + 1
    due = anchored_date(next_year, next_month, joining.day)
    return start, due

def cycle_paid(db, cycle):
    return Decimal(str(db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(Payment.cycle_id == cycle.id).scalar() or 0))

def cycle_balance(db, cycle):
    return max(Decimal("0"), Decimal(str(cycle.amount)) - cycle_paid(db, cycle))

def refresh_cycle_status(db, cycle, today=None):
    today = today or date.today()
    balance = cycle_balance(db, cycle)
    if balance <= 0: cycle.status = "Paid"
    elif balance < Decimal(str(cycle.amount)): cycle.status = "Partially paid"
    elif today > cycle.due_date: cycle.status = "Overdue"
    else: cycle.status = "Pending"
    return balance

def create_first_cycle(db, resident):
    joining = resident.joining_date or date.today()
    resident.joining_date = joining
    resident.rent_due_day = joining.day
    exists = db.query(RentCycle).filter_by(resident_id=resident.id, cycle_number=1).first()
    if not exists:
        start, due = cycle_dates(joining, 1)
        db.add(RentCycle(resident_id=resident.id, cycle_number=1,
                         cycle_start=start, due_date=due,
                         amount=resident.monthly_rent, status="Pending",
                         created_at=datetime.now()))
        # First full month's rent is payable immediately on joining.
        db.flush()
        first = db.query(RentCycle).filter_by(resident_id=resident.id, cycle_number=1).one()
        first.due_date = joining
    db.commit()

def ensure_current_and_next_cycles(db, today=None):
    """
    Ensure each active resident has all rent cycles through the current cycle
    plus exactly one upcoming cycle. Existing cycles are never duplicated.
    """
    today = today or date.today()
    residents = db.query(Resident).filter(Resident.status == "Active").all()
    created = 0

    for resident in residents:
        if not resident.joining_date:
            resident.joining_date = today
            resident.rent_due_day = today.day

        # Find the first cycle whose start date is still in the future.
        # That cycle is the one upcoming cycle to keep visible.
        target_number = 1
        while True:
            cycle_start, _ = cycle_dates(resident.joining_date, target_number)
            if cycle_start > today:
                break
            target_number += 1

        existing_numbers = {
            number for (number,) in db.query(RentCycle.cycle_number)
                .filter(RentCycle.resident_id == resident.id)
                .all()
        }

        # Create missing cycles only; repeated page loads remain idempotent.
        for number in range(1, target_number + 1):
            if number in existing_numbers:
                continue
            start, due = cycle_dates(resident.joining_date, number)
            db.add(RentCycle(
                resident_id=resident.id,
                cycle_number=number,
                cycle_start=start,
                due_date=(resident.joining_date if number == 1 else start),
                amount=resident.monthly_rent,
                status="Pending",
                created_at=datetime.now()
            ))
            created += 1

    db.commit()
    return created
