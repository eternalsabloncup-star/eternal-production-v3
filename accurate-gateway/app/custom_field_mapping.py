"""Owner-approved Accurate custom-field mapping foundation (Slice 1M).

Live Step 48 evidence: header/line ``charField*`` values exist but companion
labels are absent on the transaction payload. Semantic mapping is therefore
**BLOCKED** until Accurate field-definition metadata or Owner-approved config
is supplied.

This module never invents slot meanings from unlabeled values, product names,
colors, or categories.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

FieldScope = Literal["header", "line"]
MappedKind = Literal[
    "expedition",
    "delivery_zone",
    "buffer",
    "order_priority",
    "production_process",
    "color",
]


@dataclass(frozen=True)
class CustomFieldMappingRule:
    scope: FieldScope
    slot: str  # e.g. charField3
    kind: MappedKind
    label_aliases: tuple[str, ...]
    provenance: str  # metadata source / owner approval id


# Empty until Owner-approved metadata is registered. Do not hardcode Live slots.
APPROVED_RULES: tuple[CustomFieldMappingRule, ...] = ()

MAPPING_STATUS = "BLOCKED"
MAPPING_BLOCK_REASON = (
    "Live detail exposes unlabeled charField values; Accurate field-definition "
    "metadata / owner-approved configuration not available in this environment."
)


def mapping_status() -> dict[str, Any]:
    return {
        "status": MAPPING_STATUS,
        "reason": MAPPING_BLOCK_REASON,
        "approved_rule_count": len(APPROVED_RULES),
        "scopes": ["header", "line"],
        "requires": [
            "documented_accurate_field_metadata_or_owner_config",
            "no_unlabeled_value_inference",
            "no_sales_creator_fallback",
        ],
    }


def resolve_approved_slot(
    *,
    scope: FieldScope,
    slot: str,
    companion_label: str | None,
) -> MappedKind | None:
    """Return mapped kind only when an approved rule + label prove the slot."""
    if not companion_label or not str(companion_label).strip():
        return None
    label_norm = " ".join(str(companion_label).strip().lower().split())
    matches: list[MappedKind] = []
    for rule in APPROVED_RULES:
        if rule.scope != scope or rule.slot != slot:
            continue
        aliases = {" ".join(a.lower().split()) for a in rule.label_aliases}
        if label_norm in aliases or any(
            a in label_norm or label_norm in a for a in aliases
        ):
            matches.append(rule.kind)
    if len(matches) != 1:
        return None
    return matches[0]
