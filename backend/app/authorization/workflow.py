"""Request-scoped enforcement bridge. Never mutates or ORs legacy user grants."""
from dataclasses import dataclass, replace
from fastapi import HTTPException
from sqlalchemy import select
from app.authorization.catalog import CATALOG
from app.authorization.evaluator import Resource, evaluate, validate_grant
from app.authorization.workflow_map import WORKFLOW, PAYROLL, INBOX
from app.authorization.ownership import owned
from app.models.production.job import ProductionJob
from app.models.production.schedule import ScheduleAssignment
from app.models.production.event import ProductionEvent
from app.models.production.design import DesignVersion
from app.models.production.sample import SampleVersion
from app.models.production.payment import PaymentReceiptRef, PaymentBypass
from app.models.production.attachment import ProductionAttachment
from app.models.production.payroll import PayrollRun

@dataclass
class WorkflowContext:
    access: object
    capability: str
    legacy_checks: tuple
    resource: Resource

    def legacy(self, permissions):
        return set(permissions).issubset(self.legacy_checks)

    def branch(self, branch):
        return evaluate(self.access,self.capability,replace(self.resource,branch_id=branch)).allowed

    def can(self, capability):
        return evaluate(self.access,capability,self.resource).allowed


def context(user): return getattr(user,'_workflow_context',None)
def branch_allowed(user, branch):
    ctx=context(user)
    return ctx.branch(branch) if ctx else branch in list(user.branch_ids or [])

def legacy_allowed(user, permissions):
    ctx=context(user)
    return ctx.legacy(permissions) if ctx else set(permissions).issubset(set(user.permissions or []))

ROLE = {'prep.screener':'screener','prep.helper':'helper','output.helper':'helper','output':'operator',
        'reject':'operator','sample':'operator','packing':'packing','loading':'loading','delivery':'courier', 'attachment.return':'loading', 'attachment.delivery':'courier'}

def role_for(capability):
    for prefix in sorted(ROLE,key=len,reverse=True):
        if capability.startswith(prefix+'.'): return ROLE[prefix]
    return None

