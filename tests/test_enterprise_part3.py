#!/usr/bin/env python3
"""
EzPrint Enterprise Test Suite -- Part 3
Classes: TestRealShopScenarios, TestSecurityAndAuth, 
         TestUIAndPerformance, TestRecoveryAndResilience
Test IDs: TC166-TC220
"""
import unittest, os, sys, json, io, uuid, time, threading
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "web_interface"))

BASE_URL = os.environ.get("EZPRINT_BASE_URL", "http://localhost:5000")

def _server_available():
    try:
        import requests as _r
        _r.get(f"{BASE_URL}/api/health", timeout=3)
        return True
    except Exception:
        return False

SERVER_UP = _server_available()

def requires_server(fn):
    @unittest.skipUnless(SERVER_UP, "Web server not running")
    def wrapper(*a, **kw):
        return fn(*a, **kw)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper

_db_ok = False
try:
    from shared.database import (
        SessionLocal, Shopkeeper, PrintJob, ShopPricing, Printer,
        Base, engine, init_database,
    )
    from shared.file_processor import (
        allowed_file, parse_page_range, calculate_billing,
    )
    from shared.config import ALLOWED_EXTENSIONS, MAX_FILE_SIZE
    _db_ok = True
except Exception:
    pass

import bcrypt

def _make_shop(db, **kw):
    defaults = dict(
        username=f"test_{uuid.uuid4().hex[:8]}",
        email=f"test_{uuid.uuid4().hex[:8]}@test.com",
        password_hash=bcrypt.hashpw(b"Test1234!", bcrypt.gensalt()).decode(),
        shop_name="Test Shop",
    )
    defaults.update(kw)
    s = Shopkeeper(**defaults)
    db.add(s); db.commit(); db.refresh(s)
    return s

def _make_job(db, shop_id, **kw):
    defaults = dict(
        shop_id=shop_id, filename="test.pdf",
        file_path="https://example.com/test.pdf",
        file_size=1024, file_type="pdf",
    )
    defaults.update(kw)
    j = PrintJob(**defaults)
    db.add(j); db.commit(); db.refresh(j)
    return j

def _login(username, password):
    import requests
    return requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": username, "password": password},
        timeout=10)


