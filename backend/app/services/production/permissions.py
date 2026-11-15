"""Phase 2 production permission constants + catalog / role-default mapping.

Authorization is always checked against ``users.permissions`` (JSONB codes),
never against display names. Role defaults below are seed/config helpers only —
they do not grant access by themselves.
"""

from __future__ import annotations

DESIGN_UPLOAD = "production.design.upload"
DESIGN_APPROVE = "production.design.approve"
DESIGN_BYPASS = "production.design.bypass"
PAYMENT_RECORD = "production.payment.record"
PAYMENT_BYPASS = "production.payment.bypass"
PAYMENT_REVOKE = "production.payment.revoke"
SCHEDULE_MANAGE = "production.schedule.manage"
SAMPLE_UPLOAD = "production.sample.upload"
SAMPLE_DECIDE = "production.sample.decide"
OUTPUT_CONFIRM = "production.output.confirm"
OUTPUT_HELPER_VERIFY = "production.output.helper_verify"
REJECT_RECORD = "production.reject.record"
REJECT_VERIFY = "production.reject.verify"
PACKING_RECORD = "production.packing.record"
DELIVERY_MANAGE = "production.delivery.manage"
# Physical return dual-control (permission-gated; not role-name gated).
# Assign REQUEST to Helper / designated Loading users; APPROVE to Kepala Produksi.
DELIVERY_LOADING_RETURN_REQUEST = "production.delivery.loading_return.request"
DELIVERY_LOADING_RETURN_APPROVE = "production.delivery.loading_return.approve"
TRACKING_READ = "production.tracking.read"
JOB_READ = "production.job.read"
JOB_CREATE = "production.job.create"
JOB_CANCEL = "production.job.cancel"
# Default cancel grant: Direktur only. Other roles need explicit permissions JSONB.
JOB_CANCEL_DEFAULT_ROLES: frozenset[str] = frozenset({"direktur", "director"})
PREP_SCREENER = "production.prep.screener"
PREP_HELPER = "production.prep.helper"
PAYROLL_MANAGE = "production.payroll.manage"
PAYROLL_READ = "production.payroll.read"

# Stable role identifiers used in User.role / PrepState.role (not display labels).
ROLE_HELPER = "helper"
ROLE_DRIVER = "driver"  # designated Loading / delivery operator in V3 tests
ROLE_KEPALA_PRODUKSI = "kepala_produksi"

PERMISSION_CATALOG: tuple[dict[str, str], ...] = (
    {"code": DESIGN_UPLOAD, "group": "design", "label": "Upload design"},
    {"code": DESIGN_APPROVE, "group": "design", "label": "Approve design"},
    {"code": DESIGN_BYPASS, "group": "design", "label": "Bypass design"},
    {"code": PAYMENT_RECORD, "group": "payment", "label": "Record payment"},
    {"code": PAYMENT_BYPASS, "group": "payment", "label": "Bypass payment"},
    {"code": PAYMENT_REVOKE, "group": "payment", "label": "Revoke payment bypass"},
    {"code": SCHEDULE_MANAGE, "group": "schedule", "label": "Manage schedule"},
    {"code": SAMPLE_UPLOAD, "group": "sample", "label": "Upload sample"},
    {"code": SAMPLE_DECIDE, "group": "sample", "label": "Decide sample"},
    {"code": OUTPUT_CONFIRM, "group": "output", "label": "Confirm output"},
    {
        "code": OUTPUT_HELPER_VERIFY,
        "group": "output",
        "label": "Helper verify operator output",
    },
    {"code": REJECT_RECORD, "group": "reject", "label": "Record reject"},
    {"code": REJECT_VERIFY, "group": "reject", "label": "Verify reject"},
    {"code": PACKING_RECORD, "group": "packing", "label": "Record packing"},
    {"code": DELIVERY_MANAGE, "group": "delivery", "label": "Manage delivery / loading / POD"},
    {
        "code": DELIVERY_LOADING_RETURN_REQUEST,
        "group": "delivery",
        "label": "Request physical Loading return",
    },
    {
        "code": DELIVERY_LOADING_RETURN_APPROVE,
        "group": "delivery",
        "label": "Approve / reject physical Loading return",
    },
    {"code": TRACKING_READ, "group": "tracking", "label": "Read tracking"},
    {"code": JOB_READ, "group": "job", "label": "Read production job"},
    {"code": JOB_CREATE, "group": "job", "label": "Create production job"},
    {
        "code": JOB_CANCEL,
        "group": "job",
        "label": "Cancel production job (soft; default Direktur only)",
    },
    {"code": PREP_SCREENER, "group": "prep", "label": "Prep screener"},
    {"code": PREP_HELPER, "group": "prep", "label": "Prep helper"},
    {"code": PAYROLL_MANAGE, "group": "payroll", "label": "Manage payroll"},
    {"code": PAYROLL_READ, "group": "payroll", "label": "Read payroll"},
)

