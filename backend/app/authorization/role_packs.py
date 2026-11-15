"""Recommended manual ScopedGrant packs for enforced cutover.

These packs are Director guidance only. They are never auto-applied to existing
users. Read vs write capabilities stay separate. Branch scope is always required
except for global catalog capabilities.
"""
from __future__ import annotations

from types import MappingProxyType

# Capability tiers for the three legacy OR-bundles that remain manual_only.
PRIVILEGE_OPTIONS = MappingProxyType({
    "production.job.read": {
        "minimum_read": ("job.read", "task.read"),
        "board": ("job.board.read",),
        "schedule_ops_read": ("delivery.schedule.read", "machine.read", "report.production.read", "assignee.read"),
        "sensitive_manual_only": (
            "payment.evidence.read",
            "audit.production.read",
            "attachment.delivery.read",
            "loading.authority.read",
        ),
        "risk_if_flattened": (
            "OR-bundle legacy memberi field sensitif + attachment + loading authority "
            "bersama-sama. Flatten otomatis melebihkan akses."
        ),
        "director_decision_needed": False,
        "status": "mapped_manual_packs",
    },
    "production.delivery.manage": {
        "loading_write": ("loading.record", "loading.cancel_confirmation"),
        "pod_write": ("delivery.pod.record",),
        "sj_cancel": ("delivery.sj.cancel_local",),
        "plan_write": ("delivery.plan.manage",),
        "attachment_write": ("attachment.delivery.create",),
        "attachment_read": ("attachment.delivery.read",),
        "risk_if_flattened": (
            "Satu privilege legacy mencakup loading, POD, cancel SJ, plan, dan upload. "
            "Kurir biasanya hanya butuh POD + attachment; Kepala Produksi butuh plan/cancel."
        ),
        "director_decision_needed": False,
        "status": "mapped_manual_packs",
    },
    "production.tracking.read": {
        "read_only": ("tracking.read",),
        "link_create": ("tracking.link.create",),
        "link_revoke": ("tracking.link.revoke",),
        "risk_if_flattened": (
            "Read tracking ≠ membuat link pelanggan. Link create harus grant terpisah."
        ),
        "director_decision_needed": False,
        "status": "mapped_manual_packs",
    },
})

# Six operational roles (HTML Final Tugas Tim) + Kepala Produksi.
# ownership: all = branch-wide; own = assignment-owned only (courier/operator).
ROLE_PACKS = MappingProxyType({
    "kepala_produksi": {
        "label": "Kepala Produksi",
        "branch_scope": "explicit",
        "ownership_default": "all",
        "capabilities": (
            "inbox.read", "order.read",
            "job.read", "job.board.read", "task.read",
            "delivery.schedule.read", "machine.read", "report.production.read", "assignee.read",
            "schedule.assignment.create", "schedule.assignment.cancel_remaining",
            "schedule.assignment.transfer_remaining", "job.qty_drift.acknowledge",
            "sample.decision.record",
            "delivery.plan.manage", "delivery.sj.cancel_local",
            "loading.cancel_confirmation",
            "payment.evidence.read", "audit.production.read",
            "tracking.read",
        ),
        "notes": (
            "Penjadwalan, approval sampel, plan SJ, cancel lokal. Bukan payment bypass. "
            "settings.branch.read / settings.branch.manage / payment_approval.* "
            "tetap Director-only (modul settings; grant manual branch.manage belum diizinkan)."
        ),
    },
    "designer": {
        "label": "Designer",
        "branch_scope": "explicit",
        "ownership_default": "all",
        "capabilities": (
            "inbox.read", "order.read",
            "job.read", "task.read",
            "design.version.create", "design.decision.record", "design.approval_link.create",
        ),
        "notes": "Upload + approval desain. Bypass desain hanya grant terpisah.",
    },
    "screener": {
        "label": "Screener",
        "branch_scope": "explicit",
        "ownership_default": "all",
        "capabilities": (
            "job.read", "task.read",
            "prep.screener.record", "prep.screener.correct",
        ),
        "notes": "Input/koreksi screen saja.",
    },
    "helper": {
        "label": "Helper",
        "branch_scope": "explicit",
        "ownership_default": "all",
        "capabilities": (
            "job.read", "task.read",
            "prep.helper.record", "prep.helper.correct",
            "output.helper.verify",
            "packing.record",
        ),
        "notes": "Prepare cup, helper verify, packing.",
    },
    "operator": {
        "label": "Operator",
        "branch_scope": "explicit",
        "ownership_default": "all",
        "capabilities": (
            "job.read", "task.read",
            "sample.version.create",
            "output.record", "output.correct",
            "reject.record",
        ),
        "notes": (
            "Sampel + qty cetak + reject. Approval sampel = Kepala Produksi. "
            "Pembatasan per assignment memakai TaskOwnership (bukan flatten grant own pada job.read)."
        ),
    },
    "driver": {
        "label": "Driver",
        "branch_scope": "explicit",
        "ownership_default": "all",
        "capabilities": (
            "job.read", "task.read",
            "delivery.schedule.read",
            "loading.record",
            "delivery.pod.record",
            "attachment.delivery.create", "attachment.delivery.read",
        ),
        "notes": (
            "Loading + POD + lampiran. Bukan cancel SJ / plan kurir. "
            "Scope per SJ/assignment via TaskOwnership bila Direktur membatasi."
        ),
    },
})


def privilege_option_matrix() -> dict:
    return {k: dict(v) for k, v in PRIVILEGE_OPTIONS.items()}


def role_pack_catalog() -> dict:
    return {
        "automatic_apply_allowed": False,
        "packs": {
            key: {
                **dict(pack),
                "capabilities": list(pack["capabilities"]),
            }
            for key, pack in ROLE_PACKS.items()
        },
        "usage": (
            "Direktur membuat grup biasa, menambahkan membership, lalu grant tiap "
            "capability dengan branches eksplisit melalui Pengaturan. Tidak ada tombol "
            "auto-apply ke pengguna existing."
        ),
    }