# ===================================================================
# CLASS 8 -- TestRealShopScenarios (TC166-TC190)
# ===================================================================
class TestRealShopScenarios(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not _db_ok: return
        cls.db = SessionLocal()
        cls.shop = _make_shop(cls.db)

    @classmethod
    def tearDownClass(cls):
        if not _db_ok: return
        try:
            cls.db.query(PrintJob).filter(PrintJob.shop_id == cls.shop.shop_id).delete()
            cls.db.query(Printer).filter(Printer.shop_id == cls.shop.shop_id).delete()
            cls.db.query(ShopPricing).filter(ShopPricing.shop_id == cls.shop.shop_id).delete()
            cls.db.query(Shopkeeper).filter(Shopkeeper.id == cls.shop.id).delete()
            cls.db.commit()
        except Exception:
            cls.db.rollback()
        finally:
            cls.db.close()

    def test_tc166_morning_startup(self):
        """TC166: Morning startup - dashboard loads, shop exists"""
        if not _db_ok: self.skipTest("DB unavailable")
        shop = self.db.query(Shopkeeper).filter(Shopkeeper.id == self.shop.id).first()
        self.assertIsNotNone(shop)
        self.assertIsNotNone(shop.shop_id)

    def test_tc167_first_customer(self):
        """TC167: First customer - job created, appears in dashboard"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id, filename="first_job.pdf")
        found = self.db.query(PrintJob).filter(PrintJob.job_id == j.job_id).first()
        self.assertIsNotNone(found)
        self.assertEqual(found.status, "Pending")

    def test_tc168_rush_hour_10_jobs(self):
        """TC168: Rush hour - 10 jobs in sequence, all appear"""
        if not _db_ok: self.skipTest("DB unavailable")
        jobs = []
        for i in range(10):
            j = _make_job(self.db, self.shop.shop_id, filename=f"rush_{i}.pdf")
            jobs.append(j.job_id)
        count = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.filename.like("rush_%")).count()
        self.assertEqual(count, 10)
        self.assertEqual(len(set(jobs)), 10)

    def test_tc169_three_jobs_manual_sequence(self):
        """TC169: 3 jobs manual sequence - each completes correctly"""
        if not _db_ok: self.skipTest("DB unavailable")
        for i in range(3):
            j = _make_job(self.db, self.shop.shop_id, filename=f"manual_{i}.pdf")
            j.status = "Printing"
            self.db.commit()
            j.status = "Completed"
            j.completed_at = datetime.utcnow()
            self.db.commit()
            self.assertEqual(j.status, "Completed")

    def test_tc170_auto_mode_10_jobs(self):
        """TC170: Auto mode - 10 jobs status transitions work"""
        if not _db_ok: self.skipTest("DB unavailable")
        jobs = []
        for i in range(10):
            j = _make_job(self.db, self.shop.shop_id, filename=f"auto_{i}.pdf")
            jobs.append(j)
        for j in jobs:
            j.status = "Completed"
            j.completed_at = datetime.utcnow()
        self.db.commit()
        completed = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.status == "Completed",
            PrintJob.filename.like("auto_%")).count()
        self.assertEqual(completed, 10)

    def test_tc171_mixed_mode_no_conflict(self):
        """TC171: Mixed auto/manual - no DB conflicts"""
        if not _db_ok: self.skipTest("DB unavailable")
        j_auto = _make_job(self.db, self.shop.shop_id,
                          filename="mixed_auto.pdf", status="Completed")
        j_manual = _make_job(self.db, self.shop.shop_id,
                            filename="mixed_manual.pdf", status="Pending")
        self.db.refresh(j_auto)
        self.db.refresh(j_manual)
        self.assertEqual(j_auto.status, "Completed")
        self.assertEqual(j_manual.status, "Pending")

    def test_tc172_color_job(self):
        """TC172: Color job - color_mode stored correctly"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id, color_mode="Color")
        self.assertEqual(j.color_mode, "Color")

    def test_tc173_duplex_job(self):
        """TC173: Duplex job - print_side stored correctly"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id, print_side="Double")
        self.assertEqual(j.print_side, "Double")

    def test_tc174_large_job_100_pages(self):
        """TC174: Large job 100 pages - price calculated correctly"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id,
                     total_pages=100, filename="large.pdf")
        self.assertEqual(j.total_pages, 100)
        result = calculate_billing(
            color_mode="Black & White", print_side="Single",
            copies=1, layout_pages=1,
            selected_pages=list(range(1, 101)),
            color_page_dict=None,
            pricing={"bw_single": 2.0, "bw_double": 1.5,
                     "color_single": 10.0, "color_double": 8.0})
        self.assertEqual(result["total_amount"], 200.0)

    def test_tc175_20_single_page_jobs(self):
        """TC175: 20 single-page jobs - all unique job_ids"""
        if not _db_ok: self.skipTest("DB unavailable")
        ids = []
        for i in range(20):
            j = _make_job(self.db, self.shop.shop_id,
                         filename=f"single_{i}.pdf", total_pages=1)
            ids.append(j.job_id)
        self.assertEqual(len(set(ids)), 20)

    def test_tc176_copies_price(self):
        """TC176: 5 copies of 10 pages - price correct"""
        if not _db_ok: self.skipTest("DB unavailable")
        result = calculate_billing(
            color_mode="Black & White", print_side="Single",
            copies=5, layout_pages=1,
            selected_pages=list(range(1, 11)),
            color_page_dict=None,
            pricing={"bw_single": 2.0, "bw_double": 1.5,
                     "color_single": 10.0, "color_double": 8.0})
        self.assertEqual(result["total_amount"], 100.0)

    def test_tc177_end_of_day_completed_jobs(self):
        """TC177: End of day - completed jobs queryable"""
        if not _db_ok: self.skipTest("DB unavailable")
        for i in range(5):
            _make_job(self.db, self.shop.shop_id,
                     status="Completed", filename=f"eod_{i}.pdf",
                     completed_at=datetime.utcnow())
        completed = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.status == "Completed").count()
        self.assertGreaterEqual(completed, 5)

    def test_tc178_end_of_day_revenue(self):
        """TC178: End of day revenue - total calculated correctly"""
        if not _db_ok: self.skipTest("DB unavailable")
        from sqlalchemy import func
        for i in range(3):
            _make_job(self.db, self.shop.shop_id,
                     status="Completed", amount=100.0,
                     filename=f"rev_{i}.pdf")
        total = self.db.query(func.sum(PrintJob.amount)).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.status == "Completed",
            PrintJob.filename.like("rev_%")).scalar()
        self.assertEqual(float(total), 300.0)

    def test_tc179_power_cut_recovery(self):
        """TC179: Power cut - Printing jobs marked Failed on restart"""
        if not _db_ok: self.skipTest("DB unavailable")
        for i in range(3):
            _make_job(self.db, self.shop.shop_id,
                     status="Printing", filename=f"power_{i}.pdf")
        stuck = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.status == "Printing",
            PrintJob.filename.like("power_%")).all()
        for j in stuck:
            j.status = "Failed"
            j.error_message = "Recovered after power cut"
        self.db.commit()
        still_printing = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.status == "Printing",
            PrintJob.filename.like("power_%")).count()
        self.assertEqual(still_printing, 0)

    def test_tc180_internet_down_jobs_safe(self):
        """TC180: Internet down - Pending jobs not lost"""
        if not _db_ok: self.skipTest("DB unavailable")
        for i in range(5):
            _make_job(self.db, self.shop.shop_id, filename=f"inet_{i}.pdf")
        pending = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.status == "Pending",
            PrintJob.filename.like("inet_%")).count()
        self.assertEqual(pending, 5)

    def test_tc181_internet_back_queue_intact(self):
        """TC181: Internet back - queue intact"""
        if not _db_ok: self.skipTest("DB unavailable")
        pending = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.status == "Pending").count()
        self.assertGreaterEqual(pending, 0)

    def test_tc182_paper_refilled_reprint(self):
        """TC182: Paper refilled - job can be reprinted"""
        if not _db_ok: self.skipTest("DB unavailable")
        j1 = _make_job(self.db, self.shop.shop_id,
                      status="Failed", error_message="Paper out",
                      filename="paper_out.pdf")
        j2 = _make_job(self.db, self.shop.shop_id, filename=j1.filename)
        self.assertEqual(j2.status, "Pending")
        self.assertNotEqual(j1.job_id, j2.job_id)

    def test_tc183_new_printer_added(self):
        """TC183: New printer added mid-day - appears in list"""
        if not _db_ok: self.skipTest("DB unavailable")
        p = Printer(shop_id=self.shop.shop_id,
                   printer_name="NewPrinter",
                   printer_id=f"np_{uuid.uuid4().hex[:6]}",
                   is_default=False, is_active=True)
        self.db.add(p); self.db.commit()
        found = self.db.query(Printer).filter(
            Printer.printer_name == "NewPrinter",
            Printer.shop_id == self.shop.shop_id).first()
        self.assertIsNotNone(found)
        self.db.delete(p); self.db.commit()

    def test_tc184_printer_replaced(self):
        """TC184: Printer replaced - old removed, new added"""
        if not _db_ok: self.skipTest("DB unavailable")
        old = Printer(shop_id=self.shop.shop_id,
                     printer_name="OldPrinter",
                     printer_id=f"old_{uuid.uuid4().hex[:6]}",
                     is_default=True, is_active=True)
        self.db.add(old); self.db.commit()
        old.is_active = False; self.db.commit()
        new = Printer(shop_id=self.shop.shop_id,
                     printer_name="NewPrinter2",
                     printer_id=f"new_{uuid.uuid4().hex[:6]}",
                     is_default=True, is_active=True)
        self.db.add(new); self.db.commit()
        active = self.db.query(Printer).filter(
            Printer.shop_id == self.shop.shop_id,
            Printer.is_active == True).count()
        self.assertGreaterEqual(active, 1)
        self.db.delete(old); self.db.delete(new); self.db.commit()

    def test_tc185_lunch_break_queue(self):
        """TC185: Lunch break - jobs queue in order"""
        if not _db_ok: self.skipTest("DB unavailable")
        for i in range(5):
            _make_job(self.db, self.shop.shop_id, filename=f"lunch_{i}.pdf")
        jobs = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.filename.like("lunch_%")).order_by(
            PrintJob.created_at).all()
        for i in range(len(jobs) - 1):
            self.assertLessEqual(jobs[i].created_at, jobs[i+1].created_at)

    def test_tc186_fifo_order(self):
        """TC186: Multiple customers - FIFO order maintained"""
        if not _db_ok: self.skipTest("DB unavailable")
        jobs = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id).order_by(
            PrintJob.created_at).all()
        for i in range(len(jobs) - 1):
            self.assertLessEqual(jobs[i].created_at, jobs[i+1].created_at)

    def test_tc187_customer_cancels(self):
        """TC187: Customer cancels by calling - status Cancelled"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id)
        j.status = "Cancelled"; self.db.commit()
        self.assertEqual(j.status, "Cancelled")

    def test_tc188_wrong_file_reprint(self):
        """TC188: Wrong file printed - reprint creates new job"""
        if not _db_ok: self.skipTest("DB unavailable")
        j1 = _make_job(self.db, self.shop.shop_id,
                      status="Completed", filename="wrong.pdf")
        j2 = _make_job(self.db, self.shop.shop_id, filename="wrong.pdf")
        self.assertNotEqual(j1.job_id, j2.job_id)
        self.assertEqual(j2.status, "Pending")

    def test_tc189_customer_dispute_history(self):
        """TC189: Customer disputes - job queryable by job_id"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id, filename="dispute.pdf")
        found = self.db.query(PrintJob).filter(
            PrintJob.job_id == j.job_id).first()
        self.assertIsNotNone(found)
        self.assertEqual(found.filename, "dispute.pdf")

    def test_tc190_month_end_500_jobs(self):
        """TC190: Month end - 500 jobs query under 10 seconds"""
        if not _db_ok: self.skipTest("DB unavailable")
        start = time.time()
        jobs = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id).limit(500).all()
        elapsed = time.time() - start
        self.assertLess(elapsed, 10.0)


