"""Locked Owner/Direktur policy for authorization cutover.

These rules are source-of-truth for cutover behaviour. Code must not silently
weaken them. They do not activate enforced mode by themselves.
"""
from __future__ import annotations

from types import MappingProxyType

from app.authorization.catalog import CATALOG, LEGACY_MAPPING, MAPPING_REVIEW_REQUIRED

# 1) System Director (bootstrap target commonly DIREKTUR_ETERNAL) has Full Access.
DIRECTOR_FULL_ACCESS = True
# 2) Operational access is group + branch scoped grants only.
EMPLOYEE_ACCESS_BY_GROUP_AND_BRANCH = True
# 3–4) Accounts and grants are created manually; never auto-import.
MANUAL_USER_CREATION_ONLY = True
AUTOMATIC_GRANT_IMPORT_ALLOWED = False
# 5) Settings UI/API must expose group, permission, membership, branch scope.
MANUAL_SETTINGS_REQUIRED = True
# 6) Every access mutation writes AccessAudit and is Director-visible.
AUDIT_TRAIL_REQUIRED = True
# 7) Existing accounts are not deactivated or rewritten by cutover tooling.
NO_SILENT_LEGACY_ACCOUNT_MUTATION = True

OWNER_DECISIONS = MappingProxyType({
    "director_full_access": (
        "DIREKTUR_ETERNAL (anggota grup sistem director) wajib Full Access "
        "seluruh modul/endpoint/tindakan/data/cabang."
    ),
    "employee_group_branch": (
        "Hak karyawan hanya dari keanggotaan grup + grant capability + cakupan cabang "
        "yang ditentukan Direktur."
    ),
    "manual_users": (
        "Pengguna baru ditambahkan MANUAL oleh Direktur lewat Pengaturan. "
        "Tidak ada pembuatan pengguna otomatis."
    ),
    "no_auto_import": (
        "Tidak ada auto-import grant dan tidak ada permission otomatis ke pengguna lama."
    ),
    "manual_settings": (
        "Pengaturan grup, permission, keanggotaan, dan cakupan cabang tersedia secara manual."
    ),
    "audit_trail": (
        "Setiap perubahan permission/membership/akun wajib AccessAudit dan terlihat oleh Direktur."
    ),
    "no_silent_legacy_change": (
        "Akun lama tidak dinonaktifkan atau diubah diam-diam oleh paket cutover."
    ),
})

# Owner decision for the three review-required legacy bundles (2026-11-14):
# keep granular manual grants; never flatten the legacy OR-bundle automatically.
MAPPING_OWNER_RESOLUTIONS = MappingProxyType({
    "production.job.read": {
        "status": "manual_only_no_auto_import",
        "impact": (
            "Holder legacy job.read bisa kehilangan board sensitif, attachment download, "
            "dan loading authority di mode enforced kecuali Direktur memberi grant granular "
            "per cabang (`job.read`, `job.board.read`, `task.read`, plus manual-only "
            "`payment.evidence.read` / `audit.production.read` / `attachment.delivery.read` / "
            "`loading.authority.read`)."
        ),
        "recommendation": (
            "Jangan auto-map. Buat grup per jabatan; grant `job.read`+`task.read` "
            "(dan `job.board.read` bila perlu) per cabang. Field sensitif & attachment "
            "tetap grant terpisah."
        ),
        "owner_decision": (
            "Sesuai keputusan Direktur: grant MANUAL saja; tidak ada import otomatis "
            "dari legacy bundle."
        ),
    },
    "production.delivery.manage": {
        "status": "manual_only_no_auto_import",
        "impact": (
            "Holder legacy delivery.manage tidak mendapat loading/POD/cancel/attachment "
            "otomatis. Tanpa grant granular, endpoint terkait menolak (403) di enforced."
        ),
        "recommendation": (
            "Grant per tindakan: `loading.record`, `delivery.pod.record`, "
            "`delivery.sj.cancel_local`, `loading.cancel_confirmation` per cabang; "
            "attachment create/read manual-only; pertimbangkan ownership `own` untuk kurir."
        ),
        "owner_decision": (
            "Sesuai keputusan Direktur: tidak ada auto-import; Direktur menetapkan "
            "grup jabatan + cabang secara manual."
        ),
    },
    "production.tracking.read": {
        "status": "manual_only_no_auto_import",
        "impact": (
            "Tanpa grant terpisah, pengguna kehilangan baca tracking dan/atau kemampuan "
            "membuat link pelanggan (`tracking.link.create`) di enforced."
        ),
        "recommendation": (
            "Grant `tracking.read` per cabang untuk yang perlu pantau. "
            "`tracking.link.create` terpisah (berbagi token ke pelanggan) — hanya jabatan "
            "yang disetujui Direktur."
        ),
        "owner_decision": (
            "Sesuai keputusan Direktur: mapping otomatis dilarang; link create bukan "
            "implikasi dari read."
        ),
    },
})


def mapping_review_details() -> dict:
    """Three privileges still shown to Direktur with impact + recommendation."""
    from app.authorization.role_packs import PRIVILEGE_OPTIONS

    out = {}
    for key in sorted(MAPPING_REVIEW_REQUIRED):
        detail = dict(MAPPING_OWNER_RESOLUTIONS[key])
        detail["legacy_reason"] = MAPPING_REVIEW_REQUIRED[key]
        detail["granular_candidates"] = list(LEGACY_MAPPING.get(key, ()))
        options = PRIVILEGE_OPTIONS.get(key)
        if options:
            detail["permission_options"] = {
                tier: list(caps) if isinstance(caps, tuple) else caps
                for tier, caps in options.items()
                if tier not in {"director_decision_needed"}
            }
            detail["status"] = options.get("status", detail.get("status"))
            detail["director_decision_needed"] = bool(
                options.get("director_decision_needed")
            )
        out[key] = detail
    return out


def policy_invariants() -> dict:
    """Machine-checkable invariants for tests and authorization-status."""
    return {
        "director_full_access": DIRECTOR_FULL_ACCESS,
        "employee_access_by_group_and_branch": EMPLOYEE_ACCESS_BY_GROUP_AND_BRANCH,
        "manual_user_creation_only": MANUAL_USER_CREATION_ONLY,
        "automatic_grant_import_allowed": AUTOMATIC_GRANT_IMPORT_ALLOWED,
        "manual_settings_required": MANUAL_SETTINGS_REQUIRED,
        "audit_trail_required": AUDIT_TRAIL_REQUIRED,
        "no_silent_legacy_account_mutation": NO_SILENT_LEGACY_ACCOUNT_MUTATION,
        "catalog_size": len(CATALOG),
        "mapping_review_required_keys": sorted(MAPPING_REVIEW_REQUIRED),
        "owner_decisions": dict(OWNER_DECISIONS),
    }
