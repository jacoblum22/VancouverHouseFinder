from __future__ import annotations

from .models import Listing, SearchCriteria


def apply_criteria(listings: list[Listing], criteria: SearchCriteria) -> list[Listing]:
    """Keep listings that pass every criterion we can verify.

    When a field is None we cannot verify, so we keep the listing rather than
    silently discard potentially valid results.
    """
    result: list[Listing] = []
    for listing in listings:
        if listing.price_cad is not None and listing.price_cad <= 0:
            continue
        if listing.price_cad is not None and listing.price_cad > criteria.max_rent_cad:
            continue
        if listing.bedrooms is not None and listing.bedrooms < criteria.min_bedrooms:
            continue
        if (
            criteria.available_before is not None
            and listing.availability_date is not None
            and listing.availability_date > criteria.available_before
        ):
            continue
        result.append(listing)
    return result
