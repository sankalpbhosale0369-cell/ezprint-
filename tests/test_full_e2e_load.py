#!/usr/bin/env python
"""
EzPrint — Full End-to-End Virtual Load Test
=============================================
Standalone script for comprehensive testing and load simulation.
Dependencies: requests, threading, time, random, os, json, uuid

Usage:
    python tests/test_full_e2e_load.py
"""

import requests
import threading
import time
import random
import os
import json
import uuid
import io
import sys
from datetime import datetime

# Add parent directory to sys.path to allow importing from shared
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Configuration ────────────────────────────────────────────────────────────
BASE_URL = "http://127.0.0.1:5000"
TIMEOUT = 60  # Increased for slow cloud uploads/processing

# ── Reporting State ─────────────────────────────────────────────────────────
# ... (rest stays the same)
results = {
    "SCENARIO 1": {"pass": [], "fail": []},
    "SCENARIO 2": {"pass": [], "fail": []},
    "SCENARIO 3": {"pass": [], "fail": []},
    "SCENARIO 4": {"pass": [], "fail": []},
    "SCENARIO 5": {"pass": [], "fail": []},
    "SCENARIO 6": {"pass": [], "fail": []},
}
results_lock = threading.Lock()
created_job_ids = []
created_shopkeepers = []
created_printers = []

# ── Helpers ──────────────────────────────────────────────────────────────────

def record(scenario, passed, label, detail=None, endpoint=None, payload=None, response=None, fix=None):
    with results_lock:
        bucket = "pass" if passed else "fail"
        entry = {
            "label": label,
            "detail": detail,
            "endpoint": endpoint,
            "payload": payload,
            "response": response,
            "fix": fix
        }
        results[scenario][bucket].append(entry)

def api_call(method, path, **kwargs):
    kwargs.setdefault("timeout", TIMEOUT)
    url = f"{BASE_URL}{path}"
    try:
        return getattr(requests, method.lower())(url, **kwargs)
    except Exception as e:
        print(f"DEBUG: API call failed to {url}: {e}")
        return None

def create_fake_pdf(unique_id=None):
    """Create a minimal PDF file."""
    buf = io.BytesIO()
    buf.write(b"%PDF-1.1\n")
    if unique_id:
        buf.write(f"% {unique_id}\n".encode())
    buf.write(b"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n")
    buf.write(b"2 0 obj <</Type /Pages /Count 1 /Kids [3 0 R]>> endobj\n")
    buf.write(b"3 0 obj <</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]>> endobj\n")
    buf.write(b"xref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000052 00000 n\n0000000101 00000 n\ntrailer <</Size 4 /Root 1 0 R>>\nstartxref\n158\n%%EOF")
    buf.seek(0)
    return buf

# ── Scenario Logic ────────────────────────────────────────────────────────────

