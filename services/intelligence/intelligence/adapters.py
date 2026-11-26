"""Adapter contract. No network-capable adapter is registered in INT-01."""
from typing import Protocol
from .models import Observation


class SourceAdapter(Protocol):
    source: str

    def collect(self) -> tuple[Observation, ...]:
        """Return a bounded batch with provenance; future adapters require authorization."""
        ...


class FixtureAdapter:
    source = "fixture"

    def collect(self) -> tuple[Observation, ...]:
        from datetime import datetime, timezone
        at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return (
            Observation(self.source, "demo-001", "Producto de prueba", "https://catalog.invalid/demo-001", at, "COP", 4990000),
            Observation(self.source, "demo-002", "Precio no informado", "https://catalog.invalid/demo-002", at, "COP", None),
        )
