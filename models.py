import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, Date
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False, unique=True, index=True)
    hashed_password = Column(String, nullable=False)
    email = Column(String, nullable=True, unique=True)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String, nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False, nullable=False)

    user = relationship("User")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    unit = Column(String, nullable=False)
    active = Column(Boolean, default=True, nullable=False)

    entries = relationship("HarvestEntry", back_populates="product")
    uitgiftes = relationship("Uitgifte", back_populates="product")


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    active = Column(Boolean, default=True, nullable=False)

    entries = relationship("HarvestEntry", back_populates="location")
    uitgiftes = relationship("Uitgifte", back_populates="location")


class HarvestEntry(Base):
    __tablename__ = "harvest_entries"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    quantity = Column(Float, nullable=False)
    date = Column(String, nullable=False)  # ISO formaat: YYYY-MM-DD
    entered_by = Column(String, nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    houdbaar_tot = Column(Date, nullable=True)
    volgnummer = Column(Integer, nullable=True)
    gewijzigd_door = Column(String, nullable=True)
    gewijzigd_op = Column(DateTime, nullable=True)

    product = relationship("Product", back_populates="entries")
    location = relationship("Location", back_populates="entries")


class Ontvanger(Base):
    __tablename__ = "ontvangers"

    id = Column(Integer, primary_key=True, index=True)
    naam = Column(String, nullable=False)
    actief = Column(Boolean, default=True, nullable=False)


class Uitgifte(Base):
    __tablename__ = "uitgiftes"

    id = Column(Integer, primary_key=True, index=True)
    harvest_entry_id = Column(Integer, ForeignKey("harvest_entries.id"), nullable=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    quantity = Column(Float, nullable=False)
    ontvanger = Column(String, nullable=False)
    date = Column(String, nullable=False)  # ISO formaat: YYYY-MM-DD
    entered_by = Column(String, nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    product = relationship("Product", back_populates="uitgiftes")
    location = relationship("Location", back_populates="uitgiftes")
