from __future__ import annotations
from datetime import datetime
from typing import List, Optional

from sqlalchemy import String, Integer, Date, ForeignKey, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

# 1. Modern Declarative Base
class Base(DeclarativeBase):
    pass

class Search(Base):
    __tablename__ = 'searches'
    
    # Mapped[type] explicitly tells your IDE/type-checker the Python type
    id: Mapped[int] = mapped_column(primary_key=True)
    origin: Mapped[str] = mapped_column(String(100), nullable=False)
    destination: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Note: datetime.now is passed as a function (no parentheses)
    created_at: Mapped[Date] = mapped_column(Date, default=datetime.now)

    # Link to the results (List of PriceHistory objects)
    prices: Mapped[List["PriceTimeSeries"]] = relationship(
        "PriceTimeSeries", back_populates="search", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint(
            'origin', 'destination',
            name='_search_params_uc'
        ),
    )

class PriceTimeSeries(Base):
    __tablename__ = 'price_time_series'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    search_id: Mapped[int] = mapped_column(ForeignKey('searches.id'))
    
    # Specifics of the actual flight found
    departure_date: Mapped[Date] = mapped_column(Date, nullable=False)
    price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    scraped_at: Mapped[Date] = mapped_column(Date, default=datetime.now)

    # Relationship back to the parent search
    search: Mapped["Search"] = relationship("Search", back_populates="prices")


# --- Database Setup ---
DATABASE = "flight_price_database.db"
engine = create_engine(f'sqlite:///{DATABASE}', echo=False)

# This creates the tables if they don't exist
Base.metadata.create_all(engine)

# Session factory for use in your scraper
Session = sessionmaker(bind=engine)