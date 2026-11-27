"""Conservative comparison hints. Original observations are never changed."""
from dataclasses import dataclass
import re
import unicodedata
from .models import Observation


def _text(value: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("Invalid comparison attribute")
    if any(unicodedata.category(c).startswith("C") for c in value):
        raise ValueError("Control or invisible format character")
    return value


def normalize_label(value: str) -> str:
    # Accent folding is for search hints only, not for identity.
    value = unicodedata.normalize("NFKD", _text(value, 300).casefold())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in value).split())


def normalize_code(value: str) -> str:
    # Keep punctuation, leading zeros and model suffixes.
    return " ".join(unicodedata.normalize("NFC", _text(value, 128)).casefold().split())


def normalize_gtin(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9]{8}|[0-9]{12}|[0-9]{13}|[0-9]{14})", value):
        raise ValueError("Invalid GTIN format")
    if not any(c != "0" for c in value):
        raise ValueError("Zero GTIN")
    total = sum(int(digit) * (3 if i % 2 == 0 else 1) for i, digit in enumerate(reversed(value[:-1])))
    if (10 - total % 10) % 10 != int(value[-1]):
        raise ValueError("Invalid GTIN check digit")
    return value.zfill(14)


@dataclass(frozen=True, slots=True)
class ReviewedAttributes:
    """Explicit evidence annotation for one exact observation, not inferred from title."""
    observation_key: tuple[str, str, str]
    evidence_ref: str
    brand: str | None = None
    model: str | None = None
    gtin: str | None = None
    variants: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        if not isinstance(self.observation_key, tuple) or len(self.observation_key) != 3:
            raise ValueError("Expected observation key")
        _text(self.evidence_ref, 128)
        if self.brand is not None:
            _text(self.brand, 128)
        if self.model is not None:
            _text(self.model, 128)
        if self.gtin is not None:
            normalize_gtin(self.gtin)
        if not isinstance(self.variants, tuple) or len(self.variants) > 20:
            raise ValueError("Invalid variant attributes")
        keys = set()
        for name, value in self.variants:
            key = normalize_code(name)
            normalize_code(value)
            if key in keys:
                raise ValueError("Duplicate variant attribute")
            keys.add(key)


@dataclass(frozen=True, slots=True)
class NormalizedProduct:
    observation: Observation
    title_key: str
    brand_key: str | None
    model_key: str | None
    gtin14: str | None
    variants: tuple[tuple[str, str], ...]
    evidence_ref: str | None

    @property
    def identity(self) -> tuple[str, str]:
        return self.observation.source, self.observation.external_id


def normalize_product(observation: Observation, attributes: ReviewedAttributes | None = None) -> NormalizedProduct:
    if attributes is not None and attributes.observation_key != observation.key:
        raise ValueError("Attribute evidence belongs to another observation")
    return NormalizedProduct(
        observation, normalize_label(observation.title),
        normalize_code(attributes.brand) if attributes and attributes.brand is not None else None,
        normalize_code(attributes.model) if attributes and attributes.model is not None else None,
        normalize_gtin(attributes.gtin) if attributes and attributes.gtin is not None else None,
        tuple(sorted((normalize_code(k), normalize_code(v)) for k, v in attributes.variants)) if attributes else (),
        attributes.evidence_ref if attributes else None,
    )


def latest_observations(rows: tuple[Observation, ...]) -> tuple[Observation, ...]:
    """Build a comparison view; retain all original history in the caller/store."""
    if len(rows) > 1000:
        raise ValueError("Comparison input exceeds 1000 observations")
    seen = {}
    latest = {}
    for row in rows:
        if row.key in seen and seen[row.key] != row:
            raise ValueError("Conflicting observations for same key")
        seen[row.key] = row
        identity = row.source, row.external_id
        if identity not in latest or row.observed_at > latest[identity].observed_at:
            latest[identity] = row
    return tuple(latest[key] for key in sorted(latest))
