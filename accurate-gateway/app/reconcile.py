"""Read-only list reconciliation — never claim atomic full universe lightly."""

from __future__ import annotations

from typing import Any


def reconcile_id_pages(
    pages: list[list[dict[str, Any]]],
    *,
    claimed_total: int | None,
    id_key: str = "accurate_id",
    page_count_claimed: int | None = None,
    failed_pages: int = 0,
    metadata_errors: int = 0,
    first_page_stable: bool | None = None,
) -> dict[str, Any]:
    """Count / dedupe ids across pages with census metadata fail-closed.

    ``census_scan_pass`` may be true when scanned unique ids match claimed total
    with zero duplicates/missing/metadata/page failures.

    ``full_universe_verified`` stays False unless an Owner-approved atomic snapshot
    flag is also set — Director Live G4B: census_scan_pass true, atomic not guaranteed.
    """
    ids: list[str] = []
    missing_id_rows = 0
    for page in pages:
        if not isinstance(page, list):
            metadata_errors += 1
            continue
        for row in page:
            if not isinstance(row, dict):
                metadata_errors += 1
                continue
            raw = row.get(id_key)
            if raw is None or str(raw).strip() == "":
                # Prefer internal id; fall back only for counting gaps.
                raw = row.get("id")
            if raw is None or str(raw).strip() == "":
                missing_id_rows += 1
                continue
            ids.append(str(raw).strip())
    unique = set(ids)
    dup = len(ids) - len(unique)
    scanned = len(ids)
    missing_vs_claimed = 0
    if claimed_total is not None:
        try:
            missing_vs_claimed = max(0, int(claimed_total) - len(unique))
        except (TypeError, ValueError):
            metadata_errors += 1
            claimed_total = None
    pages_seen = len(pages)
    page_count_ok = True
    if page_count_claimed is not None:
        try:
            page_count_ok = pages_seen <= int(page_count_claimed)
        except (TypeError, ValueError):
            page_count_ok = False
            metadata_errors += 1
    count_matches = (
        claimed_total is not None
        and len(unique) == int(claimed_total)
        and dup == 0
        and missing_id_rows == 0
        and missing_vs_claimed == 0
    )
    census_scan_pass = bool(
        count_matches
        and failed_pages == 0
        and metadata_errors == 0
        and page_count_ok
        and (first_page_stable is not False)
    )
    incomplete = (
        failed_pages > 0
        or metadata_errors > 0
        or dup > 0
        or missing_id_rows > 0
        or (claimed_total is not None and not count_matches)
        or first_page_stable is False
    )
    return {
        "scanned_rows": scanned,
        "row_count": scanned,
        "unique_ids": len(unique),
        "duplicate_ids": dup,
        "missing_ids": missing_id_rows + missing_vs_claimed,
        "missing_id_rows": missing_id_rows,
        "claimed_total": claimed_total,
        "page_count_claimed": page_count_claimed,
        "pages_seen": pages_seen,
        "failed_pages": failed_pages,
        "metadata_errors": metadata_errors,
        "first_page_stable": first_page_stable,
        "count_matches_claimed": count_matches,
        "census_scan_pass": census_scan_pass,
        # Atomic snapshot across multi-minute scans is not guaranteed (Director G4B).
        "atomic_snapshot_guaranteed": False,
        "full_universe_verified": False,
        "incomplete": incomplete,
        "fail_closed": True,
        "note": (
            "census_scan_pass≠atomic snapshot; full_universe_verified stays false "
            "without Owner atomic guarantee"
        ),
    }
