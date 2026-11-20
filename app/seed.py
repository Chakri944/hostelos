from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from .models import Property, Floor, Room, Bed, Resident, Invoice, Payment

def ensure_beds(db: Session):
    for room in db.query(Room).all():
        if not room.beds:
            for n in range(1, room.capacity + 1):
                db.add(Bed(bed_number=f"B{n}", room_id=room.id, status="Available"))
    db.flush()
    for resident in db.query(Resident).filter(Resident.status == "Active", Resident.room_id.isnot(None), Resident.bed_id.is_(None)).all():
        candidate = db.query(Bed).filter(Bed.room_id == resident.room_id, Bed.status == "Available").first()
        if candidate:
            candidate.status = "Occupied"
            resident.bed_id = candidate.id
    db.commit()

def seed_demo_data(db: Session):
    if db.query(Property).first():
        ensure_beds(db)
        return

    prop = Property(name="Lakeview Residency", city="Hyderabad", address="Gaddiannaram, Hyderabad")
    db.add(prop)
    db.flush()
    floors = []
    for floor_name in ["Ground Floor", "First Floor", "Second Floor"]:
        floor = Floor(name=floor_name, property_id=prop.id)
        db.add(floor)
        floors.append(floor)
    db.flush()

    room_specs = [("101", 2, 6500, 0), ("102", 2, 6000, 0), ("103", 3, 7000, 0),
                  ("201", 2, 6500, 1), ("202", 3, 6000, 1), ("203", 2, 6500, 1)]
    rooms = []
    for number, capacity, rent, floor_idx in room_specs:
        room = Room(room_number=number, capacity=capacity, monthly_rent=Decimal(str(rent)),
                    room_type="Double Sharing" if capacity == 2 else "Triple Sharing",
                    property_id=prop.id, floor_id=floors[floor_idx].id)
        db.add(room)
        rooms.append(room)
    db.flush()

    for room in rooms:
        for n in range(1, room.capacity + 1):
            db.add(Bed(bed_number=f"B{n}", room_id=room.id, status="Available"))
    db.flush()

    people = [
        ("Aarav Sharma", "9876501001", 6500, 0),
        ("Rohan Kumar", "9876501002", 6000, 0),
        ("Aditya Reddy", "9876501003", 7000, 1),
        ("Karthik Rao", "9876501004", 6500, 1),
        ("Rahul Verma", "9876501005", 6000, 2),
        ("Nikhil Patil", "9876501006", 6500, 3),
        ("Varun Singh", "9876501007", 7000, 3),
        ("Sai Teja", "9876501008", 6000, 4),
        ("Arjun Das", "9876501009", 6500, 4),
        ("Manoj Kumar", "9876501010", 6000, 5),
    ]
    residents = []
    for name, phone, rent, room_idx in people:
        resident = Resident(full_name=name, phone=phone, monthly_rent=Decimal(str(rent)), room_id=rooms[room_idx].id)
        db.add(resident)
        residents.append(resident)
    db.flush()

    # Mark one bed occupied per seeded resident, preserving room capacity.
    for room in rooms:
        assigned = [r for r in residents if r.room_id == room.id]
        for bed, resident in zip(room.beds, assigned):
            bed.status = "Occupied"
            resident.bed_id = bed.id

    today = date.today()
    month_label = today.strftime("%B %Y")
    for i, resident in enumerate(residents):
        paid = i not in (2, 5, 6, 8)
        partial = i == 5
        status = "Paid" if paid else ("Partially paid" if partial else "Overdue")
        due = date(today.year, today.month, 5)
        db.add(Invoice(resident_id=resident.id, billing_month=month_label,
                       amount=resident.monthly_rent, due_date=due, status=status))
        if paid:
            db.add(Payment(resident_id=resident.id, amount=resident.monthly_rent,
                           paid_on=today - timedelta(days=(i % 8) + 1),
                           method=["UPI", "Bank transfer", "Cash"][i % 3],
                           reference=f"HOSTEL{i+1001}"))
        elif partial:
            db.add(Payment(resident_id=resident.id, amount=Decimal("3000.00"),
                           paid_on=today - timedelta(days=2), method="UPI", reference="UPI-PART-1006"))
    db.commit()
