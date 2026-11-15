"""Explicit compatibility manifest. Never flatten scoped grants into legacy JSON."""
from dataclasses import dataclass
from types import MappingProxyType

# The legacy code is retained; entries describe its independently grantable actions.
_ROWS = {
    'inbox.read': ('inbox.read',),
    'order.read': ('order.read',),
    'job.read': ('job.read', 'job.board.read', 'task.read', 'delivery.schedule.read', 'machine.read', 'report.production.read', 'assignee.read'),
    'job.create': ('job.create', 'job.source_sync'),
    'job.cancel': ('job.cancel',),
    'design.upload': ('design.version.create', 'design.approval_link.create'),
    'design.approve': ('design.decision.record',),
    'design.bypass': ('design.bypass.create',),
    'payment.record': ('payment.receipt.record', 'payment.receipt.revalidate'),
    'payment.bypass': ('payment.bypass.create',),
    'payment.revoke': ('payment.bypass.revoke', 'payment.receipt.invalidate'),
    'schedule.manage': ('schedule.assignment.create', 'schedule.assignment.cancel_remaining', 'schedule.assignment.transfer_remaining', 'machine.manage', 'job.qty_drift.acknowledge'),
    'prep.screener': ('prep.screener.record', 'prep.screener.correct'),
    'prep.helper': ('prep.helper.record', 'prep.helper.correct'),
    'sample.upload': ('sample.version.create',),
    'sample.decide': ('sample.decision.record',),
    'output.confirm': ('output.record', 'output.correct'),
    'output.helper_verify': ('output.helper.verify',),
    'reject.record': ('reject.record',),
    'reject.verify': ('reject.verify',),
    'packing.record': ('packing.record',),
    'delivery.manage': ('loading.record', 'loading.cancel_confirmation', 'delivery.sj.cancel_local', 'delivery.pod.record', 'delivery.plan.manage'),
    'delivery.loading_return.request': ('loading.return.request', 'attachment.return.create'),
    'delivery.loading_return.approve': ('loading.return.approve', 'loading.return.reject'),
    'tracking.read': ('tracking.read', 'tracking.link.create'),
    'payroll.read': ('payroll.rate.read', 'payroll.run.read'),
    'payroll.manage': ('payroll.rate.manage', 'payroll.run.create'),
}
LEGACY_MAPPING = MappingProxyType({'production.' + key: values for key, values in _ROWS.items()})
# These are blockers to automatic grant conversion, NOT implicit additional grants.
MAPPING_REVIEW_REQUIRED = MappingProxyType({
    'production.job.read': 'Board sensitive fields and attachment read OR rules require endpoint/field mapping.',
    'production.delivery.manage': 'Attachment purpose/read OR rules require endpoint mapping.',
    'production.tracking.read': 'Tracking event field visibility requires explicit mapping.',
})

@dataclass(frozen=True)
class Capability:
    code: str
    module: str
    action: str
    scope: str  # branch or global
    manual_only: bool = False


def _action(code: str) -> str:
    if code.endswith(('.export', '.print', '.read')):
        return code.rsplit('.', 1)[1]
    if '.correct' in code:
        return 'correction'
    if any(part in code for part in ('cancel', 'invalidate', 'revoke')):
        return 'cancel'
    if any(part in code for part in ('decision', 'verify', 'approve', '.reject', 'bypass')) and code != 'reject.record':
        return 'approval'
    return 'input'

_codes = {code for codes in LEGACY_MAPPING.values() for code in codes}
_manual = {
    'payment.evidence.read', 'audit.production.read', 'attachment.delivery.create', 'attachment.delivery.read',
    'loading.authority.read', 'evidence.capability.read', 'capability.read',
    'job.export', 'job.print', 'task.export', 'report.production.export', 'payroll.export', 'payroll.print',
    'assignment.ownership.manage', 'assignment.delegation.manage',
    'design.approval_link.revoke', 'tracking.link.revoke',
    'job.cancel',  # default Direktur; explicit grant for other roles
}
_admin = {
    'settings.user.read', 'settings.user.create', 'settings.user.update', 'settings.user.deactivate',
    'settings.user.password_reset', 'settings.group.read', 'settings.group.manage',
    'settings.membership.manage', 'settings.grant.manage', 'settings.effective_access.read',
    'settings.access_audit.read', 'settings.access_audit.export',
    # Fase 3 production settings (PostgreSQL) — mapped for enforced; no auto-import from legacy.
    'settings.payment_approval.read', 'settings.payment_approval.manage',
    'settings.branch.read', 'settings.branch.manage',
}
_global = _admin | {'payroll.rate.read', 'payroll.rate.manage', 'evidence.capability.read', 'capability.read'}
CATALOG = MappingProxyType({
    code: Capability(code, code.split('.')[0], 'administration' if code in _admin or code.endswith('.manage') else _action(code),
                     'global' if code in _global else 'branch', code in _manual or code in _admin)
    for code in sorted(_codes | _manual | _admin)
})


def compatibility_inventory(permissions: list[str]) -> dict:
    """Read-only candidate mapping, not an import/cutover authorization."""
    return {
        'candidates': {p: list(LEGACY_MAPPING[p]) for p in sorted(set(permissions)) if p in LEGACY_MAPPING},
        'unknown': sorted(set(permissions) - LEGACY_MAPPING.keys()),
        'review_required': {p: MAPPING_REVIEW_REQUIRED[p] for p in sorted(set(permissions)) if p in MAPPING_REVIEW_REQUIRED},
        'automatic_import_allowed': False,
    }
