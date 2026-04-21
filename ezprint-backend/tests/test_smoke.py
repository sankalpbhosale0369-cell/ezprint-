"""Lightweight smoke tests.

These don't need Postgres/MinIO running — they exercise pure units only.
"""
from __future__ import annotations

from app.core.security import (
    create_access_token,
    create_agent_session_token,
    create_upload_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.services.billing import JobBillingInputs, PricingRates, calculate_amount
from app.services.storage import StorageService, TenantScopeViolation
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest


def test_password_roundtrip():
    h = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", h)
    assert not verify_password("wrong", h)


def test_access_token_roundtrip():
    t = create_access_token("tenant-123", "shop-abc", role="shopkeeper")
    claims = decode_token(t, expected_types={"access"})
    assert claims["tid"] == "tenant-123"
    assert claims["sub"] == "shop-abc"
    assert claims["role"] == "shopkeeper"


def test_agent_and_upload_tokens_are_distinct_types():
    agent = decode_token(create_agent_session_token("t", "a"), expected_types={"agent"})
    customer = decode_token(create_upload_token("t", "slug"), expected_types={"upload"})
    assert agent["typ"] == "agent"
    assert customer["typ"] == "upload"


def test_storage_key_helpers():
    assert StorageService.tenant_prefix("t1") == "tenants/t1/"
    assert StorageService.job_prefix("t1", "j1") == "tenants/t1/jobs/j1/"
    assert StorageService.original_key("t1", "j1", "doc.pdf") == "tenants/t1/jobs/j1/original/doc.pdf"
    # sanitize
    assert StorageService.original_key("t1", "j1", "../evil.pdf") == "tenants/t1/jobs/j1/original/evil.pdf"


def test_storage_scope_violation():
    svc = StorageService()
    with pytest.raises(TenantScopeViolation):
        svc._assert_tenant_scope("tenants/other/jobs/x/original/file.pdf", "t1")


def test_billing_bw_only():
    rates = PricingRates()
    amt = calculate_amount(rates, JobBillingInputs(total_pages=10, color_pages=0, copies=2))
    # 10 pages * 2 (bw_single) * 2 copies
    assert amt == 40.0


def test_billing_mixed_color():
    rates = PricingRates(bw_single=1.0, color_single=5.0)
    amt = calculate_amount(
        rates,
        JobBillingInputs(
            total_pages=10, color_pages=3, copies=1, color_mode="Color", print_side="Single"
        ),
    )
    # 3 color * 5 + 7 bw * 1 = 22
    assert amt == 22.0


def test_billing_double_sided():
    rates = PricingRates()
    amt = calculate_amount(
        rates,
        JobBillingInputs(
            total_pages=4, color_pages=0, copies=1, color_mode="Black & White", print_side="Double"
        ),
    )
    # 4 * 1.5 = 6.0
    assert amt == 6.0


# ============================================================================
# Job state machine
# ============================================================================


def _make_job(status: str = "AwaitingUpload") -> SimpleNamespace:
    """A minimal stand-in for a SQLAlchemy PrintJob row."""
    return SimpleNamespace(
        job_id="job-1",
        tenant_id="tenant-1",
        status=status,
        started_at=None,
        completed_at=None,
        error_message=None,
        object_key="tenants/tenant-1/jobs/job-1/original/doc.pdf",
        assets_deleted=False,
        assets_delete_scheduled=False,
        assets_delete_attempted_at=None,
        amount=0.0,
    )


@pytest.fixture
def no_side_effects(monkeypatch):
    """Silence storage + pub/sub so unit tests stay pure."""
    from app.services import jobs as jobs_service

    delete_prefix = MagicMock()
    monkeypatch.setattr(jobs_service.storage, "delete_prefix", delete_prefix)
    monkeypatch.setattr(jobs_service.storage, "job_prefix",
                        lambda tid, jid: f"tenants/{tid}/jobs/{jid}/")
    monkeypatch.setattr(jobs_service, "_publish_status", lambda job: None)
    return delete_prefix


def test_transition_happy_path(no_side_effects):
    from app.services.jobs import transition

    db = MagicMock()
    job = _make_job()

    transition(db, job, "Queued")
    assert job.status == "Queued"
    assert job.started_at is None

    transition(db, job, "Printing")
    assert job.status == "Printing"
    assert job.started_at is not None

    transition(db, job, "Completed")
    assert job.status == "Completed"
    assert job.completed_at is not None
    # Terminal reached once => cleanup called once
    assert no_side_effects.call_count == 1


def test_transition_rejects_illegal(no_side_effects):
    from app.services.jobs import transition
    from fastapi import HTTPException

    db = MagicMock()
    job = _make_job("Queued")

    with pytest.raises(HTTPException) as exc:
        transition(db, job, "Completed")
    assert exc.value.status_code == 409
    assert job.status == "Queued"  # unchanged on failure
    no_side_effects.assert_not_called()


def test_transition_is_idempotent(no_side_effects):
    from app.services.jobs import transition

    db = MagicMock()
    job = _make_job("Completed")
    job.assets_deleted = True  # already cleaned

    result = transition(db, job, "Completed")
    assert result is job
    assert job.status == "Completed"
    no_side_effects.assert_not_called()  # no second cleanup


def test_terminal_states_call_delete_prefix_exactly_once(no_side_effects):
    from app.services.jobs import transition

    db = MagicMock()
    job = _make_job("Printing")
    job.started_at = __import__("datetime").datetime.utcnow()

    transition(db, job, "Failed", error_message="printer jam")

    assert job.status == "Failed"
    assert job.error_message == "printer jam"
    assert job.completed_at is not None
    no_side_effects.assert_called_once()


def test_cleanup_marks_scheduled_on_storage_failure(monkeypatch):
    """If MinIO is flaky, we schedule a retry instead of crashing the request."""
    from app.services import jobs as jobs_service

    def boom(*_a, **_kw):
        raise RuntimeError("minio down")

    monkeypatch.setattr(jobs_service.storage, "delete_prefix", boom)
    monkeypatch.setattr(jobs_service.storage, "job_prefix",
                        lambda tid, jid: f"tenants/{tid}/jobs/{jid}/")
    monkeypatch.setattr(jobs_service, "_publish_status", lambda job: None)

    db = MagicMock()
    job = _make_job("Printing")
    job.started_at = __import__("datetime").datetime.utcnow()

    jobs_service.transition(db, job, "Completed")

    assert job.status == "Completed"
    assert job.assets_deleted is False
    assert job.assets_delete_scheduled is True
    assert job.assets_delete_attempted_at is not None
    # object_key is NOT cleared because cleanup didn't finish
    assert job.object_key.startswith("tenants/tenant-1/")


def test_terminal_state_rejects_further_transitions(no_side_effects):
    from app.services.jobs import transition
    from fastapi import HTTPException

    db = MagicMock()
    job = _make_job("Completed")

    with pytest.raises(HTTPException) as exc:
        transition(db, job, "Printing")
    assert exc.value.status_code == 409