def scenario_1_worker(i, shop_id):
    customer_id = f"Cust_{i}_{uuid.uuid4().hex[:4]}"
    
    # 1. Upload a PRINT job
    pdf = create_fake_pdf(unique_id=customer_id)
    pages = random.choice(["all", "1-3"])
    copies = random.randint(1, 3)
    side = random.choice(["single", "double"]) # app expects Single/Double? Let's check app.py
    # app.py expects:
    # print_side = request.form.get('print_side', 'Single')
    # color_mode = request.form.get('color_mode', 'Black & White')
    side_val = "Single" if side == "single" else "Double"
    color_val = random.choice(["Black & White", "Color"])
    
    data = {
        "shop_id": shop_id,
        "page_range": pages,
        "copies": str(copies),
        "print_side": side_val,
        "color_mode": color_val,
        "source": "print"
    }
    files = {"file": ("test.pdf", pdf, "application/pdf")}
    
    resp = api_call("POST", "/api/upload", data=data, files=files)
    if resp and resp.status_code == 200 and resp.json().get("success"):
        jid = resp.json().get("job_id")
        with results_lock:
            created_job_ids.append(jid)
        record("SCENARIO 1", True, f"Customer {i} uploaded PRINT job {jid}")
    else:
        record("SCENARIO 1", False, f"Customer {i} failed to upload PRINT job", 
               endpoint="/api/upload", response=resp.text if resp else "Connection error",
               fix="web_interface/app.py (upload_file)")

    # 2. Upload a XEROX job
    pdf = create_fake_pdf(unique_id=f"xerox_{customer_id}")
    data["source"] = "xerox"
    files = {"file[]": ("xerox.pdf", pdf, "application/pdf")} # Xerox flow in app.py expects file[]
    resp = api_call("POST", "/api/upload", data=data, files=files)
    if resp and resp.status_code == 200 and resp.json().get("success"):
        jid = resp.json().get("job_id")
        with results_lock:
            created_job_ids.append(jid)
        record("SCENARIO 1", True, f"Customer {i} uploaded XEROX job {jid}")
    else:
        record("SCENARIO 1", False, f"Customer {i} failed to upload XEROX job",
               endpoint="/api/upload", response=resp.text if resp else "Connection error")

    # 3. DOUBLE CLICK simulation
    pdf = create_fake_pdf(unique_id=f"dup_{customer_id}")
    data["source"] = "print"
    files = {"file": (f"dup_{i}.pdf", pdf, "application/pdf")}
    
    # Send twice
    r1 = api_call("POST", "/api/upload", data=data, files=files)
    pdf.seek(0)
    files = {"file": (f"dup_{i}.pdf", pdf, "application/pdf")}
    r2 = api_call("POST", "/api/upload", data=data, files=files)
    
    if r1 and r2 and r1.status_code == 200 and r2.status_code == 200:
        j1 = r1.json().get("job_id")
        j2 = r2.json().get("job_id")
        is_dup = r2.json().get("duplicate", False) or j1 == j2
        if is_dup:
            record("SCENARIO 1", True, f"Double-click dedup blocked for customer {i}")
        else:
            record("SCENARIO 1", False, f"Double-click dedup failed for customer {i} (created {j1} and {j2})",
                   fix="web_interface/app.py (upload_file dedup logic)")
    
    # 4. Upload a CORRUPTED file
    resp = api_call("POST", "/api/upload", data=data, files={"file": ("corrupt.pdf", io.BytesIO(os.urandom(100)), "application/pdf")})
    if resp and resp.status_code != 500:
        record("SCENARIO 1", True, f"Corrupted file handled gracefully for customer {i} (Status: {resp.status_code})")
    else:
        record("SCENARIO 1", False, f"Corrupted file caused 500 or error for customer {i}",
               endpoint="/api/upload", response=resp.text if resp else "Connection error")

    # 5. Upload an OVERSIZED filename
    long_name = "a" * 500 + ".pdf"
    pdf.seek(0)
    resp = api_call("POST", "/api/upload", data=data, files={"file": (long_name, pdf, "application/pdf")})
    if resp and resp.status_code != 500:
        record("SCENARIO 1", True, f"Oversized filename handled for customer {i}")
    else:
        record("SCENARIO 1", False, f"Oversized filename caused error for customer {i}",
               endpoint="/api/upload", response=resp.text if resp else "Connection error")

def run_scenario_1(shop_id):
    print("Running Scenario 1: Multiple Customers Uploading...")
    threads = []
    for i in range(10):
        t = threading.Thread(target=scenario_1_worker, args=(i, shop_id))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

