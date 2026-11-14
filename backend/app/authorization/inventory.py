"""Read-only cutover inventory: legacy User.permissions vs actual managed grants.

Runs in a READ ONLY snapshot, writes nothing and never grants. Every difference
is reported for Owner review; only Director widening is expected by policy.

    python -m app.authorization.inventory --preflight   # no connection
    python -m app.authorization.inventory --summary > inventory.json
"""
import asyncio
import json
import sys

from sqlalchemy import select, text

from app.authorization.catalog import CATALOG, LEGACY_MAPPING, compatibility_inventory
from app.authorization.service import load_access
from app.authorization.shadow import Probe, compare
from app.authorization.evaluator import Resource
from app.models.user import User

UNMAPPED = '(no legacy permission)'
OUTSIDE = '(outside legacy branches)'


def _probes(user, access):
    legacy_branches = sorted(user.branch_ids or [])
    grant_branches = {g.capability: set(g.branches) for g in access.grants}
    probes = []
    covered = set()
    for permission in sorted(set(user.permissions or []) & LEGACY_MAPPING.keys()):
        for code in LEGACY_MAPPING[permission]:
            covered.add(code)
            if CATALOG[code].scope == 'global':
                probes.append(Probe(permission, code, Resource()))
                continue
            for branch in sorted(set(legacy_branches) | grant_branches.get(code, set())) or [OUTSIDE]:
                probes.append(Probe(permission, code, Resource(branch)))
    extra = {g.capability for g in access.grants} - covered
    if access.director:
        extra |= {c for c, cap in CATALOG.items() if cap.module != 'settings'} - covered
    for code in sorted(extra):
        branches = [None] if CATALOG[code].scope == 'global' else sorted(grant_branches.get(code, set()) | set(legacy_branches)) or [OUTSIDE]
        probes.extend(Probe(UNMAPPED, code, Resource(b)) for b in branches)
    return probes


def user_report(user, access) -> dict:
    report = compare(user, access, _probes(user, access))
    narrowing = [r for r in report['comparisons'] if r['legacy'] and not r['candidate']]
    widening = [r for r in report['comparisons'] if r['candidate'] and not r['legacy']]
    blocking_widening = [] if access.director else widening
    return {
        'user_id': user.id, 'director': access.director,
        'legacy_permissions': sorted(user.permissions or []), 'legacy_branches': sorted(user.branch_ids or []),
        'managed_grants': [{'capability': g.capability, 'branches': sorted(g.branches), 'ownership': g.ownership,
                            'assignments': sorted(g.assignments)} for g in access.grants],
        'mapping': compatibility_inventory(list(user.permissions or [])),
        'narrowing': narrowing, 'widening': widening,
        'unresolved_mapping': report['unresolved_mapping'], 'unknown_legacy': report['unknown_legacy'],
        'blocking': bool(narrowing or blocking_widening or report['unresolved_mapping'] or report['unknown_legacy']),
    }


async def build(session, *, declare_readonly: bool = True) -> dict:
    # CLI starts a fresh txn and declares READ ONLY. HTTP callers already hold a
    # request transaction that may have read rows; skip SET TRANSACTION there.
    if declare_readonly:
        await session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
    users = (await session.scalars(select(User).order_by(User.id))).all()
    rows, inactive, revision = [], [], None
    for user in users:
        access = await load_access(session, user.id, lock=False)
        revision = access.revision
        if not access.active:
            inactive.append(user.id)
            continue
        rows.append(user_report(user, access))
    return {
        'access_revision': revision, 'users': rows, 'inactive_user_ids': inactive,
        'blocking_user_ids': [r['user_id'] for r in rows if r['blocking']],
        'cutover_review_clear': bool(rows) and not any(r['blocking'] for r in rows),
        'automatic_import_allowed': False, 'writes_performed': False,
    }


LOOPBACK = {'127.0.0.1', 'localhost', '::1'}
PREFLIGHT = (
    'Read-only; one REPEATABLE READ READ ONLY transaction; no INSERT/UPDATE/DELETE/DDL, no migration.',
    'Reads users (id, flags, legacy permission/branch arrays), access groups/memberships/grants and access_state.revision.',
    'Never reads or prints password hashes, tokens, usernames, display names or audit payloads.',
    'Output is JSON keyed by numeric user id: grants, narrowing, widening, unknown and unresolved mappings.',
    'Exit 0 = review clear; exit 2 = blocking findings (BLOCKED); exit 3 = refused before connecting.',
    'A non-loopback target is refused unless --owner-approval-ref names the written Owner approval.',
)


def target(url: str) -> dict:
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    return {'host': parsed.hostname, 'port': parsed.port, 'database': parsed.path.lstrip('/'),
            'loopback': parsed.hostname in LOOPBACK}


def summarize(report: dict) -> dict:
    rows = report['users']
    return {
        'access_revision': report['access_revision'], 'users_checked': len(rows),
        'inactive_users': len(report['inactive_user_ids']), 'directors': sum(r['director'] for r in rows),
        'users_with_narrowing': sum(bool(r['narrowing']) for r in rows),
        'users_with_widening_non_director': sum(bool(r['widening']) and not r['director'] for r in rows),
        'users_with_unknown_legacy': sum(bool(r['unknown_legacy']) for r in rows),
        'users_with_unresolved_mapping': sum(bool(r['unresolved_mapping']) for r in rows),
        'blocking_user_ids': report['blocking_user_ids'], 'cutover_review_clear': report['cutover_review_clear'],
        'automatic_import_allowed': False, 'writes_performed': False,
    }


async def _main(argv) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog='python -m app.authorization.inventory')
    parser.add_argument('--preflight', action='store_true', help='print the plan and target; never connects')
    parser.add_argument('--summary', action='store_true', help='counts only, no per-user rows')
    parser.add_argument('--owner-approval-ref', default='', help='required for any non-loopback target')
    args = parser.parse_args(argv)
    from app.core.config import get_settings
    where = target(get_settings().database_url)
    if args.preflight:
        json.dump({'target': where, 'plan': list(PREFLIGHT), 'connects': False}, sys.stdout, indent=1)
        sys.stdout.write('\n')
        return 0
    if not where['loopback'] and not args.owner_approval_ref.strip():
        sys.stderr.write('Refused: non-loopback target requires --owner-approval-ref (see --preflight).\n')
        return 3
    from app.db.session import get_session_factory, dispose_engine
    try:
        async with get_session_factory()() as session:
            async with session.begin():
                report = await build(session)
    finally:
        await dispose_engine()
    json.dump(summarize(report) if args.summary else report, sys.stdout, indent=1, default=str)
    sys.stdout.write('\n')
    return 0 if report['cutover_review_clear'] else 2


if __name__ == '__main__':
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))
