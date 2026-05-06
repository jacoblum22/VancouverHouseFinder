from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Listing, RawDocument


class SiteScraper(ABC):
    name: str

    @abstractmethod
    async def fetch(self) -> list[RawDocument]:
        """Fetch raw documents (HTML/JSON) for this site."""
        raise NotImplementedError

    @abstractmethod
    def parse(self, docs: list[RawDocument]) -> list[Listing]:
        """Parse raw documents into normalized listings."""
        raise NotImplementedError

