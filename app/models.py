
from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Numeric, UniqueConstraint, Boolean, Text
from sqlalchemy.orm import relationship
from .database import Base

class Property(Base):
    __tablename__ = "properties"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    city = Column(String(80), nullable=False)
    address = Column(String(240))
    floors = relationship("Floor", back_populates="property", cascade="all, delete-orphan")
    rooms = relationship("Room", back_populates="property")

class Floor(Base):
    __tablename__ = "floors"
    id = Column(Integer, primary_key=True)
    name = Column(String(60), nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    property = relationship("Property", back_populates="floors")
    rooms = relationship("Room", back_populates="floor")

class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True)
    room_number = Column(String(20), nullable=False)
    room_type = Column(String(40), nullable=False, default="Shared")
    capacity = Column(Integer, nullable=False, default=1)
    monthly_rent = Column(Numeric(10,2), nullable=False, default=0)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    floor_id = Column(Integer, ForeignKey("floors.id"))
    property = relationship("Property", back_populates="rooms")
    floor = relationship("Floor", back_populates="rooms")
    beds = relationship("Bed", back_populates="room", cascade="all, delete-orphan")
    residents = relationship("Resident", back_populates="room")

class Bed(Base):
    __tablename__ = "beds"
    id = Column(Integer, primary_key=True)
    bed_number = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="Available")
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    room = relationship("Room", back_populates="beds")
    __table_args__ = (UniqueConstraint("room_id","bed_number",name="uq_bed_room_number"),)

class Resident(Base):
    __tablename__ = "residents"
    id = Column(Integer, primary_key=True)
    full_name = Column(String(120), nullable=False)
    phone = Column(String(20), nullable=False)
    monthly_rent = Column(Numeric(10,2), nullable=False)
    status = Column(String(20), nullable=False, default="Active")
    room_id = Column(Integer, ForeignKey("rooms.id"))
    bed_id = Column(Integer, ForeignKey("beds.id"))
    joining_date = Column(Date, nullable=True)
    checkout_date = Column(Date, nullable=True)
    rent_due_day = Column(Integer, nullable=False, default=5)
    reminder_enabled = Column(Boolean, nullable=False, default=True)
    room = relationship("Room", back_populates="residents")
    bed = relationship("Bed")
    cycles = relationship("RentCycle", back_populates="resident", cascade="all, delete-orphan")

class RentCycle(Base):
    __tablename__ = "rent_cycles"
    id = Column(Integer, primary_key=True)
    resident_id = Column(Integer, ForeignKey("residents.id"), nullable=False)
    cycle_number = Column(Integer, nullable=False)
    cycle_start = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    amount = Column(Numeric(10,2), nullable=False)
    status = Column(String(24), nullable=False, default="Pending")
    created_at = Column(DateTime, nullable=False)
    resident = relationship("Resident", back_populates="cycles")
    payments = relationship("Payment", back_populates="cycle")
    __table_args__ = (UniqueConstraint("resident_id","cycle_number",name="uq_rent_cycle_number"),)

class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    resident_id = Column(Integer, ForeignKey("residents.id"), nullable=False)
    cycle_id = Column(Integer, ForeignKey("rent_cycles.id"), nullable=True)
    amount = Column(Numeric(10,2), nullable=False)
    paid_on = Column(Date, nullable=False)
    method = Column(String(30), nullable=False)
    reference = Column(String(100))
    resident = relationship("Resident")
    cycle = relationship("RentCycle", back_populates="payments")

class ReminderLog(Base):
    __tablename__ = "reminder_logs"
    id = Column(Integer, primary_key=True)
    resident_id = Column(Integer, ForeignKey("residents.id"), nullable=False)
    cycle_id = Column(Integer, ForeignKey("rent_cycles.id"))
    scheduled_for = Column(Date, nullable=False)
    reminder_type = Column(String(30), nullable=False)
    recipient = Column(String(30), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default="Queued")
    provider_message_id = Column(String(120))
    error = Column(String(500))
    sent_at = Column(DateTime)

class ReminderSetting(Base):
    __tablename__ = "reminder_settings"
    id = Column(Integer, primary_key=True)
    days_before = Column(Integer, nullable=False, default=3)
    first_overdue_days = Column(Integer, nullable=False, default=3)
    repeat_every_days = Column(Integer, nullable=False, default=7)
    enabled = Column(Boolean, nullable=False, default=False)
