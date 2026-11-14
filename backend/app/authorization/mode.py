"""Workflow authorization mode gates and Director-visible status.

Does not activate enforced by itself. Default remains legacy. Never hides an
active mode or invents Director privileges.
"""
from __future__ import annotations

from app.authorization.catalog import MAPPING_REVIEW_REQUIRED
from app.authorization.workflow_map import WORKFLOW, PAYROLL, INBOX


def enforced_startup_allowed(settings) -> None:
    """Refuse unsafe process start. Call from create_app only."""
    mode = settings.v3_workflow_authorization
    if mode not in {"legacy", "enforced"}:
        raise RuntimeError("Unknown workflow authorization mode")
    if mode != "enforced":
        return
    if not settings.v3_settings_enabled:
        raise RuntimeError(
            "V3_WORKFLOW_AUTHORIZATION=enforced requires V3_SETTINGS_ENABLED=true"
        )
    if settings.app_env == "test":
        return
    if (settings.v3_workflow_enforced_approval_ref or "").strip():
        return
    raise RuntimeError(
        "V3_WORKFLOW_AUTHORIZATION=enforced outside APP_ENV=test requires "
        "V3_WORKFLOW_ENFORCED_APPROVAL_REF (Owner-attested cutover reference). "
        "Leave mode=legacy until Director approval and inventory are clear."
    )


def approval_ref_configured(settings) -> bool:
    return bool((settings.v3_workflow_enforced_approval_ref or "").strip())


def authorization_status(
    settings,
    *,
    bootstrapped: bool | None = None,
    inventory_summary: dict | None = None,
) -> dict:
    """Public, non-secret status for Direktur. Never echoes approval ref text."""
    mode = settings.v3_workflow_authorization
    settings_on = bool(settings.v3_settings_enabled)
    approval = approval_ref_configured(settings)
    test_sandbox = settings.app_env == "test"
    can_start_enforced = settings_on and (test_sandbox or approval)
    blockers: list[str] = []
    if not settings_on:
        blockers.append("V3_SETTINGS_ENABLED is false — Settings & Permission belum aktif di server.")
    if bootstrapped is False:
        blockers.append("Director bootstrap belum selesai — grup sistem Direktur belum ada.")
    if mode == "legacy":
        blockers.append(
            "V3_WORKFLOW_AUTHORIZATION=legacy — workflow tetap memakai izin legacy; "
            "grant Settings belum memutus akses produksi."
        )
    if mode == "enforced" and not can_start_enforced:
        blockers.append(
            "enforced tidak boleh start: butuh Settings aktif dan "
            "(APP_ENV=test atau V3_WORKFLOW_ENFORCED_APPROVAL_REF)."
        )
    if not test_sandbox and not approval and mode != "enforced":
        blockers.append(
            "Persetujuan cutover produksi belum tercatat "
            "(V3_WORKFLOW_ENFORCED_APPROVAL_REF kosong)."
        )
    review = sorted(MAPPING_REVIEW_REQUIRED.keys())
    if inventory_summary is not None:
        if not inventory_summary.get("cutover_review_clear"):
            blockers.append(
                "Inventory cutover belum clear "
                f"(blocking_user_ids={inventory_summary.get('blocking_user_ids', [])})."
            )
        if inventory_summary.get("users_with_unresolved_mapping"):
            blockers.append(
                "Ada pengguna dengan unresolved mapping Owner "
                f"({inventory_summary.get('users_with_unresolved_mapping')} user)."
            )
        if inventory_summary.get("automatic_import_allowed"):
            blockers.append("automatic_import_allowed unexpectedly true — fail closed.")
    mapped = len(WORKFLOW) + len(PAYROLL) + len(INBOX)
    inventory_clear = bool(
        inventory_summary and inventory_summary.get("cutover_review_clear")
        and not inventory_summary.get("automatic_import_allowed")
    )
    return {
        "workflow_authorization": mode,
        "settings_enabled": settings_on,
        "app_env": settings.app_env,
        "director_bootstrap_completed": bootstrapped,
        "enforced_approval_ref_configured": approval,
        "enforced_process_start_allowed": can_start_enforced,
        "production_endpoints_mapped": mapped,
        "mapping_review_required": {
            key: MAPPING_REVIEW_REQUIRED[key] for key in review
        },
        "branch_management": (
            "Cabang dikelola sebagai ID eksplisit pada grant grup (bukan master cabang terpisah). "
            "Direktur lintas cabang melalui keanggotaan grup sistem director."
        ),
        "automatic_grant_import": False,
        "inventory": inventory_summary,
        "blockers": blockers,
        "activation_recommended": bool(
            settings_on
            and bootstrapped
            and approval
            and inventory_clear
            and mode == "legacy"
            and not any("Inventory cutover belum clear" in b for b in blockers)
        ),
        "active_now": mode == "enforced",
        "notes": [
            "Default tetap legacy; dokumen ini tidak mengaktifkan enforced.",
            "Aktivasi produksi memerlukan persetujuan Direktur terpisah dari merge.",
            "Akun operasional tanpa managed grant akan ditolak di mode enforced — "
            "selesaikan inventory/grant sebelum cutover.",
            "Password akun tidak diubah oleh paket ini; staging_admin tidak dinonaktifkan.",
            "Katalog mapping_review_required selalu ditampilkan untuk transparansi; "
            "menjadi blocker hanya jika inventory menemukan unresolved pada pengguna.",
        ],
    }
