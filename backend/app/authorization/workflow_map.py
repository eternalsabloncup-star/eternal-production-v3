"""Exhaustive authenticated legacy production endpoint manifest.

Each action is independently granted. No inferred OR with User.permissions.
Dynamic variants (bypass, correction, sync, upload purpose) are resolved before
business execution. Unlisted production routes fail closed in enforced mode.
"""
# endpoint function -> (capability, legacy checks expected inside that endpoint)
WORKFLOW = {
 'create_job': ('job.create', ('job.create',)),
 'evidence_capability': ('evidence.capability.read', ()),
 'list_team_tasks': ('task.read', ('job.read',)),
 'list_team_tasks_with_sync': ('task.read', ('job.read',)),
 'get_job_by_so': ('job.read', ('job.read',)),
 'get_job_board': ('job.board.read', ('job.read',)),
 'get_loading_authority': ('loading.authority.read', ('job.read',)),
 'get_job': ('job.read', ('job.read',)),
 'design_upload': ('design.version.create', ('design.upload',)),
 'design_decide': ('design.decision.record', ('design.approve',)),
 'design_approval_link': ('design.approval_link.create', ('design.upload',)),
 'live_tracking_link': ('tracking.link.create', ('tracking.read',)),
 'payment_receipt': ('payment.receipt.record', ('payment.record',)),
 'payment_receipt_revalidate': ('payment.receipt.revalidate', ('payment.record',)),
 'payment_bypass': ('payment.bypass.create', ('payment.bypass',)),
 'payment_bypass_revoke': ('payment.bypass.revoke', ('payment.revoke',)),
 'payment_receipt_invalidate': ('payment.receipt.invalidate', ('payment.revoke',)),
 'schedule_create': ('schedule.assignment.create', ('schedule.manage',)),
 'schedule_cancel_remaining': ('schedule.assignment.cancel_remaining', ('schedule.manage',)),
 'schedule_transfer': ('schedule.assignment.transfer_remaining', ('schedule.manage',)),
 'prep_screener': ('prep.screener.record', ('prep.screener',)),
 'prep_helper': ('prep.helper.record', ('prep.helper',)),
 'sample_upload': ('sample.version.create', ('sample.upload',)),
 'sample_decide': ('sample.decision.record', ('sample.decide',)),
 'output_confirm': ('output.record', ('output.confirm',)),
 'reject_record': ('reject.record', ('reject.record',)),
 'reject_verify': ('reject.verify', ('reject.verify',)),
 'output_correct': ('output.correct', ('output.confirm',)),
 'helper_verify_output': ('output.helper.verify', ('output.helper_verify',)),
 'packing_record': ('packing.record', ('packing.record',)),
 'loading_record': ('loading.record', ('delivery.manage',)),
 'loading_cancel': ('loading.cancel_confirmation', ('delivery.manage',)),
 'loading_return_request': ('loading.return.request', ('delivery.loading_return.request',)),
 'loading_return_approve': ('loading.return.approve', ('delivery.loading_return.approve',)),
 'loading_return_reject': ('loading.return.reject', ('delivery.loading_return.approve',)),
 'pod_record': ('delivery.pod.record', ('delivery.manage',)),
 'upload_attachment': ('attachment.delivery.create', ('delivery.manage',)),
 'download_attachment': ('attachment.delivery.read', ('job.read', 'delivery.manage')),
 'list_attachments': ('attachment.delivery.read', ('job.read',)),
 'sj_cancel': ('delivery.sj.cancel_local', ('delivery.manage',)),
 'tracking': ('tracking.read', ('tracking.read',)),
}
PAYROLL = {
 'create_rate': ('payroll.rate.manage', ('payroll.manage',)),
 'get_rates': ('payroll.rate.read', ('payroll.read',)),
 'create_run': ('payroll.run.create', ('payroll.manage',)),
 'get_run': ('payroll.run.read', ('payroll.read',)),
}
INBOX = {'inbox': ('inbox.read', ('inbox.read',)), 'order_detail': ('order.read', ('order.read',)),
         'permissions_catalog': ('capability.read', ())}
SENSITIVE_FIELDS = {
 'payment_receipts': 'payment.evidence.read', 'payment_bypasses': 'payment.evidence.read',
 'events': 'audit.production.read', 'prep_events': 'audit.production.read',
}
# Aggregate job views require branch-wide grants, not an assignment-only grant.
COLLECTIONS = {'list_team_tasks', 'list_team_tasks_with_sync', 'inbox', 'order_detail',
               'permissions_catalog', 'evidence_capability'}