def run_scenario_2():
    print("Running Scenario 2: Shopkeeper Auth...")
    for i in range(3):
        uname = f"test_shop_{uuid.uuid4().hex[:6]}"
        email = f"{uname}@example.com"
        passwd = "password123"
        
        # 1. Register (Attempt API)
        # Note: /api/register might not exist, but we must try as per request
        reg_payload = {
            "username": uname,
            "email": email,
            "password": passwd,
            "shop_name": f"Test Shop {i}"
        }
        resp = api_call("POST", "/api/register", json=reg_payload)
        if resp and resp.status_code == 200:
            record("SCENARIO 2", True, f"Shopkeeper {i} registered via API")
        else:
            # Fallback for the sake of the test suite continuing
            # In a real senior QA role, we'd report this as a FAIL if the API is missing
            try:
                from shared.database import SessionLocal, Shopkeeper
                import bcrypt
                db = SessionLocal()
                sk = Shopkeeper(
                    username=uname, 
                    email=email, 
                    password_hash=bcrypt.hashpw(passwd.encode('utf-8'), bcrypt.gensalt()).decode('utf-8'),
                    shop_name=f"Test Shop {i}",
                    shop_id=str(uuid.uuid4())
                )
                db.add(sk)
                db.commit()
                shop_id = sk.shop_id
                db.close()
                created_shopkeepers.append(uname)
                record("SCENARIO 2", False, f"Shopkeeper {i} registration API missing (404), using DB fallback",
                       endpoint="/api/register", fix="web_interface/api/auth.py (Add /register endpoint)")
            except Exception as e:
                import traceback
                error_info = traceback.format_exc()
                record("SCENARIO 2", False, f"Shopkeeper {i} registration failed completely", detail=error_info)
                continue

        # 2. Login with username
        resp = api_call("POST", "/api/auth/login", json={"username": uname, "password": passwd})
        token = None
        if resp and resp.status_code == 200:
            token = resp.json().get("data", {}).get("session_token")
            record("SCENARIO 2", True, f"Shopkeeper {i} login (username) successful")
        else:
            record("SCENARIO 2", False, f"Shopkeeper {i} login (username) failed", endpoint="/api/auth/login")

        # 3. Login with email
        resp = api_call("POST", "/api/auth/login", json={"username": email, "password": passwd})
        if resp and resp.status_code == 200:
            record("SCENARIO 2", True, f"Shopkeeper {i} login (email) successful")
        else:
            record("SCENARIO 2", False, f"Shopkeeper {i} login (email) failed", endpoint="/api/auth/login")

        # 4. Wrong password
        resp = api_call("POST", "/api/auth/login", json={"username": uname, "password": "wrongpassword"})
        if resp and resp.status_code == 401:
            record("SCENARIO 2", True, f"Shopkeeper {i} wrong password rejected correctly")
        else:
            record("SCENARIO 2", False, f"Shopkeeper {i} wrong password NOT handled correctly", response=resp.text if resp else "Err")

        # 5. Forgot password
        resp = api_call("POST", "/api/forgot-password", json={"email": email})
        if resp and resp.status_code == 200:
            record("SCENARIO 2", True, f"Shopkeeper {i} forgot password flow initiated")
        else:
            record("SCENARIO 2", False, f"Forgot password API missing or failing", 
                   endpoint="/api/forgot-password", fix="web_interface/api/auth.py (Add /forgot-password endpoint)")

def run_scenario_3(shop_id, token):
    print("Running Scenario 3: Print Job Dashboard Flow...")
    headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Fetch all pending jobs
    resp = api_call("GET", f"/api/jobs/{shop_id}")
    if resp and resp.status_code == 200:
        jobs = resp.json().get("jobs", [])
        record("SCENARIO 3", True, f"Fetched {len(jobs)} pending jobs")
    else:
        record("SCENARIO 3", False, "Failed to fetch pending jobs", endpoint=f"/api/jobs/{shop_id}")

    # 2. Status transitions
    if created_job_ids:
        jid = created_job_ids[0]
        statuses = ["In Queue", "Printing Started", "Completed"]
        for s in statuses:
            # Note: API might not exist
            resp = api_call("PATCH", f"/api/jobs/{jid}/status", json={"status": s}, headers=headers)
            if resp and resp.status_code == 200:
                record("SCENARIO 3", True, f"Job {jid} transitioned to {s}")
            else:
                record("SCENARIO 3", False, f"Job status update API missing/failing for {s}", 
                       endpoint=f"/api/jobs/{jid}/status", fix="web_interface/api/jobs.py (Implement status update)")
                break

        # 3. Pickup
        resp = api_call("POST", f"/api/jobs/{jid}/pickup", headers=headers)
        if resp and resp.status_code == 200:
            record("SCENARIO 3", True, f"Job {jid} picked up")
        else:
            record("SCENARIO 3", False, f"Pickup API missing/failing", endpoint="/api/jobs/{job_id}/pickup")

        # 4. Cancel
        if len(created_job_ids) > 1:
            jid2 = created_job_ids[1]
            resp = api_call("POST", f"/api/jobs/{jid2}/cancel", headers=headers)
            if resp and resp.status_code == 200:
                record("SCENARIO 3", True, f"Job {jid2} cancelled correctly")
            else:
                record("SCENARIO 3", False, f"Cancel API missing/failing", endpoint="/api/jobs/{job_id}/cancel")

        # 5. Reprint
        if created_job_ids:
            jid = created_job_ids[0]
            resp = api_call("POST", f"/api/jobs/{jid}/reprint", headers=headers)
            if resp and resp.status_code == 200:
                record("SCENARIO 3", True, f"Job {jid} reprint triggered")
            else:
                record("SCENARIO 3", False, f"Reprint API missing/failing", endpoint="/api/jobs/{job_id}/reprint")

