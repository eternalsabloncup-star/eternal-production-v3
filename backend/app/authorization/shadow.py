"""Read-only compatibility diagnostics. Never grants or authorizes a request."""
from dataclasses import dataclass
from app.authorization.catalog import LEGACY_MAPPING, MAPPING_REVIEW_REQUIRED, CATALOG
from app.authorization.evaluator import Access, Grant, Resource, evaluate

@dataclass(frozen=True)
class Probe:
    legacy_permission: str
    capability: str
    resource: Resource


def candidate_access(user):
    """Transient candidate for comparison only; no DB write or role inference."""
    grants = []
    for permission in user.permissions or []:
        for code in LEGACY_MAPPING.get(permission, ()):
            branches = frozenset() if CATALOG[code].scope == 'global' else frozenset(user.branch_ids or [])
            grants.append(Grant(len(grants) + 1, code, branches))
    return Access(user.id, user.is_active, False, tuple(grants))


def compare(user, candidate, probes):
    results = []
    for probe in probes:
        global_scope = CATALOG.get(probe.capability) and CATALOG[probe.capability].scope == 'global'
        old = bool(user.is_active and probe.legacy_permission in (user.permissions or []) and
                   (global_scope or probe.resource.branch_id in (user.branch_ids or [])))
        new = evaluate(candidate, probe.capability, probe.resource).allowed
        results.append({'capability': probe.capability, 'legacy': old, 'candidate': new,
                        'matches': old == new, 'branch': probe.resource.branch_id,
                        'assignment': probe.resource.assignment_id})
    unresolved = sorted(set(user.permissions or []) & MAPPING_REVIEW_REQUIRED.keys())
    unknown = sorted(set(user.permissions or []) - LEGACY_MAPPING.keys())
    return {'comparisons': results, 'unresolved_mapping': unresolved, 'unknown_legacy': unknown,
            'cutover_allowed': bool(results) and not unresolved and not unknown and all(r['matches'] for r in results)}
