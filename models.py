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


class Eenheid(Base):
    __tablename__ = "eenheden"

    id = Column(Integer, primary_key=True, index=True)
    naam = Column(String, nullable=False)
    etiket_per_stuk = Column(Boolean, nullable=False, default=False)
    actief = Column(Boolean, default=True, nullable=False)

    producten = relationship("Product", back_populates="eenheid")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    unit = Column(String, nullable=True)  # legacy veld, blijft voor backward compat
    eenheid_id = Column(Integer, ForeignKey("eenheden.id"), nullable=True)
    active = Column(Boolean, default=True, nullable=False)

    eenheid = relationship("Eenheid", back_populates="producten")
    entries = relationship("HarvestEntry", back_populates="product")
    uitgiftes = relationship("Uitgifte", back_populates="product")


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    active = Column(Boolean, default=True, nullable=False)

    entries = relationship("HarvestEntry", back_populates="location")
    uitgiftes = relationship("Uitgifte", back_populates="location")


class Conserveringsmethode(Base):
    __tablename__ = "conserveringsmethoden"

    id = Column(Integer, primary_key=True, index=True)
    naam = Column(String, nullable=False)
    actief = Column(Boolean, default=True, nullable=False)

    entries = relationship("HarvestEntry", back_populates="conserveringsmethode")
    houdbaarheid_records = relationship("ProductHoudbaarheid", back_populates="conserveringsmethode")


class HarvestEntry(Base):
    __tablename__ = "harvest_entries"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    conserveringsmethode_id = Column(Integer, ForeignKey("conserveringsmethoden.id"), nullable=True)
    quantity = Column(Float, nullable=False)
    date = Column(String, nullable=False)  # ISO formaat: YYYY-MM-DD
    entered_by = Column(String, nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    houdbaar_tot = Column(Date, nullable=True)
    volgnummer = Column(Integer, nullable=True)
    gewijzigd_door = Column(String, nullable=True)
    gewijzigd_op = Column(DateTime, nullable=True)
    uitgegeven = Column(Boolean, default=False, nullable=False)
    uitgegeven_op = Column(DateTime, nullable=True)
    uitgegeven_aan = Column(String, nullable=True)

    product = relationship("Product", back_populates="entries")
    location = relationship("Location", back_populates="entries")
    conserveringsmethode = relationship("Conserveringsmethode", back_populates="entries")


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


class ProductHoudbaarheid(Base):
    __tablename__ = "product_houdbaarheid"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    conserveringsmethode_id = Column(Integer, ForeignKey("conserveringsmethoden.id"), nullable=True)
    houdbaarheid_maanden = Column(Integer, nullable=False)
    actief = Column(Boolean, default=True, nullable=False)

    product = relationship("Product")
    conserveringsmethode = relationship("Conserveringsmethode", back_populates="houdbaarheid_records")


class ShopItem(Base):
    __tablename__ = "shop_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    barcode = Column(String, nullable=True)
    name = Column(String, nullable=False)
    brand = Column(String, nullable=True)
    quantity_per_unit = Column(Float, default=1)
    unit = Column(String, default="stuks")
    image_url = Column(String, nullable=True)
    owner = Column(String, nullable=False)
    stock = Column(Integer, default=0)
    minimum_stock = Column(Integer, nullable=True)
    houdbaar_tot = Column(Date, nullable=True)
    date_added = Column(Date, default=datetime.date.today)
    entered_by = Column(String, nullable=False)


class ShopUitgifte(Base):
    __tablename__ = "shop_uitgiftes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_item_id = Column(Integer, ForeignKey("shop_items.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    date = Column(Date, default=datetime.date.today)
    entered_by = Column(String, nullable=False)

    shop_item = relationship("ShopItem")


class SharedList(Base):
    __tablename__ = "shared_lists"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token = Column(String, nullable=False, unique=True, index=True)
    owner = Column(String, nullable=False)
    list_data = Column(Text, nullable=False)  # JSON
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class ProductCache(Base):
    __tablename__ = "product_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    barcode = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=True)
    brand = Column(String, nullable=True)
    quantity = Column(Float, nullable=True)
    unit = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    cached_at = Column(DateTime, default=datetime.datetime.utcnow)