def run_scenario_4(shop_id, token):
    print("Running Scenario 4: Printer Simulation...")
    headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Register fake printer
    p_id = f"test_printer_{uuid.uuid4().hex[:4]}"
    payload = {"printer_name": "EzPrint_Test_Printer_01", "printer_id": p_id}
    resp = api_call("POST", "/api/shop/printers", json=payload, headers=headers)
    if resp and resp.status_code == 200:
        record("SCENARIO 4", True, "Fake printer registered successfully")
        created_printers.append(p_id)
    else:
        record("SCENARIO 4", False, "Printer registration API missing", 
               endpoint="/api/shop/printers", fix="web_interface/api/config.py (Add /printers POST)")

    # 2. Set default
    resp = api_call("PUT", f"/api/shop/printers/{p_id}/default", headers=headers)
    if resp and resp.status_code == 200:
        record("SCENARIO 4", True, "Printer set as default")
    else:
        record("SCENARIO 4", False, "Set default printer API missing", endpoint="/api/shop/printers/id/default")

    # 3. Offline/Online
    resp = api_call("POST", f"/api/shop/printers/{p_id}/status", json={"is_active": False}, headers=headers)
    if resp and resp.status_code == 200:
        record("SCENARIO 4", True, "Printer set to offline")
    else:
        record("SCENARIO 4", False, "Printer status update API missing", endpoint="/api/shop/printers/id/status")

def run_scenario_5(shop_id, token):
    print("Running Scenario 5: Stress Test...")
    stop_event = threading.Event()
    
    def upload_thread():
        while not stop_event.is_set():
            pdf = create_fake_pdf()
            api_call("POST", "/api/upload", data={"shop_id": shop_id, "source": "print"}, files={"file": ("stress.pdf", pdf, "application/pdf")})
            time.sleep(0.5)

    def poll_thread():
        while not stop_event.is_set():
            api_call("GET", f"/api/jobs/{shop_id}")
            time.sleep(1)

    threads = []
    for _ in range(5):
        t = threading.Thread(target=upload_thread)
        threads.append(t)
        t.start()
    
    p_t = threading.Thread(target=poll_thread)
    threads.append(p_t)
    p_t.start()

    time.sleep(30)
    stop_event.set()
    for t in threads:
        t.join()
    
    h_resp = api_call("GET", "/api/health")
    if h_resp and h_resp.status_code == 200:
        record("SCENARIO 5", True, "Stress test complete, server remains healthy")
    else:
        record("SCENARIO 5", False, "Server UNHEALTHY after stress test", response=h_resp.text if h_resp else "Err")

