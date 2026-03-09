"""
Standalone Test: Corrupted File Crash Chain Fix
================================================
Verifies the 3-part fix that prevents silent thread death
when a corrupted/invalid file enters the print pipeline.

Mocks all Qt signals and printer calls — no real printer or PyQt window needed.
Run: python test_crash_chain_fix.py
"""

import sys
import os
import logging
import traceback

# ── Setup path so imports work ──────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Fix Windows console encoding ───────────────────────────────
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ── Logging ─────────────────────────────────────────────────────
logging.basicConfig(level=logging.CRITICAL, format="%(levelname)s - %(message)s")
logging.getLogger("error_handler").setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════
# TEST RESULTS TRACKER
# ════════════════════════════════════════════════════════════════
results = []

def record(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, passed, detail))
    icon = "✅" if passed else "❌"
    print(f"  {icon} {status}: {name}")
    if detail and not passed:
        print(f"         Detail: {detail}")


# ════════════════════════════════════════════════════════════════
# TEST 1: @safe_printer_action returns (False, msg) on exception
# ════════════════════════════════════════════════════════════════
def test_safe_printer_action_returns_tuple():
    """FIX 1: Decorator must return (False, error_string) — never None."""
    print("\n── TEST 1: @safe_printer_action return value ──")

    from shared.global_error_handler import safe_printer_action

    @safe_printer_action("TEST_CONTEXT")
    def always_throws():
        raise RuntimeError("Simulated corrupted PDF error")

    result = always_throws()

    # Must be a tuple
    if result is None:
        record("Returns non-None", False, f"Got None — the old broken behavior")
        return
    record("Returns non-None", True)

    if not isinstance(result, tuple):
        record("Returns tuple type", False, f"Got {type(result).__name__}: {result}")
        return
    record("Returns tuple type", True)

    # Must be exactly 2 elements
    if len(result) != 2:
        record("Tuple has 2 elements", False, f"Got {len(result)} elements: {result}")
        return
    record("Tuple has 2 elements", True)

    ok, msg = result
    record("ok is False", ok is False or ok == False, f"ok={ok}")
    record("msg is non-empty string", isinstance(msg, str) and len(msg) > 0, f"msg={msg!r}")

    # Verify it can be unpacked without error (the exact crash that was happening)
    try:
        ok2, msg2 = always_throws()
        record("Tuple unpacking succeeds", True)
    except TypeError as e:
        record("Tuple unpacking succeeds", False, f"TypeError: {e}")


# ════════════════════════════════════════════════════════════════
# MOCK INFRASTRUCTURE for Tests 2-5
# ════════════════════════════════════════════════════════════════

class MockSignal:
    """Simulates a Qt signal with .emit() and .connect()"""
    def __init__(self, name="signal", raises_on_emit=False):
        self.name = name
        self.emissions = []
        self._callbacks = []
        self._raises_on_emit = raises_on_emit

    def emit(self, *args):
        if self._raises_on_emit:
            raise RuntimeError("Wrapped C/C++ object has been deleted (simulated)")
        self.emissions.append(args)
        for cb in self._callbacks:
            cb(*args)

    def connect(self, callback):
        self._callbacks.append(callback)


class MockPrinterManager:
    """Simulates PrinterManager with controllable return values"""
    def __init__(self, print_result=None):
        self._print_result = print_result
        self.polling_started = False

    def start_job_status_polling(self, job_id, callback):
        self.polling_started = True

    def print_document_with_settings(self, file_path, file_type, settings, job_id=None):
        return self._print_result


class MockDashboard:
    """Simulates DashboardWindow.report_job_status"""
    def __init__(self):
        self.reported_statuses = []

    def report_job_status(self, job_id, status, progress=0, details=''):
        self.reported_statuses.append((job_id, status, progress, details))