# Default grants for the two physical-return codes only (not a full role matrix).
# Helper + designated Loading role (driver) → request; Kepala Produksi → approve.
LOADING_RETURN_REQUEST_DEFAULT_ROLES: frozenset[str] = frozenset(
    {ROLE_HELPER, ROLE_DRIVER}
)
LOADING_RETURN_APPROVE_DEFAULT_ROLES: frozenset[str] = frozenset(
    {ROLE_KEPALA_PRODUKSI}
)

ROLE_DEFAULT_PERMISSIONS: dict[str, tuple[str, ...]] = {
    ROLE_HELPER: (DELIVERY_LOADING_RETURN_REQUEST, OUTPUT_HELPER_VERIFY),
    ROLE_DRIVER: (DELIVERY_LOADING_RETURN_REQUEST,),
    ROLE_KEPALA_PRODUKSI: (DELIVERY_LOADING_RETURN_APPROVE,),
}


def normalize_role_id(role: str | None) -> str:
    return (role or "").strip().lower()


def default_loading_return_permissions_for_role(role: str | None) -> list[str]:
    """Return only loading_return.* defaults for a stable role id.

    Does not grant permissions to every user — callers must merge into
    ``users.permissions`` explicitly (seed / admin tooling). Authorization
    remains permission-code based at runtime.
    """
    rid = normalize_role_id(role)
    return list(ROLE_DEFAULT_PERMISSIONS.get(rid, ()))


def merge_role_default_permissions(
    existing: list[str] | None, role: str | None
) -> list[str]:
    """Merge role-default loading_return permissions into an existing list."""
    base = list(existing or [])
    seen = set(base)
    for code in default_loading_return_permissions_for_role(role):
        if code not in seen:
            base.append(code)
            seen.add(code)
    return base


def is_job_cancel_default_role(role: str | None) -> bool:
    return normalize_role_id(role) in JOB_CANCEL_DEFAULT_ROLES


def user_may_cancel_job(user) -> bool:
    """Least privilege: explicit grant OR Direktur default. Never invents grants."""
    from app.authorization.workflow import context

    ctx = context(user)
    if ctx is not None:
        access = getattr(ctx, "access", None)
        if access is not None and getattr(access, "director", False):
            return True
        # Catalog capability code (enforced grants) — not production.* JSONB.
        if getattr(ctx, "capability", None) == "job.cancel":
            return True
        return bool(getattr(ctx, "can", lambda _c: False)("job.cancel"))
    access = getattr(user, "_managed_access", None)
    if access is not None and getattr(access, "director", False):
        return True
    perms = set(user.permissions or [])
    if JOB_CANCEL in perms or "job.cancel" in perms:
        return True
    return is_job_cancel_default_role(getattr(user, "role", None))


def permission_catalog_payload() -> dict:
    return {
        "permissions": [dict(row) for row in PERMISSION_CATALOG],
        "role_defaults": {
            rid: list(codes) for rid, codes in ROLE_DEFAULT_PERMISSIONS.items()
        },
        "job_cancel": {
            "code": JOB_CANCEL,
            "default_roles": sorted(JOB_CANCEL_DEFAULT_ROLES),
            "note": "Direktur default; other roles require explicit grant",
        },
        "loading_return": {
            "request_code": DELIVERY_LOADING_RETURN_REQUEST,
            "approve_code": DELIVERY_LOADING_RETURN_APPROVE,
            "request_default_roles": sorted(LOADING_RETURN_REQUEST_DEFAULT_ROLES),
            "approve_default_roles": sorted(LOADING_RETURN_APPROVE_DEFAULT_ROLES),
        },
    }
