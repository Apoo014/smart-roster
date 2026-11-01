import os
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, Index, create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker


# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL")

# SQLite for local development
if not DATABASE_URL:
    if os.getenv("VERCEL") == "1":
        raise RuntimeError(
            "DATABASE_URL must be configured on Vercel."
        )

    DATABASE_URL = "sqlite:///./roster.db"


# Support PostgreSQL connection strings
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql://",
        1
    )


# Database engine
_args = (
    {"check_same_thread": False}
    if DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(
    DATABASE_URL,
    connect_args=_args,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Pod(Base):
    __tablename__ = "pods"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)
    lead_id = Column(Integer, nullable=True)   # employee id (plain int avoids a circular FK with employees.pod_id)


class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True)
    name = Column(String(120), nullable=False)
    email = Column(String(160))
    status = Column(String(12), default="ACTIVE")           # ACTIVE / INACTIVE
    pod_id = Column(Integer, ForeignKey("pods.id"), nullable=True)
    daily_capacity = Column(Integer, default=2)             # max distinct brands per day


class Brand(Base):
    __tablename__ = "brands"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True, nullable=False)
    status = Column(String(12), default="ACTIVE")
    pod_id = Column(Integer, ForeignKey("pods.id"), nullable=True)


class Process(Base):
    __tablename__ = "processes"
    id = Column(Integer, primary_key=True)
    name = Column(String(60), unique=True, nullable=False)
    description = Column(String(200))


class Assignment(Base):
    """Many-to-many: which employee handles which process of which brand."""
    __tablename__ = "assignments"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    process_id = Column(Integer, ForeignKey("processes.id"), nullable=False)
    __table_args__ = (UniqueConstraint("employee_id", "brand_id", "process_id", name="uq_assignment"),)


class WorkingRule(Base):
    """Brand/process operating calendar + minimum staffing (also acts as CoverageRequirement)."""
    __tablename__ = "working_rules"
    id = Column(Integer, primary_key=True)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    process_id = Column(Integer, ForeignKey("processes.id"), nullable=False)
    calendar_type = Column(String(30), default="SUNDAY_HOLIDAY_OFF")
    min_staff = Column(Integer, default=1)
    __table_args__ = (UniqueConstraint("brand_id", "process_id", name="uq_rule"),)


class WeeklyOff(Base):
    __tablename__ = "weekly_offs"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    weekday = Column(Integer, nullable=False)               # 0 = Monday ... 6 = Sunday
    __table_args__ = (UniqueConstraint("employee_id", "weekday", name="uq_weekly_off"),)


class Leave(Base):
    __tablename__ = "leaves"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    leave_type = Column(String(30), default="Casual")       # Casual / Sick / Comp-off
    reason = Column(String(200))
    status = Column(String(12), default="PENDING")          # PENDING / APPROVED / REJECTED


class Holiday(Base):
    __tablename__ = "holidays"
    id = Column(Integer, primary_key=True)
    date = Column(Date, unique=True, nullable=False)
    name = Column(String(120), nullable=False)


class Roster(Base):
    __tablename__ = "rosters"
    id = Column(Integer, primary_key=True)
    month = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    status = Column(String(20), default="DRAFT")            # DRAFT / PENDING_APPROVAL / PUBLISHED
    generated_at = Column(DateTime, default=datetime.utcnow)
    note = Column(Text)
    __table_args__ = (UniqueConstraint("month", "year", name="uq_roster_month"),)


class RosterEntry(Base):
    __tablename__ = "roster_entries"
    id = Column(Integer, primary_key=True)
    roster_id = Column(Integer, ForeignKey("rosters.id"), nullable=False)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    process_id = Column(Integer, ForeignKey("processes.id"), nullable=False)
    date = Column(Date, nullable=False)
    status = Column(String(2), nullable=False)              # W O L H C X
    manual = Column(Boolean, default=False)
    cover = Column(Boolean, default=False)
    __table_args__ = (Index("ix_entry_roster_date", "roster_id", "date"),
                      Index("ix_entry_roster_emp", "roster_id", "employee_id"))


class Conflict(Base):
    __tablename__ = "conflicts"
    id = Column(Integer, primary_key=True)
    roster_id = Column(Integer, ForeignKey("rosters.id"), nullable=False)
    date = Column(Date)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=True)
    process_id = Column(Integer, ForeignKey("processes.id"), nullable=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    type = Column(String(30), nullable=False)
    severity = Column(String(10), nullable=False)
    description = Column(Text)
    suggestion = Column(Text)
    backup_ids = Column(String(60), default="")
    status = Column(String(14), default="OPEN")             # OPEN / ACKNOWLEDGED
    __table_args__ = (Index("ix_conflict_roster", "roster_id"),)