async def authorize_request(session,user,request):
    endpoint=request.scope.get('endpoint')
    module=getattr(endpoint,'__module__',''); name=getattr(endpoint,'__name__','')
    maps={'app.api.production.workflow':WORKFLOW,'app.api.production.payroll':PAYROLL,'app.api.production_inbox':INBOX}
    mapping=maps.get(module)
    if mapping is None:
        if module.startswith('app.authorization.'): return  # separately guarded new routes
        if '/production/' in request.url.path: raise HTTPException(403,'Unmapped production endpoint')
        return
    if name not in mapping: raise HTTPException(403,'Unmapped production endpoint')
    cap,legacy=mapping[name]
    # An ORM identity may be reused by a test/session; never retain a previous guard.
    user._workflow_context = None
    body={}
    if request.method in {'POST','PATCH','PUT'}:
        if 'application/json' in request.headers.get('content-type',''):
            try: body=await request.json()
            except Exception: raise HTTPException(422,'Invalid JSON')
            if not isinstance(body,dict): raise HTTPException(422,'Object body required')
        elif name=='upload_attachment': body=dict(await request.form())
    if name=='design_decide' and body.get('bypass'): cap,legacy='design.bypass.create',('design.bypass',)
    if name in {'prep_screener','prep_helper'} and body.get('as_correction'): cap=cap.replace('.record','.correct')
    if name=='upload_attachment' and str(body.get('purpose','')).startswith('loading_return'):
        cap,legacy='attachment.return.create',('delivery.loading_return.request','delivery.manage')
    access=user._managed_access
    def any_scope(code):
        if access.director: return code in CATALOG
        for g in access.grants:
            if g.capability!=code: continue
            try: validate_grant(g)
            except ValueError: continue
            return True
        return False
    if not any_scope(cap): raise HTTPException(403,'Capability denied: '+cap)
    params=request.path_params
    def number(value):
        try:
            if isinstance(value,bool) or int(value)<=0: raise ValueError()
            return int(value)
        except (ValueError,TypeError): raise HTTPException(422,'Invalid resource ID')
    job=None
    assignment_id=params.get('assignment_id')
    if name in {'output_confirm','reject_record','sample_upload','prep_screener','prep_helper'}:
        assignment_id=body.get('assignment_id',assignment_id)
    if params.get('job_id'): job=await session.get(ProductionJob,number(params['job_id']))
    if params.get('job_id') and job is None: raise HTTPException(404,'Job not found')
    refs=[('version_id',DesignVersion),('sample_id',SampleVersion),('receipt_id',PaymentReceiptRef),
          ('bypass_id',PaymentBypass),('event_id',ProductionEvent),('request_id',ProductionEvent),('attachment_id',ProductionAttachment)]
    for key,model in refs:
        if key not in params: continue
        row=await session.get(model,number(params[key]))
        if row is None: raise HTTPException(404,'Resource not found')
        if job is not None and job.id!=row.job_id: raise HTTPException(403,'Cross-job resource denied')
        job=await session.get(ProductionJob,row.job_id)
        assignment_id=getattr(row,'assignment_id',None) or assignment_id
    if name=='output_correct' and body.get('source_event_id'):
        row=await session.get(ProductionEvent,number(body['source_event_id']))
        if row is None or (job is not None and row.job_id!=job.id): raise HTTPException(403,'Cross-job source denied')
        job=await session.get(ProductionJob,row.job_id); assignment_id=row.assignment_id
    if assignment_id is not None:
        assignment_id=number(assignment_id)
        assignment=await session.get(ScheduleAssignment,assignment_id)
        if assignment is None: raise HTTPException(404,'Assignment not found')
        if job is not None and assignment.job_id!=job.id: raise HTTPException(403,'Cross-job assignment denied')
        job=await session.get(ProductionJob,assignment.job_id)
    if name=='get_job_by_so':
        job=await session.scalar(select(ProductionJob).where(ProductionJob.accurate_so_number==params['so_number']))
        if job is None: raise HTTPException(404,'Job not found')
    branch=job.branch_id if job else body.get('branch_id')
    if name in {'create_run','get_run'}:
        run=await session.get(PayrollRun,number(params['run_id'])) if name=='get_run' else await session.scalar(select(PayrollRun).where(PayrollRun.idempotency_key==body.get('idempotency_key')))
        if run is not None:
            if branch and run.branch_id!=branch: raise HTTPException(403,'Payroll request scope mismatch')
            branch=run.branch_id
        if not branch and not access.director: raise HTTPException(403,'Explicit payroll branch required')
    owner_id=None; binding=None
    role=role_for(cap)
    if job is not None and role:
        binding=await owned(session,user.id,job.id,role,assignment_id)
        if binding: owner_id=user.id
    resource=Resource(branch,assignment_id,owner_id,binding)
    if job is not None or branch or CATALOG[cap].scope=='global' or name in {'create_run','get_run'}:
        if not evaluate(access,cap,resource).allowed: raise HTTPException(403,'Resource scope denied')
    if name=='list_team_tasks_with_sync' and body.get('sync_ensure'):
        # Legacy sync commits per job; a transaction-safe bulk adapter is still required.
        raise HTTPException(409,'Bulk source sync unavailable during sandbox cutover')
    user._workflow_context=WorkflowContext(access,cap,tuple('production.'+p for p in legacy),resource)


def redact_board(user, payload):
    ctx=context(user)
    if ctx:
        from app.authorization.workflow_map import SENSITIVE_FIELDS
        for key,cap in SENSITIVE_FIELDS.items():
            if not ctx.can(cap): payload[key]=[]
        if not ctx.can('audit.production.read'):
            for row in payload.get('prep_states', []): row['evidence_ref'] = None
            for row in payload.get('design_versions', []):
                row['decision_reason'] = None
                row['file_name'] = None
            for row in payload.get('samples', []): row['file_name'] = None
    return payload