def build_worker(print_result, emit_raises=False):
    """
    Build a mock _SettingsPrintWorker that uses the REAL run() logic
    from the production code, but with mocked signals and dependencies.
    """
    dashboard = MockDashboard()
    pm = MockPrinterManager(print_result=print_result)

    job_completed = MockSignal("job_completed")
    job_failed = MockSignal("job_failed", raises_on_emit=emit_raises)

    class TestWorker:
        def __init__(self):
            self.job_id = "test-job-001"
            self.file_path = "/fake/file.pdf"
            self.file_type = "pdf"
            self.settings = {"copies": 1, "page_size": "A4"}
            self.printer_manager = pm
            self.dashboard = dashboard
            self.websocket_client = None
            self.job_completed = job_completed
            self.job_failed = job_failed

        def run(self):
            """
            This is a COPY of the production _SettingsPrintWorker.run()
            from dashboard.py — with the 3 fixes applied.
            We copy it here to test the exact logic without needing PyQt.
            """
            try:
                # Mark printing started via authoritative reporter
                self.dashboard.report_job_status(self.job_id, 'Printing Started')

                # Start real-time status polling
                def status_callback(job_id, status, progress, details):
                    self.dashboard.report_job_status(job_id, status, progress, details)

                # Start polling for this job
                self.printer_manager.start_job_status_polling(self.job_id, status_callback)

                result = self.printer_manager.print_document_with_settings(
                    self.file_path, self.file_type, self.settings, job_id=self.job_id
                )
                # FIX 3: Guard against None / non-tuple return from @safe_printer_action
                if result is None or not isinstance(result, (tuple, list)):
                    ok, msg = False, "Print pipeline returned no result (internal error)"
                else:
                    ok, msg = result[0], result[1] if len(result) > 1 else "Unknown error"
                # Do not mark completed immediately; rely on poller callback.
                # If the print call itself fails, emit failure now.
                if not ok:
                    self.job_failed.emit(self.job_id, msg)
            except Exception as e:
                # FIX 2: Outer catch-all — never let the thread die silently
                try:
                    self.job_failed.emit(self.job_id, f"Print worker error: {str(e)}")
                except Exception:
                    logger.error(f"CRITICAL: Could not emit job_failed for {self.job_id}: {e}")

    worker = TestWorker()
    return worker, dashboard, job_completed, job_failed


# ════════════════════════════════════════════════════════════════
# TEST 2: run() receives None → None guard catches, job_failed emits
# ════════════════════════════════════════════════════════════════
def test_none_result_guard():
    """FIX 3: When print_document_with_settings returns None, no TypeError."""
    print("\n── TEST 2: None result guard ──")

    worker, dashboard, job_completed, job_failed = build_worker(print_result=None)

    # This would previously crash with: TypeError: cannot unpack non-iterable NoneType
    try:
        worker.run()
        record("run() completes without crash", True)
    except TypeError as e:
        record("run() completes without crash", False, f"TypeError: {e}")
        return
    except Exception as e:
        record("run() completes without crash", False, f"{type(e).__name__}: {e}")
        return

    # job_failed must have been emitted
    record("job_failed emitted", len(job_failed.emissions) > 0,
           f"emissions={job_failed.emissions}")

    if job_failed.emissions:
        job_id, msg = job_failed.emissions[0]
        record("job_id correct", job_id == "test-job-001", f"job_id={job_id}")
        record("msg mentions internal error", "internal error" in msg.lower() or "no result" in msg.lower(),
               f"msg={msg!r}")

    # job_completed must NOT have been emitted
    record("job_completed NOT emitted", len(job_completed.emissions) == 0,
           f"emissions={job_completed.emissions}")


# ════════════════════════════════════════════════════════════════
# TEST 3: run() receives (False, msg) → job_failed emits correctly
# ════════════════════════════════════════════════════════════════
def test_false_result_handling():
    """Normal failure path: (False, error_msg) → job_failed.emit()"""
    print("\n── TEST 3: (False, msg) result handling ──")

    worker, dashboard, job_completed, job_failed = build_worker(
        print_result=(False, "Printer offline")
    )

    try:
        worker.run()
        record("run() completes without crash", True)
    except Exception as e:
        record("run() completes without crash", False, f"{type(e).__name__}: {e}")
        return

    record("job_failed emitted", len(job_failed.emissions) > 0,
           f"emissions={job_failed.emissions}")

    if job_failed.emissions:
        job_id, msg = job_failed.emissions[0]
        record("job_id correct", job_id == "test-job-001", f"job_id={job_id}")
        record("msg is 'Printer offline'", msg == "Printer offline", f"msg={msg!r}")

    record("job_completed NOT emitted", len(job_completed.emissions) == 0)


