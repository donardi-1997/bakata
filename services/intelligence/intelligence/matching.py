"""Deterministic, bounded pairwise proposals; never merge products automatically."""
from dataclasses import dataclass
from enum import Enum
from itertools import combinations
from .normalization import NormalizedProduct
from .references import ref


class MatchKind(str, Enum):
    GTIN = "gtin-review"
    BRAND_MODEL = "brand-model-review"
    TITLE = "title-review"
    CONFLICT = "conflict"
    NONE = "no-match"


@dataclass(frozen=True, slots=True)
class MatchProposal:
    left: NormalizedProduct
    right: NormalizedProduct
    kind: MatchKind
    reasons: tuple[str, ...]

    @property
    def reviewable(self) -> bool:
        return self.kind in (MatchKind.GTIN, MatchKind.BRAND_MODEL, MatchKind.TITLE)


def compare(left: NormalizedProduct, right: NormalizedProduct) -> MatchProposal:
    if left.identity == right.identity:
        raise ValueError("Compare latest observations of distinct source identities")
    if left.identity[0] == right.identity[0]:
        return MatchProposal(left, right, MatchKind.NONE, ("same-source-distinct-id",))
    conflicts = []
    for name, a, b in (("gtin", left.gtin14, right.gtin14),
                       ("brand", left.brand_key, right.brand_key),
                       ("model", left.model_key, right.model_key)):
        if a is not None and b is not None and a != b:
            conflicts.append(name + "-conflict")
    a, b = dict(left.variants), dict(right.variants)
    conflicts.extend("variant-conflict:" + key for key in sorted(a.keys() & b.keys()) if a[key] != b[key])
    if conflicts:
        return MatchProposal(left, right, MatchKind.CONFLICT, tuple(conflicts))
    missing = ("variant-coverage-incomplete",) if not a or not b or a.keys() != b.keys() else ()
    if left.gtin14 is not None and left.gtin14 == right.gtin14:
        return MatchProposal(left, right, MatchKind.GTIN, ("same-validated-gtin",) + missing)
    if (left.brand_key and left.brand_key == right.brand_key and left.model_key
            and left.model_key == right.model_key):
        return MatchProposal(left, right, MatchKind.BRAND_MODEL, ("same-brand-and-model",) + missing)
    if left.title_key and left.title_key == right.title_key:
        return MatchProposal(left, right, MatchKind.TITLE, ("normalized-title-only",) + missing)
    return MatchProposal(left, right, MatchKind.NONE, ("insufficient-evidence",))


def propose(products: tuple[NormalizedProduct, ...]) -> tuple[MatchProposal, ...]:
    if len(products) > 200:
        raise ValueError("Comparison limited to 200 distinct source identities")
    if len({item.identity for item in products}) != len(products):
        raise ValueError("Use latest observation per source identity")
    ordered = sorted(products, key=lambda item: item.identity)
    return tuple(result for left, right in combinations(ordered, 2)
                 if (result := compare(left, right)).reviewable)


@dataclass(frozen=True, slots=True)
class ReviewedLink:
    left_key: tuple[str, str, str]
    right_key: tuple[str, str, str]
    review_ref: str

    def __post_init__(self):
        ref(self.review_ref)


def approve_pair(proposal: MatchProposal, review_ref: str, *, variant_equivalence_confirmed: bool) -> ReviewedLink:
    """One reviewed pair only. No transitive grouping or persistent approval yet."""
    if not proposal.reviewable or variant_equivalence_confirmed is not True:
        raise ValueError("Explicit variant equivalence and reviewable evidence required")
    ref(review_ref)
    # A title match is a search hint, never sufficient for approving equivalence.
    if proposal.kind is MatchKind.TITLE:
        raise ValueError("Add verified brand/model or GTIN evidence before approval")
    actual = compare(proposal.left, proposal.right)
    if actual != proposal:
        raise ValueError("Proposal does not match current evidence")
    return ReviewedLink(proposal.left.observation.key, proposal.right.observation.key, review_ref)