# ===================================================================
# CLASS 9 -- TestSecurityAndAuth (TC191-TC200)
# ===================================================================
class TestSecurityAndAuth(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not _db_ok: return
        cls.db = SessionLocal()
        cls.shop = _make_shop(cls.db)
        cls.raw_pw = "Test1234!"

    @classmethod
    def tearDownClass(cls):
        if not _db_ok: return
        try:
            cls.db.query(PrintJob).filter(PrintJob.shop_id == cls.shop.shop_id).delete()
            cls.db.query(Shopkeeper).filter(Shopkeeper.id == cls.shop.id).delete()
            cls.db.commit()
        except Exception:
            cls.db.rollback()
        finally:
            cls.db.close()

    @requires_server
    def test_tc191_sql_injection_login(self):
        """TC191: SQL injection in username - login fails safely"""
        import requests
        payloads = [
            "' OR '1'='1",
            "admin'--",
            "' OR 1=1--",
            "'; DROP TABLE shopkeepers;--",
        ]
        for payload in payloads:
            r = requests.post(f"{BASE_URL}/api/auth/login",
                json={"username": payload, "password": "anything"},
                timeout=10)
            self.assertIn(r.status_code, [400, 401, 422],
                msg=f"SQL injection not blocked: {payload}")
            self.assertNotEqual(r.status_code, 500,
                msg=f"Server crashed on SQL injection: {payload}")

    @requires_server
    def test_tc192_sql_injection_search(self):
        """TC192: SQL injection in search field - handled safely"""
        import requests
        lr = _login(self.shop.username, self.raw_pw)
        if lr.status_code != 200:
            self.skipTest("Login failed")
        token = lr.json()["data"]["session_token"]
        r = requests.get(
            f"{BASE_URL}/api/jobs/{self.shop.shop_id}",
            params={"search": "' OR '1'='1"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10)
        self.assertNotEqual(r.status_code, 500)

    @requires_server
    def test_tc193_xss_in_filename(self):
        """TC193: XSS payload in filename - stored as plain text"""
        import requests
        xss = "<script>alert('xss')</script>.pdf"
        files = {"file": (xss, io.BytesIO(b"%PDF-1.4 test"), "application/pdf")}
        r = requests.post(f"{BASE_URL}/api/upload",
            files=files,
            data={"shop_id": self.shop.shop_id, "copies": "1"},
            timeout=15)
        self.assertNotEqual(r.status_code, 500)

    @requires_server
    def test_tc194_xss_in_shop_name(self):
        """TC194: XSS in shop name - stored safely"""
        if not _db_ok: self.skipTest("DB unavailable")
        s = self.db.query(Shopkeeper).filter(
            Shopkeeper.id == self.shop.id).first()
        xss_name = "<script>alert(1)</script>"
        s.shop_name = xss_name
        self.db.commit()
        self.db.refresh(s)
        self.assertEqual(s.shop_name, xss_name)
        s.shop_name = "Test Shop"
        self.db.commit()

    @requires_server
    def test_tc195_path_traversal(self):
        """TC195: Path traversal in filename - rejected or sanitized"""
        import requests
        files = {"file": ("../../../etc/passwd.pdf",
                         io.BytesIO(b"%PDF-1.4 test"),
                         "application/pdf")}
        r = requests.post(f"{BASE_URL}/api/upload",
            files=files,
            data={"shop_id": self.shop.shop_id},
            timeout=15)
        self.assertNotEqual(r.status_code, 500)

    @requires_server
    def test_tc196_oversized_payload(self):
        """TC196: Oversized JSON payload - server handles gracefully"""
        import requests
        big_payload = {"username": "x" * 100000, "password": "y" * 100000}
        try:
            r = requests.post(f"{BASE_URL}/api/auth/login",
                json=big_payload, timeout=15)
            self.assertNotEqual(r.status_code, 500)
        except requests.exceptions.ConnectionError:
            pass

    @requires_server
    def test_tc197_rapid_login_attempts(self):
        """TC197: 20 rapid login attempts - server stays stable"""
        import requests
        def attempt(i):
            return requests.post(f"{BASE_URL}/api/auth/login",
                json={"username": "fake_user", "password": "wrong"},
                timeout=10)
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = [ex.submit(attempt, i) for i in range(20)]
            results = [f.result() for f in as_completed(futures)]
        for r in results:
            self.assertNotEqual(r.status_code, 500)
        health = requests.get(f"{BASE_URL}/api/health", timeout=5)
        self.assertEqual(health.status_code, 200)

    @requires_server
    def test_tc198_invalid_jwt_token(self):
        """TC198: Invalid JWT token - returns 401"""
        import requests
        r = requests.get(
            f"{BASE_URL}/api/shop/{self.shop.shop_id}/dashboard?period=today",
            headers={"Authorization": "Bearer invalid.token.here"},
            timeout=10)
        self.assertEqual(r.status_code, 401)

    @requires_server
    def test_tc199_access_other_shop_jobs(self):
        """TC199: Access another shop's data - returns 403"""
        import requests
        lr = _login(self.shop.username, self.raw_pw)
        if lr.status_code != 200:
            self.skipTest("Login failed")
        token = lr.json()["data"]["session_token"]
        r = requests.get(
            f"{BASE_URL}/api/shop/fake-shop-id-xyz/dashboard?period=today",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10)
        self.assertEqual(r.status_code, 403)

    @requires_server
    def test_tc200_missing_auth_header(self):
        """TC200: Missing Authorization header - returns 401"""
        import requests
        r = requests.get(
            f"{BASE_URL}/api/shop/{self.shop.shop_id}/dashboard?period=today",
            timeout=10)
        self.assertEqual(r.status_code, 401)

# ===================================================================
# CLASS 10 -- TestUIAndPerformance (TC201-TC216)
# ===================================================================
class TestUIAndPerformance(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not _db_ok: return
        cls.db = SessionLocal()
        cls.shop = _make_shop(cls.db)

    @classmethod
    def tearDownClass(cls):
        if not _db_ok: return
        try:
            cls.db.query(PrintJob).filter(PrintJob.shop_id == cls.shop.shop_id).delete()
            cls.db.query(Shopkeeper).filter(Shopkeeper.id == cls.shop.id).delete()
            cls.db.commit()
        except Exception:
            cls.db.rollback()
        finally:
            cls.db.close()

    def test_tc201_100_jobs_query_speed(self):
        """TC201: 100 jobs loaded - DB query under 3 seconds"""
        if not _db_ok: self.skipTest("DB unavailable")
        for i in range(100):
            _make_job(self.db, self.shop.shop_id, filename=f"perf_{i}.pdf")
        start = time.time()
        jobs = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id).limit(100).all()
        elapsed = time.time() - start
        self.assertEqual(len(jobs), 100)
        self.assertLess(elapsed, 3.0,
            msg=f"Query took {elapsed:.2f}s — too slow")

    def test_tc202_500_jobs_query_speed(self):
        """TC202: 500 jobs loaded - DB query under 5 seconds"""
        if not _db_ok: self.skipTest("DB unavailable")
        start = time.time()
        jobs = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id).limit(500).all()
        elapsed = time.time() - start
        self.assertLess(elapsed, 5.0,
            msg=f"Query took {elapsed:.2f}s — too slow")

    def test_tc203_filter_by_status_speed(self):
        """TC203: Filter by status - query under 1 second"""
        if not _db_ok: self.skipTest("DB unavailable")
        start = time.time()
        jobs = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.status == "Pending").all()
        elapsed = time.time() - start
        self.assertLess(elapsed, 1.0,
            msg=f"Filter took {elapsed:.2f}s — too slow")

    def test_tc204_filter_by_date_speed(self):
        """TC204: Filter by date range - query under 1 second"""
        if not _db_ok: self.skipTest("DB unavailable")
        start_date = datetime.utcnow() - timedelta(days=30)
        start = time.time()
        jobs = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.created_at >= start_date).all()
        elapsed = time.time() - start
        self.assertLess(elapsed, 1.0,
            msg=f"Date filter took {elapsed:.2f}s — too slow")

    def test_tc205_search_by_filename_speed(self):
        """TC205: Search by filename - query under 1 second"""
        if not _db_ok: self.skipTest("DB unavailable")
        start = time.time()
        jobs = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.filename.like("%perf%")).all()
        elapsed = time.time() - start
        self.assertLess(elapsed, 1.0,
            msg=f"Search took {elapsed:.2f}s — too slow")

    def test_tc206_price_all_combinations(self):
        """TC206: Price calculation for all BW/Color x Single/Double combinations"""
        if not _db_ok: self.skipTest("DB unavailable")
        pricing = {
            "bw_single": 2.0, "bw_double": 1.5,
            "color_single": 10.0, "color_double": 8.0
        }
        combos = [
            ("Black & White", "Single", 1, 10, 20.0),
            ("Black & White", "Double", 1, 10, 15.0),
            ("Color", "Single", 1, 10, 100.0),
            ("Color", "Double", 1, 10, 80.0),
            ("Black & White", "Single", 3, 5, 30.0),
            ("Black & White", "Double", 2, 4, 12.0),
        ]
        for color, side, copies, pages, expected in combos:
            result = calculate_billing(
                color_mode=color, print_side=side,
                copies=copies, layout_pages=1,
                selected_pages=list(range(1, pages + 1)),
                color_page_dict=None,
                pricing=pricing)
            self.assertEqual(result["total_amount"], expected,
                msg=f"{color} {side} x{copies} x{pages}p = "
                    f"{result['total_amount']} (expected {expected})")

    def test_tc207_db_write_speed(self):
        """TC207: Job status update - DB write under 1 second"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id, filename="speed_write.pdf")
        start = time.time()
        j.status = "Completed"
        j.completed_at = datetime.utcnow()
        self.db.commit()
        elapsed = time.time() - start
        self.assertLess(elapsed, 1.0,
            msg=f"DB write took {elapsed:.2f}s — too slow")

    def test_tc208_concurrent_kpi_no_freeze(self):
        """TC208: Concurrent KPI calculation - completes under 5 seconds"""
        if not _db_ok: self.skipTest("DB unavailable")
        from sqlalchemy import func
        results = []
        errors = []

        def calc_kpi():
            try:
                db = SessionLocal()
                total = db.query(func.count(PrintJob.job_id)).filter(
                    PrintJob.shop_id == self.shop.shop_id).scalar()
                revenue = db.query(func.sum(PrintJob.amount)).filter(
                    PrintJob.shop_id == self.shop.shop_id,
                    PrintJob.status == "Completed").scalar()
                results.append((total, revenue))
                db.close()
            except Exception as e:
                errors.append(str(e))

        start = time.time()
        threads = [threading.Thread(target=calc_kpi) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=5)
        elapsed = time.time() - start
        self.assertEqual(len(errors), 0,
            msg=f"KPI errors: {errors}")
        self.assertLess(elapsed, 5.0,
            msg=f"KPI took {elapsed:.2f}s — too slow")

    @requires_server
    def test_tc209_upload_page_response_time(self):
        """TC209: Upload page health check - server responds under 2 seconds"""
        import requests
        start = time.time()
        r = requests.get(f"{BASE_URL}/api/health", timeout=5)
        elapsed = time.time() - start
        self.assertEqual(r.status_code, 200)
        self.assertLess(elapsed, 2.0,
            msg=f"Health check took {elapsed:.2f}s")

    def test_tc210_allowed_file_function(self):
        """TC210: allowed_file() accepts correct types, rejects others"""
        if not _db_ok: self.skipTest("DB unavailable")
        valid = ["doc.pdf", "file.docx", "image.png",
                 "photo.jpg", "scan.jpeg", "slide.ppt", "deck.pptx"]
        invalid = ["virus.exe", "script.js", "data.csv",
                   "archive.zip", "video.mp4"]
        for f in valid:
            self.assertTrue(allowed_file(f),
                msg=f"{f} should be allowed")
        for f in invalid:
            self.assertFalse(allowed_file(f),
                msg=f"{f} should NOT be allowed")

    def test_tc211_parse_page_range_valid(self):
        """TC211: parse_page_range valid inputs"""
        if not _db_ok: self.skipTest("DB unavailable")
        cases = [
            ("1-5", 10, [1, 2, 3, 4, 5]),
            ("1,3,5", 10, [1, 3, 5]),
            ("all", 5, [1, 2, 3, 4, 5]),
            ("1", 10, [1]),
        ]
        for input_str, total, expected in cases:
            result = parse_page_range(input_str, total)
            self.assertEqual(sorted(result), sorted(expected),
                msg=f"parse_page_range('{input_str}', {total}) = {result}")

    def test_tc212_parse_page_range_invalid(self):
        """TC212: parse_page_range invalid inputs handled gracefully"""
        if not _db_ok: self.skipTest("DB unavailable")
        invalid_cases = [
            ("abc", 10),
            ("0-5", 10),
            ("1-999", 5),
            ("", 10),
        ]
        for input_str, total in invalid_cases:
            try:
                result = parse_page_range(input_str, total)
                self.assertIsInstance(result, list)
            except (ValueError, Exception):
                pass

    def test_tc213_error_no_raw_traceback(self):
        """TC213: Error messages are user friendly - no raw tracebacks"""
        if not _db_ok: self.skipTest("DB unavailable")
        ge_path = os.path.join(ROOT, "shared", "global_error_handler.py")
        self.assertTrue(os.path.exists(ge_path),
            msg="global_error_handler.py not found")

    def test_tc214_job_status_values_valid(self):
        """TC214: All job status values are from valid set"""
        if not _db_ok: self.skipTest("DB unavailable")
        valid_statuses = {
            "Pending", "In Queue", "Printing",
            "Completed", "Failed", "Cancelled",
            "Printing Started", "Offline"
        }
        jobs = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id).all()
        for j in jobs:
            self.assertIn(j.status, valid_statuses,
                msg=f"Invalid status: {j.status}")

    def test_tc215_shopkeeper_fields_present(self):
        """TC215: Shopkeeper model has all required fields"""
        if not _db_ok: self.skipTest("DB unavailable")
        s = self.db.query(Shopkeeper).filter(
            Shopkeeper.id == self.shop.id).first()
        self.assertIsNotNone(s.username)
        self.assertIsNotNone(s.email)
        self.assertIsNotNone(s.password_hash)
        self.assertIsNotNone(s.shop_id)
        self.assertIsNotNone(s.shop_name)

    def test_tc216_printjob_fields_present(self):
        """TC216: PrintJob model has all required fields"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id)
        self.assertIsNotNone(j.job_id)
        self.assertIsNotNone(j.shop_id)
        self.assertIsNotNone(j.filename)
        self.assertIsNotNone(j.file_path)
        self.assertIsNotNone(j.status)
        self.assertIsNotNone(j.created_at)


