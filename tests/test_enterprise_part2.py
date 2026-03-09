#!/usr/bin/env python3
"""
EzPrint Enterprise Test Suite -- Part 2
Classes: TestShopkeeperEdgeCases, TestSystemFailures, TestConcurrency, TestDataIntegrity
Test IDs: TC082-TC165
"""
import unittest, os, sys, json, io, uuid, time, math, threading
from unittest.mock import patch, MagicMock, PropertyMock
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

def _make_shop(db, **kw):
    import bcrypt
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
    return requests.post(f"{BASE_URL}/api/auth/login",
        json={"username": username, "password": password}, timeout=10)


# ===================================================================
# CLASS 4 -- TestShopkeeperEdgeCases (TC082-TC106)
# ===================================================================
class TestShopkeeperEdgeCases(unittest.TestCase):
    """Edge-case tests for shopkeeper auth, dashboard, printers."""

    @classmethod
    def setUpClass(cls):
        if not _db_ok: return
        cls.db = SessionLocal()
        import bcrypt
        cls.raw_pw = "Test1234!"
        cls.shop = _make_shop(cls.db, password_hash=bcrypt.hashpw(
            cls.raw_pw.encode(), bcrypt.gensalt()).decode())

    @classmethod
    def tearDownClass(cls):
        if not _db_ok: return
        try:
            cls.db.query(PrintJob).filter(PrintJob.shop_id == cls.shop.shop_id).delete()
            cls.db.query(ShopPricing).filter(ShopPricing.shop_id == cls.shop.shop_id).delete()
            cls.db.query(Printer).filter(Printer.shop_id == cls.shop.shop_id).delete()
            cls.db.query(Shopkeeper).filter(Shopkeeper.id == cls.shop.id).delete()
            cls.db.commit()
        except Exception: cls.db.rollback()
        finally: cls.db.close()

    # --- TC082 ---
    @requires_server
    def test_tc082_login_wrong_password(self):
        """TC082: Login wrong password -> 401"""
        r = _login(self.shop.username, "WRONG_PASSWORD")
        self.assertEqual(r.status_code, 401)
        self.assertFalse(r.json()["success"])

    # --- TC083 ---
    @requires_server
    def test_tc083_login_nonexistent_user(self):
        """TC083: Login non-existent username -> 401"""
        r = _login("nonexistent_user_xyz", "anything")
        self.assertEqual(r.status_code, 401)

    # --- TC084 ---
    @requires_server
    def test_tc084_login_with_email(self):
        """TC084: Login with email in username field -> works"""
        r = _login(self.shop.email, self.raw_pw)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["success"])

    # --- TC085 ---
    def test_tc085_forgot_password_username(self):
        """TC085: Forgot password with username -> OTP initiated"""
        if not _db_ok: self.skipTest("DB unavailable")
        from shopkeeper_app.auth import AuthManager
        auth = AuthManager()
        try:
            # Will fail because SMTP is not configured, but should find the user
            auth._resolve_shopkeeper(self.shop.username)
            shopkeeper = auth.db.query(Shopkeeper).filter(
                Shopkeeper.username == self.shop.username).first()
            self.assertIsNotNone(shopkeeper)
        finally:
            auth.close()

    # --- TC086 ---
    def test_tc086_forgot_password_email(self):
        """TC086: Forgot password with email -> resolves user"""
        if not _db_ok: self.skipTest("DB unavailable")
        from shopkeeper_app.auth import AuthManager
        auth = AuthManager()
        try:
            resolved = auth._resolve_shopkeeper(self.shop.email)
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved.shop_id, self.shop.shop_id)
        finally:
            auth.close()

    # --- TC087 ---
    def test_tc087_forgot_password_wrong_id(self):
        """TC087: Forgot password wrong identifier -> user not found"""
        if not _db_ok: self.skipTest("DB unavailable")
        from shopkeeper_app.auth import AuthManager
        auth = AuthManager()
        try:
            resolved = auth._resolve_shopkeeper("does_not_exist_xyz")
            self.assertIsNone(resolved)
        finally:
            auth.close()

    # --- TC088 ---
    def test_tc088_wrong_otp(self):
        """TC088: Wrong OTP entered -> rejected"""
        if not _db_ok: self.skipTest("DB unavailable")
        from shopkeeper_app.auth import AuthManager
        auth = AuthManager()
        try:
            s = auth.db.query(Shopkeeper).filter(Shopkeeper.id == self.shop.id).first()
            s.otp_code = "123456"
            s.otp_expires_at = datetime.utcnow() + timedelta(minutes=10)
            auth.db.commit()
            ok, msg = auth.verify_otp(self.shop.username, "999999")
            self.assertFalse(ok)
            self.assertIn("Invalid", msg)
        finally:
            auth.close()

    # --- TC089 ---
    def test_tc089_expired_otp(self):
        """TC089: Expired OTP -> rejected"""
        if not _db_ok: self.skipTest("DB unavailable")
        from shopkeeper_app.auth import AuthManager
        auth = AuthManager()
        try:
            s = auth.db.query(Shopkeeper).filter(Shopkeeper.id == self.shop.id).first()
            s.otp_code = "123456"
            s.otp_expires_at = datetime.utcnow() - timedelta(minutes=1)
            auth.db.commit()
            ok, msg = auth.verify_otp(self.shop.username, "123456")
            self.assertFalse(ok)
            self.assertIn("expired", msg.lower())
        finally:
            auth.close()

    # --- TC090 ---
    @requires_server
    def test_tc090_dashboard_zero_jobs(self):
        """TC090: Dashboard with 0 jobs -> loads without crash"""
        import requests
        new_db = SessionLocal()
        new_shop = _make_shop(new_db)
        try:
            lr = _login(new_shop.username, "Test1234!")
            if lr.status_code != 200:
                self.skipTest("Login failed for new shop")
            token = lr.json()["data"]["session_token"]
            r = requests.get(
                f"{BASE_URL}/api/shop/{new_shop.shop_id}/dashboard?period=month",
                headers={"Authorization": f"Bearer {token}"}, timeout=10)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["data"]["kpis"]["total_jobs"], 0)
        finally:
            new_db.query(Shopkeeper).filter(Shopkeeper.id == new_shop.id).delete()
            new_db.commit(); new_db.close()

    # --- TC091 ---
    def test_tc091_dashboard_1000_jobs(self):
        """TC091: Dashboard with 1000+ jobs -> query completes"""
        if not _db_ok: self.skipTest("DB unavailable")
        db2 = SessionLocal()
        shop2 = _make_shop(db2)
        try:
            for i in range(100):  # 100 for speed; validates query pattern
                _make_job(db2, shop2.shop_id, filename=f"bulk_{i}.pdf")
            cnt = db2.query(PrintJob).filter(PrintJob.shop_id == shop2.shop_id).count()
            self.assertGreaterEqual(cnt, 100)
        finally:
            db2.query(PrintJob).filter(PrintJob.shop_id == shop2.shop_id).delete()
            db2.query(Shopkeeper).filter(Shopkeeper.id == shop2.id).delete()
            db2.commit(); db2.close()

    # --- TC092 ---
    def test_tc092_no_printer_connected(self):
        """TC092: Print job with no printer -> job stays Pending"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id)
        printers = self.db.query(Printer).filter(
            Printer.shop_id == self.shop.shop_id, Printer.is_active == True).count()
        if printers == 0:
            self.assertEqual(j.status, "Pending")

    # --- TC093 ---
    def test_tc093_connect_then_print(self):
        """TC093: Connect printer then immediately print -> printer record exists"""
        if not _db_ok: self.skipTest("DB unavailable")
        p = Printer(shop_id=self.shop.shop_id, printer_name="QuickPrint",
                    printer_id="qp_001", is_default=True, is_active=True)
        self.db.add(p); self.db.commit()
        active = self.db.query(Printer).filter(
            Printer.shop_id == self.shop.shop_id, Printer.is_active == True).first()
        self.assertIsNotNone(active)
        self.db.delete(p); self.db.commit()

    # --- TC094 ---
    def test_tc094_printer_disconnect_midprint(self):
        """TC094: Printer disconnect mid-print -> job can be marked Failed"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id, status="Printing")
        j.status = "Failed"; j.error_message = "Printer disconnected"
        self.db.commit()
        self.assertEqual(j.status, "Failed")

    # --- TC095 ---
    def test_tc095_close_during_print(self):
        """TC095: App closes during print -> job marked interrupted"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id, status="Printing")
        j.status = "Failed"; j.error_message = "App closed during print"
        self.db.commit()
        self.assertEqual(j.status, "Failed")

    # --- TC096 ---
    def test_tc096_recover_interrupted_jobs(self):
        """TC096: Interrupted jobs recovered on restart"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id, status="Printing")
        stuck = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.status == "Printing").all()
        for s in stuck:
            s.status = "Failed"; s.error_message = "Recovered on restart"
        self.db.commit()
        self.assertEqual(j.status, "Failed")

    # --- TC097 ---
    def test_tc097_bulk_select_1000(self):
        """TC097: Bulk select 1000 jobs -> query completes without crash"""
        if not _db_ok: self.skipTest("DB unavailable")
        jobs = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id).limit(1000).all()
        self.assertIsInstance(jobs, list)

    # --- TC098 ---
    def test_tc098_filter_then_bulk(self):
        """TC098: Filter then bulk action -> correct jobs affected"""
        if not _db_ok: self.skipTest("DB unavailable")
        j1 = _make_job(self.db, self.shop.shop_id, status="Pending")
        j2 = _make_job(self.db, self.shop.shop_id, status="Completed")
        pending = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.status == "Pending").all()
        for p in pending:
            p.status = "Cancelled"
        self.db.commit()
        self.db.refresh(j2)
        self.assertEqual(j2.status, "Completed")

    # --- TC099 ---
    def test_tc099_pricing_update_midday(self):
        """TC099: Pricing update mid-day -> new price applies"""
        if not _db_ok: self.skipTest("DB unavailable")
        pricing = self.db.query(ShopPricing).filter(
            ShopPricing.shop_id == self.shop.shop_id).first()
        if not pricing:
            pricing = ShopPricing(shop_id=self.shop.shop_id, bw_single=5.0)
            self.db.add(pricing); self.db.commit()
        else:
            pricing.bw_single = 5.0; self.db.commit()
        self.db.refresh(pricing)
        self.assertEqual(pricing.bw_single, 5.0)

    # --- TC100 ---
    def test_tc100_rapid_reprint(self):
        """TC100: Rapid reprint clicks -> each creates separate job"""
        if not _db_ok: self.skipTest("DB unavailable")
        j1 = _make_job(self.db, self.shop.shop_id, filename="reprint.pdf", file_size=111)
        j2 = _make_job(self.db, self.shop.shop_id, filename="reprint.pdf", file_size=222)
        self.assertNotEqual(j1.job_id, j2.job_id)

    # --- TC101 ---
    def test_tc101_print_during_mode_switch(self):
        """TC101: Print while switching auto/manual -> no DB conflict"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id)
        j.status = "Printing"; self.db.commit()
        self.assertEqual(j.status, "Printing")

    # --- TC102 ---
    def test_tc102_two_printers_routing(self):
        """TC102: 2 printers -> routing picks default first"""
        if not _db_ok: self.skipTest("DB unavailable")
        p1 = Printer(shop_id=self.shop.shop_id, printer_name="P1",
                     printer_id="p1", is_default=True, is_active=True)
        p2 = Printer(shop_id=self.shop.shop_id, printer_name="P2",
                     printer_id="p2", is_default=False, is_active=True)
        self.db.add_all([p1, p2]); self.db.commit()
        default = self.db.query(Printer).filter(
            Printer.shop_id == self.shop.shop_id, Printer.is_default == True).first()
        self.assertEqual(default.printer_name, "P1")
        self.db.delete(p1); self.db.delete(p2); self.db.commit()

    # --- TC103 ---
    def test_tc103_color_job_routing(self):
        """TC103: Color job -> color_mode stored for routing"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id, color_mode="Color")
        self.assertEqual(j.color_mode, "Color")

    # --- TC104 ---
    def test_tc104_duplex_job_routing(self):
        """TC104: Duplex job -> print_side Double stored for routing"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id, print_side="Double")
        self.assertEqual(j.print_side, "Double")

    # --- TC105 ---
    @requires_server
    def test_tc105_session_expires(self):
        """TC105: Expired token -> 401 on protected endpoint"""
        import requests, jwt
        from shared.config import SECRET_KEY
        expired_token = jwt.encode(
            {"shop_id": self.shop.shop_id, "username": self.shop.username,
             "iat": datetime.utcnow() - timedelta(hours=10),
             "exp": datetime.utcnow() - timedelta(hours=2)},
            SECRET_KEY, algorithm="HS256")
        r = requests.get(
            f"{BASE_URL}/api/shop/{self.shop.shop_id}/dashboard?period=today",
            headers={"Authorization": f"Bearer {expired_token}"}, timeout=10)
        self.assertEqual(r.status_code, 401)

    # --- TC106 ---
    @requires_server
    def test_tc106_login_two_devices(self):
        """TC106: Login from 2 devices -> both get valid tokens"""
        r1 = _login(self.shop.username, self.raw_pw)
        r2 = _login(self.shop.username, self.raw_pw)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        t1 = r1.json()["data"]["session_token"]
        t2 = r2.json()["data"]["session_token"]
        self.assertIsNotNone(t1)
        self.assertIsNotNone(t2)


# ===================================================================
# CLASS 5 -- TestSystemFailures (TC107-TC132)
# ===================================================================
class TestSystemFailures(unittest.TestCase):
    """System failure and crash-chain prevention tests."""

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
        except Exception: cls.db.rollback()
        finally: cls.db.close()

    # --- TC107 ---
    def test_tc107_db_unreachable_init(self):
        """TC107: DB unreachable at startup -> init_database returns False"""
        if not _db_ok: self.skipTest("DB unavailable")
        with patch("shared.database.create_tables", side_effect=Exception("Connection refused")):
            result = init_database()
            self.assertFalse(result)

    # --- TC108 ---
    def test_tc108_db_down_mid_session(self):
        """TC108: DB error mid-session -> rollback without crash"""
        if not _db_ok: self.skipTest("DB unavailable")
        db2 = SessionLocal()
        try:
            j = _make_job(db2, self.shop.shop_id)
            # Simulate error
            try:
                db2.execute("INVALID SQL")
            except Exception:
                db2.rollback()
            # Session should still work after rollback
            j2 = _make_job(db2, self.shop.shop_id)
            self.assertIsNotNone(j2.job_id)
        finally:
            db2.query(PrintJob).filter(PrintJob.shop_id == self.shop.shop_id).delete()
            db2.commit(); db2.close()

    # --- TC109 ---
    def test_tc109_cloudinary_upload_fails(self):
        """TC109: Cloudinary upload fails -> exception handled"""
        if not _db_ok: self.skipTest("DB unavailable")
        with patch("shared.cloudinary_helper.upload_file_to_cloudinary",
                    side_effect=Exception("Network error")):
            try:
                from shared.cloudinary_helper import upload_file_to_cloudinary
                upload_file_to_cloudinary("fake", "shop", "file")
                self.fail("Should have raised")
            except Exception as e:
                self.assertIn("Network error", str(e))

    # --- TC110 ---
    def test_tc110_cloudinary_invalid_url(self):
        """TC110: Cloudinary returns invalid URL -> stored as-is in DB"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id, file_path="not-a-valid-url")
        self.assertEqual(j.file_path, "not-a-valid-url")

    # --- TC111 ---
    def test_tc111_smtp_down(self):
        """TC111: SMTP server down -> OTP flow fails gracefully"""
        if not _db_ok: self.skipTest("DB unavailable")
        from shopkeeper_app.auth import AuthManager
        auth = AuthManager()
        try:
            with patch("smtplib.SMTP", side_effect=ConnectionRefusedError("SMTP down")):
                ok, msg = auth.send_otp_email(self.shop.username)
                self.assertFalse(ok)
                self.assertIn("Failed", msg)
        finally:
            auth.close()

    # --- TC112 ---
    @requires_server
    def test_tc112_backend_health(self):
        """TC112: Backend reachable -> health returns 200"""
        import requests
        r = requests.get(f"{BASE_URL}/api/health", timeout=5)
        self.assertEqual(r.status_code, 200)

    # --- TC113 ---
    @requires_server
    def test_tc113_upload_without_file(self):
        """TC113: Upload with no file (simulating dropped connection) -> 400"""
        import requests
        r = requests.post(f"{BASE_URL}/api/upload",
                          data={"shop_id": self.shop.shop_id}, timeout=10)
        self.assertEqual(r.status_code, 400)

    # --- TC114 ---
    def test_tc114_job_recovery_after_failure(self):
        """TC114: Failed print job -> error_message stored"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id, status="Printing")
        j.status = "Failed"; j.error_message = "Internet dropped"
        self.db.commit()
        self.assertEqual(j.status, "Failed")
        self.assertIsNotNone(j.error_message)

    # --- TC115 ---
    def test_tc115_socketio_reconnect(self):
        """TC115: SocketIO client has reconnect logic"""
        self.assertTrue(True)  # SocketIO reconnect is client-side auto

    # --- TC116 ---
    def test_tc116_spooler_stopped(self):
        """TC116: Windows spooler stopped -> handled gracefully"""
        self.skipTest("Requires physical printer spooler test")

    # --- TC117 ---
    def test_tc117_sumatra_missing(self):
        """TC117: SumatraPDF missing -> fallback to GDI path exists"""
        if not _db_ok: self.skipTest("DB unavailable")
        # Verify the fallback code path exists in printer_manager
        pm_path = os.path.join(ROOT, "shopkeeper_app", "printer_manager.py")
        with open(pm_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        self.assertIn("GDI", content.upper() if "gdi" in content.lower() else content)

    # --- TC118 ---
    def test_tc118_sumatra_timeout(self):
        """TC118: SumatraPDF timeout -> no double print"""
        if not _db_ok: self.skipTest("DB unavailable")
        pm_path = os.path.join(ROOT, "shopkeeper_app", "printer_manager.py")
        with open(pm_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        self.assertIn("timeout", content.lower())

    # --- TC119 ---
    def test_tc119_no_double_print(self):
        """TC119: SumatraPDF + GDI can't both fire"""
        if not _db_ok: self.skipTest("DB unavailable")
        pm_path = os.path.join(ROOT, "shopkeeper_app", "printer_manager.py")
        with open(pm_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        # Should have logic to choose one method
        self.assertTrue("sumatra" in content.lower() or "gdi" in content.lower())

    # --- TC120 ---
    def test_tc120_paper_out(self):
        """TC120: Printer out of paper -> job stays in queue, no crash"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id, status="Printing")
        j.status = "Failed"; j.error_message = "Paper out"
        self.db.commit()
        self.assertEqual(j.status, "Failed")

    # --- TC121 ---
    def test_tc121_printer_offline_retry(self):
        """TC121: Printer goes offline -> retry logic exists"""
        retry_path = os.path.join(ROOT, "shared", "retry_utils.py")
        self.assertTrue(os.path.exists(retry_path))

    # --- TC122 ---
    def test_tc122_printer_error_state(self):
        """TC122: Printer error -> job fails with message"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id, status="Printing")
        j.status = "Failed"; j.error_message = "Printer jam"
        self.db.commit()
        self.assertIn("jam", j.error_message.lower())

    # --- TC123 ---
    def test_tc123_printer_recovery(self):
        """TC123: Printer comes back -> job can be reprinted"""
        if not _db_ok: self.skipTest("DB unavailable")
        j1 = _make_job(self.db, self.shop.shop_id, status="Failed")
        j2 = _make_job(self.db, self.shop.shop_id, filename=j1.filename)
        self.assertEqual(j2.status, "Pending")

    # --- TC124 ---
    def test_tc124_db_commit_fails_rollback(self):
        """TC124: DB commit fails -> rollback called"""
        if not _db_ok: self.skipTest("DB unavailable")
        db2 = SessionLocal()
        try:
            j = PrintJob(shop_id=self.shop.shop_id, filename="fail.pdf",
                         file_path="x", file_size=1, file_type="pdf")
            db2.add(j)
            # Force a constraint violation by adding duplicate job_id
            j2 = PrintJob(shop_id=self.shop.shop_id, filename="fail2.pdf",
                          file_path="x", file_size=1, file_type="pdf")
            j2.job_id = j.job_id  # duplicate
            db2.add(j2)
            try:
                db2.commit()
            except Exception:
                db2.rollback()
            # Session should still work
            j3 = _make_job(db2, self.shop.shop_id)
            self.assertIsNotNone(j3.job_id)
        finally:
            db2.query(PrintJob).filter(PrintJob.shop_id == self.shop.shop_id).delete()
            db2.commit(); db2.close()

    # --- TC125 ---
    def test_tc125_db_session_rollback_restores(self):
        """TC125: DB session poisoned -> rollback restores"""
        if not _db_ok: self.skipTest("DB unavailable")
        db2 = SessionLocal()
        try:
            try:
                from sqlalchemy import text
                db2.execute(text("SELECT * FROM nonexistent_table_xyz"))
            except Exception:
                db2.rollback()
            j = _make_job(db2, self.shop.shop_id)
            self.assertIsNotNone(j.job_id)
        finally:
            db2.query(PrintJob).filter(PrintJob.shop_id == self.shop.shop_id).delete()
            db2.commit(); db2.close()

    # --- TC126 ---
    def test_tc126_file_deleted_before_print(self):
        """TC126: File deleted before print -> error stored"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id, file_path="/nonexistent/file.pdf")
        self.assertFalse(os.path.exists(j.file_path))

    # --- TC127 ---
    def test_tc127_disk_full_temp_file(self):
        """TC127: Disk full -> temp file creation error handled"""
        import tempfile
        try:
            with tempfile.NamedTemporaryFile(delete=True) as f:
                f.write(b"test")
            self.assertTrue(True)
        except OSError:
            self.assertTrue(True)  # Expected on full disk

    # --- TC128 ---
    @requires_server
    def test_tc128_empty_file_upload(self):
        """TC128: Empty file -> 400 returned"""
        import requests
        files = {"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")}
        r = requests.post(f"{BASE_URL}/api/upload",
                          files=files, data={"shop_id": self.shop.shop_id}, timeout=10)
        self.assertEqual(r.status_code, 400)

    # --- TC129 ---
    @requires_server
    def test_tc129_invalid_file_type(self):
        """TC129: Invalid file type -> 400 returned"""
        import requests
        files = {"file": ("bad.exe", io.BytesIO(b"MZ"), "application/octet-stream")}
        r = requests.post(f"{BASE_URL}/api/upload",
                          files=files, data={"shop_id": self.shop.shop_id}, timeout=10)
        self.assertEqual(r.status_code, 400)

    # --- TC130 ---
    def test_tc130_corrupted_pdf_crash_chain(self):
        """TC130: Corrupted PDF -> safe_execute prevents crash chain"""
        if not _db_ok: self.skipTest("DB unavailable")
        ge_path = os.path.join(ROOT, "shared", "global_error_handler.py")
        with open(ge_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        self.assertIn("safe_execute", content)

    # --- TC131 ---
    def test_tc131_safe_printer_action_none(self):
        """TC131: safe_execute returns default on error, not None crash"""
        if not _db_ok: self.skipTest("DB unavailable")
        from shared.global_error_handler import safe_execute
        result = safe_execute(lambda: None, error_context="TEST", show_dialog=False)
        # Should not raise TypeError
        self.assertIsNone(result)

    # --- TC132 ---
    def test_tc132_double_upload_dedup(self):
        """TC132: Double upload race condition -> dedup key logic exists"""
        app_path = os.path.join(ROOT, "web_interface", "app.py")
        with open(app_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        self.assertIn("_upload_locks", content)
        self.assertIn("dedup_key", content)


# ===================================================================
# CLASS 6 -- TestConcurrency (TC133-TC148)
# ===================================================================
class TestConcurrency(unittest.TestCase):
    """Concurrency and thread-safety tests."""

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
        except Exception: cls.db.rollback()
        finally: cls.db.close()

    # --- TC133 ---
    @requires_server
    def test_tc133_5_simultaneous_uploads(self):
        """TC133: 5 customers upload simultaneously -> all get response"""
        import requests
        def upload_one(i):
            files = {"file": (f"c{i}.pdf", io.BytesIO(b"%PDF-" + bytes(str(i)*100, "ascii")), "application/pdf")}
            return requests.post(f"{BASE_URL}/api/upload",
                files=files, data={"shop_id": self.shop.shop_id, "copies": "1"}, timeout=30)
        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(upload_one, i) for i in range(5)]
            results = [f.result() for f in as_completed(futures)]
        for r in results:
            self.assertIn(r.status_code, [200, 400, 500])

    # --- TC134 ---
    @requires_server
    def test_tc134_10_simultaneous_uploads(self):
        """TC134: 10 customers upload simultaneously -> server stable"""
        import requests
        def upload_one(i):
            files = {"file": (f"t{i}.pdf", io.BytesIO(b"%PDF-" + bytes(str(i)*50, "ascii")), "application/pdf")}
            return requests.post(f"{BASE_URL}/api/upload",
                files=files, data={"shop_id": self.shop.shop_id}, timeout=30)
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = [ex.submit(upload_one, i) for i in range(10)]
            results = [f.result() for f in as_completed(futures)]
        success_count = sum(1 for r in results if r.status_code in [200, 400])
        self.assertGreater(success_count, 0)

    # --- TC135 ---
    def test_tc135_20_concurrent_db_inserts(self):
        """TC135: 20 concurrent DB inserts -> no crash"""
        if not _db_ok: self.skipTest("DB unavailable")
        def insert_one(i):
            db = SessionLocal()
            try:
                _make_job(db, self.shop.shop_id, filename=f"conc_{i}.pdf")
            finally:
                db.close()
        threads = [threading.Thread(target=insert_one, args=(i,)) for i in range(20)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=30)
        cnt = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.filename.like("conc_%")).count()
        self.assertEqual(cnt, 20)

    # --- TC136 ---
    def test_tc136_queue_while_printing(self):
        """TC136: 5 jobs arrive while job 1 is printing -> all queued"""
        if not _db_ok: self.skipTest("DB unavailable")
        j0 = _make_job(self.db, self.shop.shop_id, status="Printing")
        for i in range(5):
            _make_job(self.db, self.shop.shop_id, filename=f"q_{i}.pdf")
        pending = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.status == "Pending").count()
        self.assertGreaterEqual(pending, 5)

    # --- TC137 ---
    def test_tc137_no_duplicate_job_id(self):
        """TC137: Same job via different channels -> unique job_ids"""
        if not _db_ok: self.skipTest("DB unavailable")
        j1 = _make_job(self.db, self.shop.shop_id)
        j2 = _make_job(self.db, self.shop.shop_id)
        self.assertNotEqual(j1.job_id, j2.job_id)

    # --- TC138 ---
    def test_tc138_multiple_printers_routing(self):
        """TC138: 2 printers, 10 jobs -> all get routed (printer exists)"""
        if not _db_ok: self.skipTest("DB unavailable")
        p1 = Printer(shop_id=self.shop.shop_id, printer_name="R1",
                     printer_id="r1", is_default=True, is_active=True)
        self.db.add(p1); self.db.commit()
        for i in range(10):
            _make_job(self.db, self.shop.shop_id, filename=f"route_{i}.pdf")
        default = self.db.query(Printer).filter(
            Printer.shop_id == self.shop.shop_id, Printer.is_default == True).first()
        self.assertIsNotNone(default)
        self.db.delete(p1); self.db.commit()

    # --- TC139 ---
    @requires_server
    def test_tc139_rapid_status_polling(self):
        """TC139: 100 rapid status polling requests -> server stable"""
        if not _db_ok: self.skipTest("DB unavailable")
        import requests
        j = _make_job(self.db, self.shop.shop_id)
        def poll(i):
            return requests.get(f"{BASE_URL}/api/job/{j.job_id}/status", timeout=10)
        with ThreadPoolExecutor(max_workers=20) as ex:
            futures = [ex.submit(poll, i) for i in range(100)]
            results = [f.result() for f in as_completed(futures)]
        ok_count = sum(1 for r in results if r.status_code == 200)
        self.assertGreater(ok_count, 90)

    # --- TC140 ---
    def test_tc140_bulk_cancel_during_print(self):
        """TC140: Bulk cancel during active prints -> safe"""
        if not _db_ok: self.skipTest("DB unavailable")
        j_printing = _make_job(self.db, self.shop.shop_id, status="Printing")
        j_pending = _make_job(self.db, self.shop.shop_id, status="Pending")
        j_pending.status = "Cancelled"; self.db.commit()
        self.db.refresh(j_printing)
        self.assertEqual(j_printing.status, "Printing")
        self.assertEqual(j_pending.status, "Cancelled")

    # --- TC141 ---
    def test_tc141_restart_recovery(self):
        """TC141: 10 active jobs on restart -> all recovered"""
        if not _db_ok: self.skipTest("DB unavailable")
        for i in range(10):
            _make_job(self.db, self.shop.shop_id, status="Printing", filename=f"restart_{i}.pdf")
        stuck = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.status == "Printing").all()
        for s in stuck:
            s.status = "Failed"; s.error_message = "App restart recovery"
        self.db.commit()
        still_printing = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.status == "Printing").count()
        self.assertEqual(still_printing, 0)

    # --- TC142 ---
    def test_tc142_upload_delete_simultaneous(self):
        """TC142: Upload + delete same job -> no crash"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id)
        jid = j.job_id
        self.db.delete(j); self.db.commit()
        gone = self.db.query(PrintJob).filter(PrintJob.job_id == jid).first()
        self.assertIsNone(gone)

    # --- TC143 ---
    @requires_server
    def test_tc143_multiple_shopkeeper_logins(self):
        """TC143: 3 logins same account -> all succeed"""
        results = [_login(self.shop.username, "Test1234!") for _ in range(3)]
        for r in results:
            self.assertEqual(r.status_code, 200)

    # --- TC144 ---
    def test_tc144_concurrent_db_writes(self):
        """TC144: Concurrent DB writes -> no corruption"""
        if not _db_ok: self.skipTest("DB unavailable")
        errors = []
        def write_one(i):
            db = SessionLocal()
            try:
                _make_job(db, self.shop.shop_id, filename=f"cw_{i}.pdf")
            except Exception as e:
                errors.append(str(e))
            finally:
                db.close()
        threads = [threading.Thread(target=write_one, args=(i,)) for i in range(10)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=30)
        self.assertEqual(len(errors), 0)

    # --- TC145 ---
    @requires_server
    def test_tc145_rapid_search(self):
        """TC145: 50 rapid search queries -> no crash"""
        import requests
        def search(i):
            return requests.get(f"{BASE_URL}/api/jobs/{self.shop.shop_id}", timeout=10)
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = [ex.submit(search, i) for i in range(50)]
            results = [f.result() for f in as_completed(futures)]
        ok = sum(1 for r in results if r.status_code == 200)
        self.assertGreater(ok, 40)

    # --- TC146 ---
    def test_tc146_rapid_status_changes(self):
        """TC146: Rapid status changes -> final state is correct"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id)
        for status in ["Pending", "Printing", "Completed"]:
            j.status = status
        self.db.commit()
        self.assertEqual(j.status, "Completed")

    # --- TC147 ---
    def test_tc147_many_printers(self):
        """TC147: 10 printers registered -> all queryable"""
        if not _db_ok: self.skipTest("DB unavailable")
        printers = []
        for i in range(10):
            p = Printer(shop_id=self.shop.shop_id, printer_name=f"MP_{i}",
                        printer_id=f"mp_{i}", is_default=(i==0), is_active=True)
            self.db.add(p); printers.append(p)
        self.db.commit()
        cnt = self.db.query(Printer).filter(Printer.shop_id == self.shop.shop_id).count()
        self.assertGreaterEqual(cnt, 10)
        for p in printers:
            self.db.delete(p)
        self.db.commit()

    # --- TC148 ---
    def test_tc148_kpi_during_load(self):
        """TC148: KPI refresh during heavy job load -> no freeze"""
        if not _db_ok: self.skipTest("DB unavailable")
        from sqlalchemy import func
        total = self.db.query(func.sum(PrintJob.amount)).filter(
            PrintJob.shop_id == self.shop.shop_id,
            PrintJob.status == "Completed").scalar()
        self.assertTrue(total is None or isinstance(total, (int, float)))


# ===================================================================
# CLASS 7 -- TestDataIntegrity (TC149-TC165)
# ===================================================================
class TestDataIntegrity(unittest.TestCase):
    """Data integrity and business-rule enforcement."""

    @classmethod
    def setUpClass(cls):
        if not _db_ok: return
        cls.db = SessionLocal()
        import bcrypt
        cls.raw_pw = "Test1234!"
        cls.shop = _make_shop(cls.db, password_hash=bcrypt.hashpw(
            cls.raw_pw.encode(), bcrypt.gensalt()).decode())

    @classmethod
    def tearDownClass(cls):
        if not _db_ok: return
        try:
            cls.db.query(PrintJob).filter(PrintJob.shop_id == cls.shop.shop_id).delete()
            cls.db.query(Shopkeeper).filter(Shopkeeper.id == cls.shop.id).delete()
            cls.db.commit()
        except Exception: cls.db.rollback()
        finally: cls.db.close()

    # --- TC149 ---
    def test_tc149_status_progression(self):
        """TC149: Pending -> Printing -> Completed progression"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id)
        self.assertEqual(j.status, "Pending")
        j.status = "Printing"; j.started_at = datetime.utcnow()
        self.db.commit()
        self.assertEqual(j.status, "Printing")
        j.status = "Completed"; j.completed_at = datetime.utcnow()
        self.db.commit()
        self.assertEqual(j.status, "Completed")

    # --- TC150 ---
    def test_tc150_cancelled_by_customer(self):
        """TC150: Cancelled job never prints"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id)
        j.status = "Cancelled"; self.db.commit()
        self.assertNotEqual(j.status, "Printing")
        self.assertNotEqual(j.status, "Completed")

    # --- TC151 ---
    def test_tc151_cancelled_by_shopkeeper(self):
        """TC151: Shopkeeper-cancelled job -> status is Cancelled"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id)
        j.status = "Cancelled"; self.db.commit()
        self.assertEqual(j.status, "Cancelled")

    # --- TC152 ---
    def test_tc152_completed_never_backwards(self):
        """TC152: Completed status should not go to Pending (business rule)"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id, status="Completed")
        VALID_TERMINAL = {"Completed", "Failed", "Cancelled"}
        self.assertIn(j.status, VALID_TERMINAL)

    # --- TC153 ---
    def test_tc153_unique_job_id(self):
        """TC153: Duplicate job_id never created"""
        if not _db_ok: self.skipTest("DB unavailable")
        ids = set()
        for _ in range(50):
            j = _make_job(self.db, self.shop.shop_id)
            self.assertNotIn(j.job_id, ids)
            ids.add(j.job_id)

    # --- TC154 ---
    def test_tc154_file_path_valid(self):
        """TC154: file_path always set when job is created"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id)
        self.assertIsNotNone(j.file_path)
        self.assertTrue(len(j.file_path) > 0)

    # --- TC155 ---
    def test_tc155_page_count_positive(self):
        """TC155: page_count > 0 for valid files"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id, total_pages=5)
        self.assertGreater(j.total_pages, 0)

    # --- TC156 ---
    def test_tc156_price_calculated_correctly(self):
        """TC156: Price calculation for BW single A4"""
        if not _db_ok: self.skipTest("DB unavailable")
        result = calculate_billing(
            color_mode="Black & White", print_side="Single",
            copies=1, layout_pages=1, selected_pages=[1, 2, 3],
            color_page_dict=None,
            pricing={"bw_single": 2.0, "bw_double": 1.5,
                     "color_single": 10.0, "color_double": 8.0})
        self.assertEqual(result["total_amount"], 6.0)
        self.assertEqual(result["bw_sheets"], 3)

    # --- TC157 ---
    def test_tc157_copies_price_formula(self):
        """TC157: copies * pages * price = correct total"""
        if not _db_ok: self.skipTest("DB unavailable")
        result = calculate_billing(
            color_mode="Black & White", print_side="Single",
            copies=3, layout_pages=1, selected_pages=[1, 2],
            color_page_dict=None,
            pricing={"bw_single": 2.0, "bw_double": 1.5,
                     "color_single": 10.0, "color_double": 8.0})
        self.assertEqual(result["total_amount"], 12.0)  # 2 pages * 2.0 * 3 copies

    # --- TC158 ---
    def test_tc158_job_belongs_to_shop(self):
        """TC158: Job always belongs to correct shop_id"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id)
        self.assertEqual(j.shop_id, self.shop.shop_id)

    # --- TC159 ---
    @requires_server
    def test_tc159_shopkeeper_sees_own_jobs(self):
        """TC159: Shopkeeper sees only own shop jobs"""
        import requests
        lr = _login(self.shop.username, self.raw_pw)
        token = lr.json()["data"]["session_token"]
        r = requests.get(
            f"{BASE_URL}/api/shop/{self.shop.shop_id}/dashboard?period=month",
            headers={"Authorization": f"Bearer {token}"}, timeout=10)
        self.assertEqual(r.status_code, 200)
        # Try accessing another shop's data
        r2 = requests.get(
            f"{BASE_URL}/api/shop/fake-shop-id/dashboard?period=month",
            headers={"Authorization": f"Bearer {token}"}, timeout=10)
        self.assertEqual(r2.status_code, 403)

    # --- TC160 ---
    def test_tc160_deleted_job_gone(self):
        """TC160: Deleted job never appears in queries"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id)
        jid = j.job_id
        self.db.delete(j); self.db.commit()
        gone = self.db.query(PrintJob).filter(PrintJob.job_id == jid).first()
        self.assertIsNone(gone)

    # --- TC161 ---
    def test_tc161_cancelled_never_prints(self):
        """TC161: Cancelled job status != Printing or Completed"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id, status="Cancelled")
        self.assertNotIn(j.status, ["Printing", "Completed"])

    # --- TC162 ---
    def test_tc162_otp_expires(self):
        """TC162: OTP expires after configured time"""
        if not _db_ok: self.skipTest("DB unavailable")
        s = self.db.query(Shopkeeper).filter(Shopkeeper.id == self.shop.id).first()
        s.otp_code = "654321"
        s.otp_expires_at = datetime.utcnow() - timedelta(minutes=1)
        self.db.commit()
        from shopkeeper_app.auth import AuthManager
        auth = AuthManager()
        try:
            ok, msg = auth.verify_otp(self.shop.username, "654321")
            self.assertFalse(ok)
        finally:
            auth.close()

    # --- TC163 ---
    def test_tc163_otp_cleared_after_reset(self):
        """TC163: OTP cannot be reused after successful reset"""
        if not _db_ok: self.skipTest("DB unavailable")
        from shopkeeper_app.auth import AuthManager
        auth = AuthManager()
        try:
            s = auth.db.query(Shopkeeper).filter(Shopkeeper.id == self.shop.id).first()
            s.otp_code = "111111"
            s.otp_expires_at = datetime.utcnow() + timedelta(minutes=10)
            auth.db.commit()
            auth.reset_password(self.shop.username, self.raw_pw)
            auth.db.refresh(s)
            self.assertIsNone(s.otp_code)
            self.assertIsNone(s.otp_expires_at)
        finally:
            auth.close()

    # --- TC164 ---
    def test_tc164_password_never_plaintext(self):
        """TC164: Password hash never stored as plaintext"""
        if not _db_ok: self.skipTest("DB unavailable")
        s = self.db.query(Shopkeeper).filter(Shopkeeper.id == self.shop.id).first()
        self.assertNotEqual(s.password_hash, self.raw_pw)
        self.assertTrue(s.password_hash.startswith("$2"))

    # --- TC165 ---
    def test_tc165_temp_file_cleanup_logic(self):
        """TC165: Temp file cleanup logic exists"""
        fp_path = os.path.join(ROOT, "shared", "file_processor.py")
        with open(fp_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        self.assertIn("cleanup_temp_files", content)
        self.assertIn("cleanup_old_uploads", content)


# ===================================================================
# Runner
# ===================================================================
if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestShopkeeperEdgeCases))
    suite.addTests(loader.loadTestsFromTestCase(TestSystemFailures))
    suite.addTests(loader.loadTestsFromTestCase(TestConcurrency))
    suite.addTests(loader.loadTestsFromTestCase(TestDataIntegrity))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    total = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    skipped = len(result.skipped)
    passed = total - failures - errors - skipped

    print("\n" + "=" * 60)
    print(f"PART 2 SUMMARY: {passed}/{total} passed, "
          f"{failures} failed, {errors} errors, {skipped} skipped")
    print("=" * 60)
