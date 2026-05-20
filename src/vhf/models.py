from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class SearchCriteria(BaseModel):
    max_rent_cad: int = 6600
    city: str = "Vancouver"
    min_bedrooms: int = 4
    available_before: date | None = date(2026, 9, 1)


class RawDocument(BaseModel):
    source: str
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    url: HttpUrl
    content_type: str | None = None
    body: str


class Listing(BaseModel):
    source: str
    source_listing_id: str | None = None
    url: HttpUrl
    title: str | None = None
    price_cad: int | None = None
    bedrooms: float | None = None
    bathrooms: float | None = None
    availability_date: date | None = None
    address_text: str | None = None
    neighborhood: str | None = None
    description: str | None = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)

    # filled during later stages
    dedupe_key: str | None = None
    status: Literal["active", "inactive"] = "active"
    transit_minutes_to_ubc: int | None = None
    latitude: float | None = None
    longitude: float | None = None

