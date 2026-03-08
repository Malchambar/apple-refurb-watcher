from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class PollRun(Base):
    __tablename__ = "arw_poll_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parser_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_products_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    relevant_products_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    observations: Mapped[list["ListingObservation"]] = relationship(back_populates="poll_run")


class ProductConfig(Base):
    __tablename__ = "arw_product_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title_normalized: Mapped[str | None] = mapped_column(String(512), nullable=True)
    chip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cpu_cores: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gpu_cores: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_title_example: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    listings: Mapped[list["Listing"]] = relationship(back_populates="product_config")


class Listing(Base):
    __tablename__ = "arw_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    product_config_id: Mapped[int] = mapped_column(ForeignKey("arw_product_configs.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    price_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    disappeared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_known_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    product_config: Mapped[ProductConfig] = relationship(back_populates="listings")
    observations: Mapped[list["ListingObservation"]] = relationship(back_populates="listing")


class ListingObservation(Base):
    __tablename__ = "arw_listing_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    poll_run_id: Mapped[int] = mapped_column(ForeignKey("arw_poll_runs.id"), index=True, nullable=False)
    listing_id: Mapped[int] = mapped_column(ForeignKey("arw_listings.id"), index=True, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    price_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False)

    poll_run: Mapped[PollRun] = relationship(back_populates="observations")
    listing: Mapped[Listing] = relationship(back_populates="observations")


class AppState(Base):
    __tablename__ = "arw_app_state"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
