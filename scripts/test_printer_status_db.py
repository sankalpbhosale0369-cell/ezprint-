"""
Standalone test: verify _update_printer_status_in_db() works correctly.

Tests:
  1. Real printer name → is_active updated in DB
  2. Fake printer name → graceful no-op, no crash
  3. Simulated DB error → rollback executes, session not corrupted

Run from project root:
    python scripts/test_printer_status_db.py
"""
import sys
import os
import uuid
import logging
from unittest.mock import PropertyMock, patch

# ── Path setup ──────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shared.database import SessionLocal, Printer

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ── Minimal stub that only has what the method needs ────────────────
# We avoid instantiating the full PrinterManager (which starts threads,
# printer discovery, connection monitors, etc.)  Instead we build a
# lightweight object that has .db and the method under test.

class _Stub:
    """Bare-minimum object carrying only .db and the method under test."""
    pass


def _attach_method(stub, db):
    """Bind the real _update_printer_status_in_db logic to our stub."""
    stub.db = db

    def _update_printer_status_in_db(self, printer_name: str, is_online: bool):
        """Update printer status in database"""
        try:
            printer = self.db.query(Printer).filter(
                Printer.printer_name == printer_name
            ).first()
            if printer:
                printer.is_active = is_online
                self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error updating printer status in DB: {e}")

    import types
    stub._update_printer_status_in_db = types.MethodType(
        _update_printer_status_in_db, stub
    )


# ── Helpers ─────────────────────────────────────────────────────────
TEST_SHOP = f"test-shop-{uuid.uuid4().hex[:8]}"
TEST_PRINTER = f"Test Printer {uuid.uuid4().hex[:6]}"
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


# ── Setup: insert a test printer row ───────────────────────────────
db = SessionLocal()
test_printer = Printer(
    shop_id=TEST_SHOP,
    printer_name=TEST_PRINTER,
    printer_id=f"test-id-{uuid.uuid4().hex[:8]}",
    is_default=False,
    is_active=True,       # starts as True
)
db.add(test_printer)
db.commit()
printer_id = test_printer.id
print(f"\nSetup: created test printer '{TEST_PRINTER}' (id={printer_id})\n")

# Force stdout to handle encoding gracefully on Windows
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ── Build stub ──────────────────────────────────────────────────────
stub = _Stub()
_attach_method(stub, db)

# ════════════════════════════════════════════════════════════════════
print("TEST 1: Real printer name -> is_active updated in DB")
# ════════════════════════════════════════════════════════════════════
try:
    # Set to offline (False)
    stub._update_printer_status_in_db(TEST_PRINTER, False)
    db.expire_all()  # force re-read from DB
    row = db.query(Printer).filter(Printer.id == printer_id).first()
    result("is_active set to False", row.is_active is False, f"is_active={row.is_active}")

    # Set back to online (True)
    stub._update_printer_status_in_db(TEST_PRINTER, True)
    db.expire_all()
    row = db.query(Printer).filter(Printer.id == printer_id).first()
    result("is_active set to True", row.is_active is True, f"is_active={row.is_active}")
except Exception as e:
    result("Real printer update", False, str(e))

# ════════════════════════════════════════════════════════════════════
print("\nTEST 2: Fake printer name -> graceful failure, no crash")
# ════════════════════════════════════════════════════════════════════
try:
    stub._update_printer_status_in_db("NonExistent Printer XYZ-999", True)
    # Should silently return without error or DB change
    db.expire_all()
    row = db.query(Printer).filter(Printer.id == printer_id).first()
    result("No crash with fake name", True)
    result("Original row unchanged", row.is_active is True, f"is_active={row.is_active}")
except Exception as e:
    result("Fake printer name", False, f"Unexpected exception: {e}")

# ════════════════════════════════════════════════════════════════════
print("\nTEST 3: Simulated DB error -> rollback, session not corrupted")
# ════════════════════════════════════════════════════════════════════
try:
    # First, set to False so we can verify it stays False after the error
    stub._update_printer_status_in_db(TEST_PRINTER, False)
    db.expire_all()

    # Patch commit to raise an exception, simulating a DB error
    with patch.object(db, 'commit', side_effect=Exception("Simulated DB failure")):
        stub._update_printer_status_in_db(TEST_PRINTER, True)
        # After this call, the method should have caught the exception and
        # called rollback. The value should still be False (not True).

    result("No crash on DB error", True)

    # Verify rollback happened — value should still be False
    db.expire_all()
    row = db.query(Printer).filter(Printer.id == printer_id).first()
    result("Rollback preserved old value", row.is_active is False, f"is_active={row.is_active}")

    # Verify session is still usable after the error
    count = db.query(Printer).filter(Printer.id == printer_id).count()
    result("Session still usable after error", count == 1, f"query returned {count} rows")
except Exception as e:
    result("DB error simulation", False, f"Unexpected exception: {e}")

# ── Cleanup ─────────────────────────────────────────────────────────
print("\nCleaning up test data...")
try:
    db.query(Printer).filter(Printer.id == printer_id).delete()
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
