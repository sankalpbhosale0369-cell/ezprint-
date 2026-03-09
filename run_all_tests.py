"""
Run all EzPrint test scripts and produce a full report.
"""
import subprocess
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE = os.path.dirname(os.path.abspath(__file__))

TEST_FILES = [
    # Root directory
    "test_crash_chain_fix.py",
    "test_db.py",
    "test_db_connection.py",
    "test_eventlet.py",
    "test_socketio.py",
    "test_step3_migration.py",
    "test_step4_migration.py",
    "test_step5_client.py",
    "test_url_processor.py",
    # scripts/ directory
    os.path.join("scripts", "test_duplex_flag.py"),
    os.path.join("scripts", "test_duplicate_upload.py"),
    os.path.join("scripts", "test_job_recovery.py"),
    os.path.join("scripts", "test_printer_status_db.py"),
    # scripts/tests/ directory
    os.path.join("scripts", "tests", "test_cloudinary.py"),
    os.path.join("scripts", "tests", "test_cloudinary_integration.py"),
    os.path.join("scripts", "tests", "test_db_connection.py"),
    os.path.join("scripts", "tests", "test_filter_logic.py"),
    os.path.join("scripts", "tests", "test_inference.py"),
    os.path.join("scripts", "tests", "test_security_and_config.py"),
]

REPORT_FILE = os.path.join(BASE, "test_report.txt")

results = []

with open(REPORT_FILE, "w", encoding="utf-8", errors="replace") as report:
    report.write("=" * 70 + "\n")
    report.write("  EzPrint Full Test Report\n")
    report.write("=" * 70 + "\n\n")

    for tf in TEST_FILES:
        full_path = os.path.join(BASE, tf)
        report.write("-" * 70 + "\n")
        report.write(f"FILE: {tf}\n")
        report.write("-" * 70 + "\n")

        if not os.path.exists(full_path):
            report.write("  STATUS: FILE NOT FOUND\n\n")
            results.append((tf, "NOT_FOUND", -1, "File does not exist"))
            continue

        try:
            r = subprocess.run(
                [sys.executable, full_path],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                cwd=BASE,
            )
            stdout = r.stdout or ""
            stderr = r.stderr or ""
            exit_code = r.returncode

            report.write(f"  EXIT CODE: {exit_code}\n")
            report.write(f"  STDOUT:\n")
            for line in stdout.splitlines():
                report.write(f"    {line}\n")
            if stderr.strip():
                report.write(f"  STDERR (last 800 chars):\n")
                for line in stderr[-800:].splitlines():
                    report.write(f"    {line}\n")
            report.write("\n")

            status = "PASS" if exit_code == 0 else "FAIL"
            detail = ""
            if exit_code != 0:
                # Try to extract failure info
                detail = stderr[-300:] if stderr else stdout[-300:]
            results.append((tf, status, exit_code, detail))

        except subprocess.TimeoutExpired:
            report.write("  STATUS: TIMEOUT (30s)\n\n")
            results.append((tf, "TIMEOUT", -1, "Script did not complete within 30s"))
        except Exception as e:
            report.write(f"  STATUS: ERROR - {e}\n\n")
            results.append((tf, "ERROR", -1, str(e)))

    # Summary
    report.write("\n" + "=" * 70 + "\n")
    report.write("  SUMMARY\n")
    report.write("=" * 70 + "\n\n")

    total = len(results)
    passed = sum(1 for _, s, _, _ in results if s == "PASS")
    failed = sum(1 for _, s, _, _ in results if s == "FAIL")
    errors = sum(1 for _, s, _, _ in results if s in ("TIMEOUT", "ERROR", "NOT_FOUND"))

    report.write(f"  Total test scripts: {total}\n")
    report.write(f"  Passed: {passed}\n")
    report.write(f"  Failed: {failed}\n")
    report.write(f"  Errors/Timeouts: {errors}\n\n")

    if failed > 0 or errors > 0:
        report.write("  FAILURES:\n")
        for name, status, code, detail in results:
            if status != "PASS":
                report.write(f"    [{status}] {name} (exit code: {code})\n")
                if detail:
                    for line in detail.strip().splitlines()[-5:]:
                        report.write(f"      {line}\n")
                report.write("\n")

    report.write("=" * 70 + "\n")

print(f"Report written to: {REPORT_FILE}")

# Also print summary to console
print(f"\nTotal: {total} | Passed: {passed} | Failed: {failed} | Errors: {errors}")
for name, status, code, detail in results:
    icon = "PASS" if status == "PASS" else "FAIL" if status == "FAIL" else status
    print(f"  [{icon}] {name} (exit={code})")

sys.exit(0)