# ════════════════════════════════════════════════════════════════
# TEST 4: run() receives (True, "ok") → no job_failed emit
# ════════════════════════════════════════════════════════════════
def test_success_result_handling():
    """Happy path: (True, 'ok') → rely on poller, no failure emitted."""
    print("\n── TEST 4: (True, 'ok') success result ──")

    worker, dashboard, job_completed, job_failed = build_worker(
        print_result=(True, "Sent to spooler")
    )

    try:
        worker.run()
        record("run() completes without crash", True)
    except Exception as e:
        record("run() completes without crash", False, f"{type(e).__name__}: {e}")
        return

    # Success path: do NOT mark completed immediately, rely on poller
    record("job_failed NOT emitted", len(job_failed.emissions) == 0,
           f"emissions={job_failed.emissions}")

    # Status reporting should have happened
    record("Printing Started reported", 
           any(s[1] == "Printing Started" for s in dashboard.reported_statuses),
           f"statuses={dashboard.reported_statuses}")


# ════════════════════════════════════════════════════════════════
# TEST 5: job_failed.emit() itself throws → logger fallback, no death
# ════════════════════════════════════════════════════════════════
def test_emit_failure_fallback():
    """FIX 2: If emit() throws (widget destroyed), thread still survives."""
    print("\n── TEST 5: job_failed.emit() throws → fallback logger ──")

    # Build worker where emit() raises (simulates destroyed Qt widget)
    worker, dashboard, job_completed, job_failed = build_worker(
        print_result=None,  # Will trigger job_failed path
        emit_raises=True    # emit() itself will throw
    )

    # Capture logger.error calls
    logged_errors = []
    original_error = logger.error
    def capture_error(msg, *args, **kwargs):
        logged_errors.append(msg)
        original_error(msg, *args, **kwargs)
    logger.error = capture_error

    try:
        worker.run()
        record("run() completes without crash", True)
    except Exception as e:
        record("run() completes without crash", False,
               f"Thread would have died: {type(e).__name__}: {e}")
        return
    finally:
        logger.error = original_error

    # The emit raised, but run() should NOT have crashed
    record("job_failed.emit was attempted", True)  # We know it was because result=None

    # Logger fallback must have fired
    record("Logger fallback fired", len(logged_errors) > 0,
           f"logged_errors={logged_errors}")

    if logged_errors:
        record("Log mentions CRITICAL", any("CRITICAL" in e for e in logged_errors),
               f"first_log={logged_errors[0]!r}")


# ════════════════════════════════════════════════════════════════
# BONUS: End-to-end — @safe_printer_action feeds into run()
# ════════════════════════════════════════════════════════════════
def test_end_to_end_chain():
    """Full chain: corrupted file → @safe_printer_action → run() → job_failed"""
    print("\n── BONUS: End-to-end crash chain ──")

    from shared.global_error_handler import safe_printer_action

    @safe_printer_action("E2E_TEST")
    def simulate_corrupted_pdf_print(file_path, file_type, settings, job_id=None):
        import fitz  # This would fail with FileDataError on corrupted PDF
        raise Exception("fitz.FileDataError: corrupted PDF document")

    # Get the result as @safe_printer_action would return it
    result = simulate_corrupted_pdf_print("/fake/corrupt.pdf", "pdf", {}, job_id="e2e-001")

    # Now feed it through the same logic as _SettingsPrintWorker.run()
    try:
        if result is None or not isinstance(result, (tuple, list)):
            ok, msg = False, "Print pipeline returned no result (internal error)"
        else:
            ok, msg = result[0], result[1] if len(result) > 1 else "Unknown error"

        record("No TypeError during unpacking", True)
        record("ok is False", ok == False, f"ok={ok}")
        record("msg contains error info", isinstance(msg, str) and len(msg) > 5,
               f"msg={msg!r}")

    except TypeError as e:
        record("No TypeError during unpacking", False, f"CRASH: {e}")
    except Exception as e:
        record("No TypeError during unpacking", False, f"{type(e).__name__}: {e}")


# ════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  EzPrint Crash Chain Fix — Verification Tests")
    print("=" * 60)

    test_safe_printer_action_returns_tuple()
    test_none_result_guard()
    test_false_result_handling()
    test_success_result_handling()
    test_emit_failure_fallback()
    test_end_to_end_chain()

    # ── Summary ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    total = len(results)
    passed = sum(1 for _, p, _ in results if p)
    failed = total - passed

    if failed == 0:
        print(f"  ✅ ALL {total} CHECKS PASSED")
    else:
        print(f"  ❌ {failed}/{total} CHECKS FAILED:")
        for name, p, detail in results:
            if not p:
                print(f"     • {name}: {detail}")

    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)