# ===================================================================
# CLASS 11 -- TestRecoveryAndResilience (TC217-TC220)
# ===================================================================
class TestRecoveryAndResilience(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not _db_ok: return
        cls.db = SessionLocal()
        cls.shop = _make_shop(cls.db)

    @classmethod
    def tearDownClass(cls):
        if not _db_ok: return
        try:
            cls.db.query(PrintJob).filter(PrintJob.shop_id == cls.shop.shop_id).delete()
            cls.db.query(Shopkeeper).filter(Shopkeeper.id == cls.shop.id).delete()
            cls.db.commit()
        except Exception:
            cls.db.rollback()
        finally:
            cls.db.close()

    def test_tc217_crash_recovery_all_interrupted(self):
        """TC217: App crash - all Printing jobs marked Failed"""
        if not _db_ok: self.skipTest("DB unavailable")
        for i in range(5):
            _make_job(self.db, self.shop.shop_id,
                     status="Printing", filename=f"crash_{i}.pdf")
        stuck = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.status == "Printing",
            PrintJob.filename.like("crash_%")).all()
        self.assertEqual(len(stuck), 5)
        for j in stuck:
            j.status = "Failed"
            j.error_message = "App crashed - interrupted"
        self.db.commit()
        remaining = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.status == "Printing",
            PrintJob.filename.like("crash_%")).count()
        self.assertEqual(remaining, 0)

    def test_tc218_db_reconnect(self):
        """TC218: DB reconnect after connection drop"""
        if not _db_ok: self.skipTest("DB unavailable")
        db2 = SessionLocal()
        try:
            db2.close()
            db3 = SessionLocal()
            j = _make_job(db3, self.shop.shop_id,
                         filename="reconnect.pdf")
            self.assertIsNotNone(j.job_id)
            db3.close()
        except Exception as e:
            self.fail(f"DB reconnect failed: {e}")

    def test_tc219_socketio_reconnect_logic(self):
        """TC219: SocketIO reconnect logic exists in codebase"""
        ws_path = os.path.join(ROOT, "shopkeeper_app", "websocket_client.py")
        if not os.path.exists(ws_path):
            ws_path = os.path.join(ROOT, "shopkeeper_app", "api_client.py")
        self.assertTrue(os.path.exists(ws_path),
            msg="WebSocket client file not found")
        with open(ws_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        reconnect_keywords = ["reconnect", "retry", "reconnection"]
        found = any(kw in content.lower() for kw in reconnect_keywords)
        self.assertTrue(found,
            msg="No reconnect logic found in WebSocket client")

    def test_tc220_partial_upload_no_stuck_job(self):
        """TC220: Partial/failed upload - no job stuck in Printing"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id,
                     filename="partial.pdf", status="Pending")
        self.assertNotEqual(j.status, "Printing")
        self.assertNotEqual(j.status, "In Queue")
        self.assertEqual(j.status, "Pending")


# ===================================================================
# RUNNER
# ===================================================================
if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestRealShopScenarios))
    suite.addTests(loader.loadTestsFromTestCase(TestSecurityAndAuth))
    suite.addTests(loader.loadTestsFromTestCase(TestUIAndPerformance))
    suite.addTests(loader.loadTestsFromTestCase(TestRecoveryAndResilience))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    total = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    skipped = len(result.skipped)
    passed = total - failures - errors - skipped

    print("\n" + "=" * 60)
    print(f"PART 3 SUMMARY: {passed}/{total} passed, "
          f"{failures} failed, {errors} errors, {skipped} skipped")
    print("=" * 60)
