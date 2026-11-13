"""Pure decision engine. Resource context must come from authoritative DB rows.

An allow result only authorizes access: callers MUST still apply workflow, qty,
receipt, idempotency and existing SoD checks. Not a business-rule override.
"""
from dataclasses import dataclass
from app.authorization.catalog import CATALOG

@dataclass(frozen=True)
class Grant:
    id: int
    capability: str
    branches: frozenset[str] = frozenset()
    ownership: str = 'all'  # all, own, selected
    assignments: frozenset[int] = frozenset()

@dataclass(frozen=True)
class Access:
    user_id: int
    active: bool
    director: bool = False
    grants: tuple[Grant, ...] = ()
    revision: int = 0

@dataclass(frozen=True)
class Resource:
    branch_id: str | None = None
    assignment_id: int | None = None
    owner_user_id: int | None = None
    ownership_id: int | None = None

@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    grant_id: int | None = None


def validate_grant(grant: Grant) -> None:
    cap = CATALOG.get(grant.capability)
    if cap is None:
        raise ValueError('Unknown capability')
    if cap.module == 'settings':
        raise ValueError('Access administration is Director-only in this release')
    if grant.ownership not in {'all', 'own', 'selected'}:
        raise ValueError('Invalid ownership scope')
    if any(not isinstance(b, str) or not b.strip() or b != b.strip() or b == '*' for b in grant.branches):
        raise ValueError('Explicit branch identifiers required')
    if any(type(a) is not int or a <= 0 for a in grant.assignments):
        raise ValueError('Invalid assignment identifiers')
    if cap.scope == 'global':
        if grant.branches or grant.assignments or grant.ownership != 'all':
            raise ValueError('Global capability cannot carry branch/assignment scope')
    elif not grant.branches:
        raise ValueError('Branch capability requires explicit branches')
    if (grant.ownership == 'selected') != bool(grant.assignments):
        raise ValueError('Selected ownership requires assignment identifiers only')


def evaluate(access: Access, capability: str, resource: Resource = Resource()) -> Decision:
    cap = CATALOG.get(capability)
    if not access.active:
        return Decision(False, 'inactive')
    if cap is None:
        return Decision(False, 'unknown_capability')
    if access.director:
        return Decision(True, 'system_director')
    if cap.module == 'settings':
        return Decision(False, 'director_required')
    for grant in access.grants:
        if grant.capability != capability:
            continue
        try:
            validate_grant(grant)
        except ValueError:
            continue  # malformed persisted grants fail closed
        if cap.scope == 'branch' and resource.branch_id not in grant.branches:
            continue
        if grant.ownership == 'own' and ((resource.assignment_id is None and resource.ownership_id is None) or resource.owner_user_id != access.user_id):
            continue
        if grant.ownership == 'selected' and resource.assignment_id not in grant.assignments:
            continue
        return Decision(True, 'scoped_grant', grant.id)
    return Decision(False, 'no_matching_grant')
