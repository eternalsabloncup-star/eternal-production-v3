"""Runtime payment-bypass authorization — mirrors job.cancel Direktur default."""

from types import SimpleNamespace

from app.authorization.evaluator import Access, Grant, Resource
from app.authorization.workflow import WorkflowContext
from app.services.production import permissions as P


def _user(**kwargs):
    base = {
        "role": "operator",
        "permissions": [],
        "_workflow_context": None,
        "_managed_access": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_legacy_direktur_without_jsonb_allowed():
    assert P.user_may_bypass_payment(_user(role="Direktur", permissions=[])) is True
    assert P.user_may_bypass_payment(_user(role="director", permissions=[])) is True


def test_legacy_operator_without_grant_denied():
    assert P.user_may_bypass_payment(_user(role="operator", permissions=[])) is False
    assert P.user_may_bypass_payment(_user(role="Kepala Produksi", permissions=[])) is False


def test_legacy_operator_with_explicit_grant_allowed():
    assert P.user_may_bypass_payment(
        _user(role="operator", permissions=[P.PAYMENT_BYPASS])
    ) is True


def test_spoofed_non_role_attributes_do_not_elevate():
    assert (
        P.user_may_bypass_payment(
            _user(role="operator", permissions=[], display_name="Direktur", claimed="Direktur")
        )
        is False
    )


def test_enforced_system_director_allowed():
    access = Access(1, True, director=True, grants=(), revision=1)
    ctx = WorkflowContext(access, "payment.bypass.create", (P.PAYMENT_BYPASS,), Resource("A"))
    assert P.user_may_bypass_payment(_user(role="operator", permissions=[], _workflow_context=ctx)) is True


def test_enforced_scoped_grant_allowed_and_missing_denied():
    grant = Grant(1, "payment.bypass.create", frozenset({"A"}), "all", frozenset())
    access = Access(3, True, director=False, grants=(grant,), revision=1)
    ctx = WorkflowContext(access, "payment.bypass.create", (P.PAYMENT_BYPASS,), Resource("A"))
    assert P.user_may_bypass_payment(_user(permissions=[], _workflow_context=ctx)) is True
    empty = Access(3, True, director=False, grants=(), revision=1)
    ctx_deny = WorkflowContext(empty, "job.read", (P.JOB_READ,), Resource("A"))
    assert P.user_may_bypass_payment(_user(permissions=[], _workflow_context=ctx_deny)) is False
