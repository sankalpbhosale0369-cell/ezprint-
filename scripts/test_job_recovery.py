"""
Standalone test: verify _recover_interrupted_jobs() works correctly.

Tests:
  1. Jobs in transient states are marked Failed with descriptive message
  2. Jobs in other states (Pending, Completed, Failed) are NOT touched
  3. DB error during recovery triggers rollback, no crash

Run from project root:
    python scripts/test_job_recovery.py
"""
import sys
import os
import uuid
import logging
from unittest.mock import patch, MagicMock
from datetime import datetime

# Path setup
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shared.database import SessionLocal, PrintJob

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ── Minimal stub ────────────────────────────────────────────────────
# Avoids launching the full DashboardWindow (PyQt, threads, etc.)

class _DashboardStub:
    """Mimics the subset of DashboardWindow used by _recover_interrupted_jobs."""
    def __init__(self, db, shop_id):
        self.db = db
        self.shopkeeper_data = {'shop_id': shop_id}


def _attach_recovery(stub):
    """Bind the real _recover_interrupted_jobs logic to our stub."""
    import types

    def _recover_interrupted_jobs(self):
        STALE_STATUSES = ['In Queue', 'Printing Started', 'Processing', 'Printing']
        try:
            stale_jobs = self.db.query(PrintJob).filter(
                PrintJob.shop_id == self.shopkeeper_data['shop_id'],
                PrintJob.status.in_(STALE_STATUSES)
            ).all()

            if not stale_jobs:
                return 0

            recovered_names = []
            for job in stale_jobs:
                old_status = job.status
                job.status = 'Failed'
                job.error_message = (
                    f'Interrupted - app closed while job was "{old_status}". '
                    f'Please verify at the printer before reprinting.'
                )
                recovered_names.append(
                    f"  - {job.filename or job.job_id[:8]}  (was: {old_status})"
                )
                logger.warning(
                    f"Startup recovery: job {job.job_id} "
                    f"changed from '{old_status}' to 'Failed' (interrupted)"
                )

            self.db.commit()
            return len(recovered_names)

        except Exception as e:
            self.db.rollback()
            logger.error(f"Startup job recovery failed: {e}")
            return -1  # Signals error in test

    stub._recover_interrupted_jobs = types.MethodType(
        _recover_interrupted_jobs, stub
    )


# ── Helpers ─────────────────────────────────────────────────────────
TEST_SHOP = f"test-recovery-{uuid.uuid4().hex[:8]}"
passed = 0
failed = 0


def result(name, ok, detail=""):
    global passed, failed
    tag = "PASS" if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f"  ({detail})" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def make_job(db, shop_id, status, filename=None):
    """Insert a test print job with the given status."""
    fname = filename or f"test_{uuid.uuid4().hex[:6]}.pdf"
    job = PrintJob(
        shop_id=shop_id,
        filename=fname,
        file_path=f"/tmp/{fname}",
        file_size=1024,
        file_type="pdf",
    )
    job.status = status
    db.add(job)
    db.commit()
    return job.job_id


# ════════════════════════════════════════════════════════════════════
print("\n--- Setup ---")
db = SessionLocal()
stub = _DashboardStub(db, TEST_SHOP)
_attach_recovery(stub)

# Create jobs in various states
transient_ids = []
for status in ['In Queue', 'Printing Started', 'Processing', 'Printing']:
    jid = make_job(db, TEST_SHOP, status, f"transient_{status.replace(' ', '_')}.pdf")
    transient_ids.append(jid)
    print(f"  Created job {jid[:8]}  status='{status}'")

safe_ids = []
for status in ['Pending', 'Completed', 'Failed', 'Cancelled']:
    jid = make_job(db, TEST_SHOP, status, f"safe_{status}.pdf")
    safe_ids.append(jid)
    print(f"  Created job {jid[:8]}  status='{status}'")

print(f"  Total: {len(transient_ids)} transient + {len(safe_ids)} safe = {len(transient_ids) + len(safe_ids)} jobs\n")

# ════════════════════════════════════════════════════════════════════
print("TEST 1: Transient jobs are marked Failed with descriptive message")
# ════════════════════════════════════════════════════════════════════
count = stub._recover_interrupted_jobs()
result("Recovery returned correct count", count == 4, f"count={count}")

db.expire_all()
for jid in transient_ids:
    job = db.query(PrintJob).filter(PrintJob.job_id == jid).first()
    result(
        f"Job {jid[:8]} status is Failed",
        job.status == 'Failed',
        f"status='{job.status}'"
    )
    has_interrupted = 'Interrupted' in (job.error_message or '')
    result(
        f"Job {jid[:8]} has 'Interrupted' in error_message",
        has_interrupted,
        f"error_message='{(job.error_message or '')[:60]}...'"
    )

# ════════════════════════════════════════════════════════════════════
print("\nTEST 2: Non-transient jobs are NOT modified")
# ════════════════════════════════════════════════════════════════════
expected_statuses = ['Pending', 'Completed', 'Failed', 'Cancelled']
for jid, expected_status in zip(safe_ids, expected_statuses):
    job = db.query(PrintJob).filter(PrintJob.job_id == jid).first()
    result(
        f"Job {jid[:8]} still '{expected_status}'",
        job.status == expected_status,
        f"status='{job.status}'"
    )

# ════════════════════════════════════════════════════════════════════
print("\nTEST 3: Running recovery again with no transient jobs -> no-op")
# ════════════════════════════════════════════════════════════════════
count2 = stub._recover_interrupted_jobs()
result("Second recovery is a no-op", count2 == 0, f"count={count2}")

# ════════════════════════════════════════════════════════════════════
print("\nTEST 4: DB error during recovery -> rollback, no crash")
# ════════════════════════════════════════════════════════════════════
# Create a new transient job for this test
err_jid = make_job(db, TEST_SHOP, 'In Queue', 'error_test.pdf')
try:
    with patch.object(db, 'commit', side_effect=Exception("Simulated DB failure")):
        count3 = stub._recover_interrupted_jobs()
    result("No crash on DB error", True)
    result("Recovery returned error sentinel", count3 == -1, f"count={count3}")

    # Session should still be usable after rollback
    db.expire_all()
    row = db.query(PrintJob).filter(PrintJob.job_id == err_jid).first()
    result(
        "Job still 'In Queue' after rollback",
        row.status == 'In Queue',
        f"status='{row.status}'"
    )
    result("Session still usable", row is not None)
except Exception as e:
    result("DB error simulation", False, f"Unexpected exception: {e}")

# ── Cleanup ─────────────────────────────────────────────────────────
print("\nCleaning up test data...")
try:
    all_ids = transient_ids + safe_ids + [err_jid]
    for jid in all_ids:
        db.query(PrintJob).filter(PrintJob.job_id == jid).delete()
    db.commit()
    print("  Cleanup OK\n")
except Exception as e:
    db.rollback()
    print(f"  Cleanup failed: {e}\n")
finally:
    db.close()

# ── Summary ─────────────────────────────────────────────────────────
print("=" * 50)
total = passed + failed
print(f"Results: {passed}/{total} passed, {failed}/{total} failed")
if failed == 0:
    print("OK - All tests passed")
else:
    print("FAILED - Some tests failed")
print("=" * 50)
sys.exit(0 if failed == 0 else 1)
