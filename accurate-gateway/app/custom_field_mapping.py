"""Owner-approved Accurate custom-field mapping (Slice 1N).

Provenance: Owner Accurate Online configuration screenshots for Eternal Sales
Order — Karakter/Field ordinal (not value similarity).

Active (owner_accurate_configuration):
  Header charField3 → delivery_zone (Zona Pengiriman)
  Header charField4 → order_priority (Status Pesanan)
  Header charField5 → buffer (Buffer / Non-Buffer)
  Line   charField1 → production_process (Proses)
  Line   charField2 → color (Warna)

Still blocked: expedition, sales (never from created_by_user).
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

OWNER_PROVENANCE = "owner_accurate_configuration"


@dataclass(frozen=True)
class CustomFieldMappingRule:
    scope: FieldScope
    slot: str  # e.g. charField3
    kind: MappedKind
    label_aliases: tuple[str, ...]
    provenance: str


APPROVED_RULES: tuple[CustomFieldMappingRule, ...] = (
    CustomFieldMappingRule(
        scope="header",
        slot="charField3",
        kind="delivery_zone",
        label_aliases=("zona pengiriman", "zona", "delivery zone"),
        provenance=OWNER_PROVENANCE,
    ),
    CustomFieldMappingRule(
        scope="header",
        slot="charField4",
        kind="order_priority",
        label_aliases=("status pesanan", "order priority", "prioritas"),
        provenance=OWNER_PROVENANCE,
    ),
    CustomFieldMappingRule(
        scope="header",
        slot="charField5",
        kind="buffer",
        label_aliases=("buffer / non-buffer", "buffer/non-buffer", "buffer", "buffer stock"),
        provenance=OWNER_PROVENANCE,
    ),
    CustomFieldMappingRule(
        scope="line",
        slot="charField1",
        kind="production_process",
        label_aliases=("proses", "proses barang", "production process"),
        provenance=OWNER_PROVENANCE,
    ),
    CustomFieldMappingRule(
        scope="line",
        slot="charField2",
        kind="color",
        label_aliases=("warna", "warna barang", "color"),
        provenance=OWNER_PROVENANCE,
    ),
)


def _validate_approved_rules(rules: tuple[CustomFieldMappingRule, ...]) -> None:
    """Reject duplicate scope+slot or conflicting scope+kind mappings."""
    seen_slots: set[tuple[str, str]] = set()
    seen_kinds: set[tuple[str, str]] = set()
    for rule in rules:
        slot_key = (rule.scope, rule.slot)
        if slot_key in seen_slots:
            raise ValueError(
                f"duplicate custom-field mapping for {rule.scope}:{rule.slot}"
            )
        seen_slots.add(slot_key)
        kind_key = (rule.scope, rule.kind)
        if kind_key in seen_kinds:
            raise ValueError(
                f"conflicting custom-field kind {rule.scope}:{rule.kind}"
            )
        seen_kinds.add(kind_key)
        if rule.kind == "expedition":
            raise ValueError("expedition mapping is not Owner-approved — leave blocked")


_validate_approved_rules(APPROVED_RULES)

MAPPING_STATUS = "PARTIAL"
MAPPING_BLOCK_REASON = (
    "Owner-approved slots active for zone/status/buffer/process/color; "
    "expedition and sales remain unverified (no creator fallback)."
)


def mapping_status() -> dict[str, Any]:
    return {
        "status": MAPPING_STATUS,
        "reason": MAPPING_BLOCK_REASON,
        "approved_rule_count": len(APPROVED_RULES),
        "provenance": OWNER_PROVENANCE,
        "scopes": ["header", "line"],
        "active_kinds": sorted({r.kind for r in APPROVED_RULES}),
        "blocked_kinds": ["expedition", "sales"],
        "requires": [
            "owner_accurate_configuration_for_active_slots",
            "no_sales_creator_fallback",
            "no_expedition_slot_inference",
        ],
        "rules": [
            {
                "scope": r.scope,
                "slot": r.slot,
                "kind": r.kind,
                "provenance": r.provenance,
            }
            for r in APPROVED_RULES
        ],
    }


def _norm_label(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _label_agrees(rule: CustomFieldMappingRule, companion_label: str | None) -> bool:
    """If a companion label is present, it must match the approved aliases."""
    if companion_label is None or not str(companion_label).strip():
        return True  # Owner ordinal applies when Live omits labels
    label_norm = _norm_label(companion_label)
    aliases = {_norm_label(a) for a in rule.label_aliases}
    if label_norm in aliases:
        return True
    return any(a in label_norm or label_norm in a for a in aliases if a)


def resolve_approved_slot(
    *,
    scope: FieldScope,
    slot: str,
    companion_label: str | None = None,
) -> MappedKind | None:
    """Return mapped kind for an Owner-approved scope+slot.

    Companion labels are optional on Live payloads. When present they must agree
    with approved aliases; when absent, Owner ordinal still applies.
    """
    matches = [r for r in APPROVED_RULES if r.scope == scope and r.slot == slot]
    if len(matches) != 1:
        return None
    rule = matches[0]
    if not _label_agrees(rule, companion_label):
        return None
    return rule.kind


def rule_for_kind(*, scope: FieldScope, kind: MappedKind) -> CustomFieldMappingRule | None:
    matches = [r for r in APPROVED_RULES if r.scope == scope and r.kind == kind]
    if len(matches) != 1:
        return None
    return matches[0]


def companion_label_for_slot(raw: dict[str, Any], slot: str) -> str | None:
    """Read Accurate companion label for a charFieldN slot when present."""
    if not slot.startswith("charField"):
        return None
    suffix = slot[len("charField") :]
    if not suffix.isdigit():
        return None
    i = suffix
    for key in (
        f"charField{i}Name",
        f"charField{i}Label",
        f"charField{i}Title",
        f"customField{i}Name",
        f"customField{i}Label",
    ):
        val = raw.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def approved_raw_value(
    raw: dict[str, Any],
    *,
    scope: FieldScope,
    kind: MappedKind,
) -> str | None:
    """Return the raw Accurate slot value for an approved kind, or None."""
    rule = rule_for_kind(scope=scope, kind=kind)
    if rule is None:
        return None
    label = companion_label_for_slot(raw, rule.slot)
    if not _label_agrees(rule, label):
        return None
    slot = rule.slot
    candidates = [raw.get(slot)]
    if slot.startswith("charField"):
        i = slot[len("charField") :]
        candidates.append(raw.get(f"customField{i}"))
    for val in candidates:
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    return None
