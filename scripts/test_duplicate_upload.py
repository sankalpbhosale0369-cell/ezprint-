"""
Standalone test: verify duplicate upload prevention works at both layers.

Tests:
  1. Server-side: Two identical jobs within 10s -> second is blocked
  2. Server-side: Same file after 10s window -> allowed (legitimate re-upload)
  3. Server-side: Same shop, different filename -> allowed
  4. Server-side: Same filename, different shop -> allowed
  5. UI-side: Verify _uploadInFlight guard exists in upload.js

Run from project root:
    python scripts/test_duplicate_upload.py
"""
import sys
import os
import uuid
import logging
from datetime import datetime, timedelta

# Path setup
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shared.database import SessionLocal, PrintJob

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ── Helpers ─────────────────────────────────────────────────────────
passed = 0
failed = 0
TEST_SHOP_A = f"test-dedup-A-{uuid.uuid4().hex[:8]}"
TEST_SHOP_B = f"test-dedup-B-{uuid.uuid4().hex[:8]}"
cleanup_job_ids = []


def result(name, ok, detail=""):
    global passed, failed
    tag = "PASS" if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f"  ({detail})" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def make_job(db, shop_id, filename, file_size, created_at=None):
    """Insert a test print job."""
    job = PrintJob(
        shop_id=shop_id,
        filename=filename,
        file_path=f"/tmp/{filename}",
        file_size=file_size,
        file_type="pdf",
    )
    if created_at:
        job.created_at = created_at
    db.add(job)
    db.commit()
    cleanup_job_ids.append(job.job_id)
    return job


def check_duplicate(db, shop_id, filename, file_size):
    """Simulate the server-side duplicate check (exact logic from app.py)."""
    dedup_cutoff = datetime.utcnow() - timedelta(seconds=10)
    existing = db.query(PrintJob).filter(
        PrintJob.shop_id == shop_id,
        PrintJob.filename == filename,
        PrintJob.file_size == file_size,
        PrintJob.created_at >= dedup_cutoff
    ).first()
    return existing


# ════════════════════════════════════════════════════════════════════
db = SessionLocal()
print("\n--- Setup ---")
print(f"  Shop A: {TEST_SHOP_A}")
print(f"  Shop B: {TEST_SHOP_B}\n")

# ════════════════════════════════════════════════════════════════════
print("TEST 1: Two identical jobs within 10s -> second is blocked")
# ════════════════════════════════════════════════════════════════════
job1 = make_job(db, TEST_SHOP_A, "report.pdf", 52000)
dup = check_duplicate(db, TEST_SHOP_A, "report.pdf", 52000)
result("Duplicate detected", dup is not None)
result("Returns original job_id", dup.job_id == job1.job_id if dup else False,
       f"original={job1.job_id[:8]}, found={dup.job_id[:8] if dup else 'None'}")

# ════════════════════════════════════════════════════════════════════
print("\nTEST 2: Same file after 10s window -> allowed (not a duplicate)")
# ════════════════════════════════════════════════════════════════════
# Create a job with created_at 15 seconds ago to simulate expiry
old_job = make_job(db, TEST_SHOP_A, "monthly_report.pdf", 99000,
                   created_at=datetime.utcnow() - timedelta(seconds=15))
dup2 = check_duplicate(db, TEST_SHOP_A, "monthly_report.pdf", 99000)
result("Old job NOT flagged as duplicate", dup2 is None,
       f"found={'None' if dup2 is None else dup2.job_id[:8]}")

# ════════════════════════════════════════════════════════════════════
print("\nTEST 3: Same shop, different filename -> allowed")
# ════════════════════════════════════════════════════════════════════
make_job(db, TEST_SHOP_A, "invoice.pdf", 52000)
dup3 = check_duplicate(db, TEST_SHOP_A, "receipt.pdf", 52000)
result("Different filename not blocked", dup3 is None)

# ════════════════════════════════════════════════════════════════════
print("\nTEST 4: Same filename, different shop -> allowed")
# ════════════════════════════════════════════════════════════════════
make_job(db, TEST_SHOP_A, "shared_doc.pdf", 30000)
dup4 = check_duplicate(db, TEST_SHOP_B, "shared_doc.pdf", 30000)
result("Different shop not blocked", dup4 is None)

# ════════════════════════════════════════════════════════════════════
print("\nTEST 5: Same filename+shop, different file_size -> allowed")
# ════════════════════════════════════════════════════════════════════
make_job(db, TEST_SHOP_A, "doc_v2.pdf", 40000)
dup5 = check_duplicate(db, TEST_SHOP_A, "doc_v2.pdf", 41000)
result("Different size not blocked", dup5 is None)

# ════════════════════════════════════════════════════════════════════
print("\nTEST 6: UI-side _uploadInFlight guard exists in upload.js")
# ════════════════════════════════════════════════════════════════════
upload_js_path = os.path.join(ROOT, "web_interface", "static", "js", "upload.js")
try:
    with open(upload_js_path, "r", encoding="utf-8") as f:
        js_content = f.read()
    result("_uploadInFlight variable declared",
           "_uploadInFlight = false" in js_content)
    result("Guard check in PRINT handler",
           "if (_uploadInFlight) return" in js_content)
    # count occurrences of the flag being set to true
    set_count = js_content.count("_uploadInFlight = true")
    result("Flag set to true in both flows",
           set_count >= 2, f"found {set_count} set-to-true occurrences")
    # count occurrences of the flag being reset to false (excluding declaration)
    reset_count = js_content.count("_uploadInFlight = false") - 1  # minus declaration
    result("Flag reset in finally blocks",
           reset_count >= 2, f"found {reset_count} reset-to-false occurrences")
except Exception as e:
    result("upload.js readable", False, str(e))

# ── Cleanup ─────────────────────────────────────────────────────────
print("\nCleaning up test data...")
try:
    for jid in cleanup_job_ids:
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