def run_scenario_6(shop_id):
    print("Running Scenario 6: Edge Cases...")
    
    # 1. Empty file
    resp = api_call("POST", "/api/upload", data={"shop_id": shop_id}, files={"file": ("empty.pdf", b"", "application/pdf")})
    if resp and resp.status_code == 400:
        record("SCENARIO 6", True, "Empty file upload rejected correctly (400)")
    else:
        record("SCENARIO 6", False, "Empty file upload NOT handled correctly", response=resp.status_code if resp else "Err")

    # 2. Non-PDF
    resp = api_call("POST", "/api/upload", data={"shop_id": shop_id}, files={"file": ("evil.exe", b"binary", "application/octet-stream")})
    if resp and resp.status_code == 400:
        record("SCENARIO 6", True, "Non-PDF file upload rejected correctly")
    else:
        record("SCENARIO 6", False, "Non-PDF file upload NOT handled correctly", response=resp.status_code if resp else "Err")

    # 3. Non-existent job
    resp = api_call("GET", "/api/job/fake_id/status")
    if resp and resp.status_code == 404:
        record("SCENARIO 6", True, "Non-existent job returns 404")
    else:
        record("SCENARIO 6", False, "Non-existent job NOT returning 404", response=resp.status_code if resp else "Err")

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Starting full E2E load test...")
    
    # 0. Health check
    h_resp = api_call("GET", "/api/health")
    if not h_resp or h_resp.status_code != 200:
        print("CRITICAL: Server is not running or not healthy at localhost:5000. Please start it first.")
        sys.exit(1)
    
    # Setup - use a known shop or bootstrap one
    # We'll use a bootstrap logic for scenario 1 to have something to work with
    try:
        from shared.database import SessionLocal, Shopkeeper
        db = SessionLocal()
        s = db.query(Shopkeeper).first()
        if not s:
            print("No shops found. Boostrapping test shop...")
            s = Shopkeeper(username="testadmin", email="admin@test.com", password_hash="hash", shop_name="Test Shop", shop_id="TEST_SHOP_UUID")
            db.add(s)
            db.commit()
        shop_id = s.shop_id
        db.close()
    except:
        shop_id = "TEST_SHOP_UUID" # Hopefully it exists

    # To test Scenario 3, we need a token
    # We'll try to login with a known test user
    login_resp = api_call("POST", "/api/auth/login", json={"username": "testadmin", "password": "password123"})
    token = login_resp.json().get("data", {}).get("session_token") if login_resp and login_resp.status_code == 200 else "MOCK_TOKEN"

    run_scenario_1(shop_id)
    run_scenario_2()
    run_scenario_3(shop_id, token)
    run_scenario_4(shop_id, token)
    run_scenario_5(shop_id, token)
    run_scenario_6(shop_id)

    # ── Final Report ──────────────────────────────────────────────────────────
    print("\n" + "="*50)
    print("FINAL REPORT")
    print("="*50)
    total_scenarios = len(results)
    total_passed = 0
    total_failed = 0
    total_crashes = 0
    warnings = 0

    for s_name, data in results.items():
        print(f"\n{s_name}:")
        for p in data["pass"]:
            print(f"  [PASS] {p['label']}")
            total_passed += 1
        for f in data["fail"]:
            print(f"  [FAIL] {f['label']}")
            if f['endpoint']: print(f"         Endpoint: {f['endpoint']}")
            if f['detail']: print(f"         Detail: {f['detail']}")
            if f['response']: print(f"         Response: {f['response'][:200]}")
            if f['fix']: print(f"         Suggested Fix: {f['fix']}")
            total_failed += 1
            if "500" in str(f['response']): total_crashes += 1
            if "missing" in f['label'].lower(): warnings += 1

    print("\n" + "="*25)
    print(f"Total Scenarios: {total_scenarios}")
    print(f"Passed: {total_passed}")
    print(f"Failed: {total_failed}")
    print(f"Crashes detected: {total_crashes}")
    print(f"Warnings: {warnings}")
    print("="*25)

    # Cleanup
    print("\nCleaning up test data...")
    try:
        from shared.database import SessionLocal, Shopkeeper, PrintJob
        db = SessionLocal()
        db.query(PrintJob).filter(PrintJob.job_id.in_(created_job_ids)).delete(synchronize_session=False)
        db.query(Shopkeeper).filter(Shopkeeper.username.in_(created_shopkeepers)).delete(synchronize_session=False)
        db.commit()
        db.close()
    except:
        pass

if __name__ == "__main__":
    main()
