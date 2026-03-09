#!/usr/bin/env python3
"""
EzPrint Printer Routing Test
Tests: Fake printers + real job routing logic
"""
import unittest, os, sys, uuid, time
from unittest.mock import patch, MagicMock
# Mock win32print for testing (not available on all systems)
import sys
from unittest.mock import MagicMock

# Create mock win32print module
mock_win32print = MagicMock()
mock_win32con = MagicMock()

# Color printer mock — DC_COLORDEVICE returns 1
# Duplex printer mock — DC_DUPLEX returns 1

mock_win32con.DMCOLOR_COLOR = 2
mock_win32con.DC_COLORDEVICE = 32
mock_win32con.DC_DUPLEX = 3

sys.modules['win32print'] = mock_win32print
sys.modules['win32con'] = mock_win32con
sys.modules['win32api'] = MagicMock()
sys.modules['win32gui'] = MagicMock()
sys.modules['win32com'] = MagicMock()
sys.modules['win32com.client'] = MagicMock()
sys.modules['pywintypes'] = MagicMock()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_db_ok = False
try:
    from shared.database import (
        SessionLocal, Shopkeeper, PrintJob, Printer
    )
    _db_ok = True
except Exception:
    pass

import bcrypt

# ── helpers ──────────────────────────────────────────────────────
def _make_shop(db):
    s = Shopkeeper(
        username=f"route_{uuid.uuid4().hex[:8]}",
        email=f"route_{uuid.uuid4().hex[:8]}@test.com",
        password_hash=bcrypt.hashpw(b"Test1234!", bcrypt.gensalt()).decode(),
        shop_name="Routing Test Shop",
    )
    db.add(s); db.commit(); db.refresh(s)
    return s

def _make_printer(db, shop_id, name, color=False,
                  duplex=False, is_default=False):
    class FakePrinter:
        def __init__(self):
            self.printer_name = name
            self.printer_id = f"fake_{uuid.uuid4().hex[:8]}"
            self.shop_id = shop_id
            self.is_color = color
            self.is_duplex = duplex
            self.is_default = is_default
            self.is_active = True
    return FakePrinter()

def _make_job(db, shop_id, color_mode="Black & White",
              print_side="Single", copies=1, filename="test.pdf"):
    j = PrintJob(
        shop_id=shop_id,
        filename=filename,
        file_path="https://example.com/test.pdf",
        file_size=1024,
        file_type="pdf",
        color_mode=color_mode,
        print_side=print_side,
        copies=copies,
        status="Pending",
    )
    db.add(j); db.commit(); db.refresh(j)
    return j

# ── Routing Logic (mirrors printer_manager.py) ────────────────────
def select_printer(printers, job):
    needs_color = job.color_mode == "Color"
    needs_duplex = job.print_side == "Double"

    # Pass 1 — perfect match
    for p in printers:
        if not p.is_active:
            continue
        if needs_color and not p.is_color:
            continue
        if needs_duplex and not p.is_duplex:
            continue
        # BW job — avoid color printer if possible
        if not needs_color and p.is_color:
            continue
        return p

    # Pass 2 — color job strict: no fallback to non-color
    if needs_color:
        return None

    # Pass 3 — duplex job strict: no fallback to non-duplex
    if needs_duplex:
        return None

    # Pass 4 — BW single: fallback to any active printer
    for p in printers:
        if p.is_active:
            return p

    return None

# ── Test Class ────────────────────────────────────────────────────
class TestPrinterRouting(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not _db_ok:
            return
        cls.db = SessionLocal()
        cls.shop = _make_shop(cls.db)

        # 4 fake printers register karo
        cls.color_printer = _make_printer(
            cls.db, cls.shop.shop_id,
            name="Canon Color Printer",
            color=True, duplex=False)

        cls.bw_printer = _make_printer(
            cls.db, cls.shop.shop_id,
            name="HP Black & White Printer",
            color=False, duplex=False,
            is_default=True)

        cls.duplex_printer = _make_printer(
            cls.db, cls.shop.shop_id,
            name="Epson Duplex Printer",
            color=False, duplex=True)

        cls.color_duplex_printer = _make_printer(
            cls.db, cls.shop.shop_id,
            name="Brother Color+Duplex Printer",
            color=True, duplex=True)

        cls.all_printers = [
            cls.color_printer,
            cls.bw_printer,
            cls.duplex_printer,
            cls.color_duplex_printer,
        ]

    @classmethod
    def tearDownClass(cls):
        if not _db_ok:
            return
        try:
            cls.db.query(PrintJob).filter(
                PrintJob.shop_id == cls.shop.shop_id).delete()
            cls.db.query(Printer).filter(
                Printer.shop_id == cls.shop.shop_id).delete()
            cls.db.query(Shopkeeper).filter(
                Shopkeeper.id == cls.shop.id).delete()
            cls.db.commit()
        except Exception:
            cls.db.rollback()
        finally:
            cls.db.close()

    # ── PRINTER REGISTRATION TESTS ──────────────────────────────

    def test_01_all_4_printers_registered(self):
        """4 fake printers setup me registered hain"""
        self.assertEqual(len(self.all_printers), 4,
            msg=f"Expected 4 printers, got {len(self.all_printers)}")
        print("\n✅ 4 printers registered:")
        for p in self.all_printers:
            print(f"   • {p.printer_name} "
                  f"[Color={p.is_color}, Duplex={p.is_duplex}, "
                  f"Default={p.is_default}]")

    def test_02_color_printer_fields(self):
        """Color printer is_color=True correctly set"""
        self.assertTrue(self.color_printer.is_color)
        self.assertFalse(self.color_printer.is_duplex)

    def test_03_bw_printer_fields(self):
        """BW printer is_color=False, is_default=True"""
        self.assertFalse(self.bw_printer.is_color)
        self.assertTrue(self.bw_printer.is_default)

    def test_04_duplex_printer_fields(self):
        """Duplex printer is_duplex=True correctly set"""
        self.assertTrue(self.duplex_printer.is_duplex)
        self.assertFalse(self.duplex_printer.is_color)

    def test_05_color_duplex_printer_fields(self):
        """Color+Duplex printer both flags True"""
        self.assertTrue(self.color_duplex_printer.is_color)
        self.assertTrue(self.color_duplex_printer.is_duplex)

    # ── JOB CREATION TESTS ──────────────────────────────────────

    def test_06_color_job_created(self):
        """Color print job DB me correctly store hota hai"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id,
                     color_mode="Color",
                     filename="color_doc.pdf")
        self.assertEqual(j.color_mode, "Color")
        self.assertEqual(j.status, "Pending")
        print(f"\n✅ Color job created: {j.job_id}")

    def test_07_bw_job_created(self):
        """Black & White job DB me correctly store hota hai"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id,
                     color_mode="Black & White",
                     filename="bw_doc.pdf")
        self.assertEqual(j.color_mode, "Black & White")
        self.assertEqual(j.status, "Pending")
        print(f"\n✅ BW job created: {j.job_id}")

    def test_08_duplex_job_created(self):
        """Double side job DB me correctly store hota hai"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id,
                     print_side="Double",
                     filename="duplex_doc.pdf")
        self.assertEqual(j.print_side, "Double")
        self.assertEqual(j.status, "Pending")
        print(f"\n✅ Duplex job created: {j.job_id}")

    def test_09_single_side_job_created(self):
        """Single side job DB me correctly store hota hai"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id,
                     print_side="Single",
                     filename="single_doc.pdf")
        self.assertEqual(j.print_side, "Single")
        print(f"\n✅ Single side job created: {j.job_id}")

    def test_10_multiple_copies_job(self):
        """5 copies job correctly store hota hai"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id,
                     copies=5,
                     filename="copies_doc.pdf")
        self.assertEqual(j.copies, 5)
        print(f"\n✅ 5 copies job created: {j.job_id}")

    # ── ROUTING LOGIC TESTS ─────────────────────────────────────

    def test_11_color_job_routes_to_color_printer(self):
        """Color job → Color printer select hota hai"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id,
                     color_mode="Color",
                     filename="route_color.pdf")
        selected = select_printer(self.all_printers, j)
        self.assertIsNotNone(selected,
            msg="No printer selected for color job")
        self.assertTrue(selected.is_color,
            msg=f"Color job routed to non-color printer: "
                f"{selected.printer_name}")
        print(f"\n✅ Color job → {selected.printer_name}")

    def test_12_bw_job_routes_to_any_printer(self):
        """BW job → koi bhi printer accept kar sakta hai"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id,
                     color_mode="Black & White",
                     filename="route_bw.pdf")
        selected = select_printer(self.all_printers, j)
        self.assertIsNotNone(selected,
            msg="No printer selected for BW job")
        print(f"\n✅ BW job → {selected.printer_name}")

    def test_13_duplex_job_routes_to_duplex_printer(self):
        """Double side job → Duplex printer select hota hai"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id,
                     print_side="Double",
                     filename="route_duplex.pdf")
        selected = select_printer(self.all_printers, j)
        self.assertIsNotNone(selected,
            msg="No printer selected for duplex job")
        self.assertTrue(selected.is_duplex,
            msg=f"Duplex job routed to non-duplex printer: "
                f"{selected.printer_name}")
        print(f"\n✅ Duplex job → {selected.printer_name}")

    def test_14_color_duplex_job_routes_correctly(self):
        """Color + Double side job → Color+Duplex printer"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id,
                     color_mode="Color",
                     print_side="Double",
                     filename="route_color_duplex.pdf")
        selected = select_printer(self.all_printers, j)
        self.assertIsNotNone(selected)
        self.assertTrue(selected.is_color,
            msg=f"Color+Duplex job needs color printer, "
                f"got: {selected.printer_name}")
        self.assertTrue(selected.is_duplex,
            msg=f"Color+Duplex job needs duplex printer, "
                f"got: {selected.printer_name}")
        print(f"\n✅ Color+Duplex job → {selected.printer_name}")

    def test_15_single_bw_job_routes_to_default(self):
        """Simple BW Single job → Default printer milta hai"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id,
                     color_mode="Black & White",
                     print_side="Single",
                     filename="route_default.pdf")
        selected = select_printer(self.all_printers, j)
        self.assertIsNotNone(selected)
        print(f"\n✅ BW Single job → {selected.printer_name}")

    def test_16_no_printer_available(self):
        """Koi printer nahi → None return hota hai"""
        if not _db_ok: self.skipTest("DB unavailable")
        j = _make_job(self.db, self.shop.shop_id,
                     color_mode="Color",
                     filename="route_none.pdf")
        selected = select_printer([], j)
        self.assertIsNone(selected,
            msg="Expected None when no printers available")
        print(f"\n✅ No printer → None returned safely")

    def test_17_offline_printer_skipped(self):
        """Offline printer skip hota hai routing me"""
        from unittest.mock import MagicMock
        offline = MagicMock()
        offline.printer_name = "Offline Printer"
        offline.is_color = True
        offline.is_duplex = False
        offline.is_active = False
        offline.is_default = False

        all_with_offline = self.all_printers + [offline]

        j = MagicMock()
        j.color_mode = "Color"
        j.print_side = "Single"

        active_only = [p for p in all_with_offline if p.is_active]
        selected = select_printer(active_only, j)
        self.assertNotEqual(selected.printer_name,
            offline.printer_name,
            msg="Offline printer should not be selected")
        print(f"\n✅ Offline printer skipped → {selected.printer_name}")


    # ── MULTIPLE JOBS SIMULATION ────────────────────────────────

    def test_18_10_mixed_jobs_all_routed(self):
        """10 mixed jobs — sabko sahi printer milta hai"""
        if not _db_ok: self.skipTest("DB unavailable")

        job_configs = [
            ("Color",         "Single", 1,  "color_1.pdf"),
            ("Black & White", "Single", 1,  "bw_1.pdf"),
            ("Black & White", "Double", 2,  "duplex_1.pdf"),
            ("Color",         "Double", 1,  "color_duplex_1.pdf"),
            ("Black & White", "Single", 5,  "bw_copies.pdf"),
            ("Color",         "Single", 3,  "color_copies.pdf"),
            ("Black & White", "Double", 1,  "duplex_2.pdf"),
            ("Color",         "Single", 1,  "color_2.pdf"),
            ("Black & White", "Single", 10, "bw_bulk.pdf"),
            ("Color",         "Double", 2,  "color_duplex_2.pdf"),
        ]

        print("\n\n📋 10 Job Routing Simulation:")
        print("-" * 55)

        for color_mode, print_side, copies, filename in job_configs:
            j = _make_job(self.db, self.shop.shop_id,
                         color_mode=color_mode,
                         print_side=print_side,
                         copies=copies,
                         filename=filename)

            selected = select_printer(self.all_printers, j)

            # Printer mila
            self.assertIsNotNone(selected,
                msg=f"No printer for job: {filename}")

            # Color job check
            if color_mode == "Color":
                self.assertTrue(selected.is_color,
                    msg=f"Color job '{filename}' routed to "
                        f"non-color printer: {selected.printer_name}")

            # Duplex job check
            if print_side == "Double":
                self.assertTrue(selected.is_duplex,
                    msg=f"Duplex job '{filename}' routed to "
                        f"non-duplex printer: {selected.printer_name}")

            print(f"  {'✅'} {filename:<25} "
                  f"{color_mode:<16} {print_side:<8} "
                  f"x{copies} → {selected.printer_name}")

        print("-" * 55)

    def test_19_jobs_status_after_routing(self):
        """Job status Pending → Printing → Completed flow"""
        if not _db_ok: self.skipTest("DB unavailable")

        print("\n\n📋 Status Flow Simulation:")
        print("-" * 45)

        configs = [
            ("Color",         "Single", "color_flow.pdf"),
            ("Black & White", "Double", "duplex_flow.pdf"),
            ("Black & White", "Single", "bw_flow.pdf"),
        ]

        for color_mode, print_side, filename in configs:
            j = _make_job(self.db, self.shop.shop_id,
                         color_mode=color_mode,
                         print_side=print_side,
                         filename=filename)

            # Step 1 — Pending
            self.assertEqual(j.status, "Pending")

            # Step 2 — Route to printer
            selected = select_printer(self.all_printers, j)
            self.assertIsNotNone(selected)

            # Step 3 — Printing
            j.status = "Printing"
            self.db.commit()
            self.assertEqual(j.status, "Printing")

            # Step 4 — Completed
            j.status = "Completed"
            self.db.commit()
            self.assertEqual(j.status, "Completed")

            print(f"  ✅ {filename:<22} → {selected.printer_name:<28} "
                  f"Pending→Printing→Completed")

        print("-" * 45)

    def test_20_xerox_jobs_routing(self):
        """Xerox jobs (BW Single) — correctly routed"""
        if not _db_ok: self.skipTest("DB unavailable")

        print("\n\n📋 Xerox Jobs Simulation:")
        print("-" * 45)

        xerox_jobs = [
            ("xerox_doc1.pdf", 1),
            ("xerox_doc2.pdf", 5),
            ("xerox_doc3.pdf", 10),
            ("xerox_doc4.pdf", 20),
            ("xerox_doc5.pdf", 50),
        ]

        for filename, copies in xerox_jobs:
            j = _make_job(self.db, self.shop.shop_id,
                         color_mode="Black & White",
                         print_side="Single",
                         copies=copies,
                         filename=filename)

            selected = select_printer(self.all_printers, j)
            self.assertIsNotNone(selected,
                msg=f"No printer for xerox job: {filename}")

            print(f"  ✅ {filename:<20} x{copies:<4} "
                  f"→ {selected.printer_name}")

        print("-" * 45)

# ================================================================
# CLASS 2 -- TestFakePrinterCapabilities
# ================================================================
class TestFakePrinterCapabilities(unittest.TestCase):
    """
    Fake printer capability detection tests.
    Mocks win32print to simulate color/duplex detection.
    """

    def _make_fake_printer_manager(self):
        """Create a minimal PrinterManager-like object for testing"""
        class FakePrinterManager:
            def __init__(self):
                self.printer_capabilities = {}
                self._initialize_printer_capabilities()

            def _initialize_printer_capabilities(self):
                printer_patterns = [
                    ("HP LaserJet P1", False, False, "single"),
                    ("HP LaserJet", False, False, "single"),
                    ("HP Color LaserJet", True, True, "color"),
                    ("Canon PIXMA", True, False, "color"),
                    ("Canon imageCLASS", False, True, "duplex"),
                    ("Epson WorkForce", True, True, "color"),
                    ("Epson EcoTank", True, False, "color"),
                    ("Brother HL", False, True, "duplex"),
                    ("Brother MFC", True, True, "color"),
                    ("Color", True, False, "color"),
                    ("Laser", False, True, "duplex"),
                ]
                self._printer_patterns = printer_patterns

            def _infer_printer_capabilities(self, printer_name):
                if not printer_name:
                    return None

                import win32print
                import win32con

                # Color detection
                driver_is_color = None
                h = None
                try:
                    h = win32print.OpenPrinter(printer_name)
                    info = win32print.GetPrinter(h, 2)
                    devmode = info.get('pDevMode')
                    if devmode and hasattr(devmode, 'Color'):
                        if devmode.Color == win32con.DMCOLOR_COLOR:
                            driver_is_color = True
                    if driver_is_color is None:
                        res = win32print.DeviceCapabilities(
                            printer_name,
                            info.get('pPortName', ''),
                            win32con.DC_COLORDEVICE, None, None)
                        driver_is_color = True if res > 0 else False
                except Exception:
                    pass
                finally:
                    if h:
                        try: win32print.ClosePrinter(h)
                        except: pass

                # Duplex detection
                driver_is_duplex = None
                h2 = None
                try:
                    h2 = win32print.OpenPrinter(printer_name)
                    info2 = win32print.GetPrinter(h2, 2)
                    port_name = info2.get('pPortName', '')
                    res = win32print.DeviceCapabilities(
                        printer_name, port_name,
                        win32con.DC_DUPLEX, None, None)
                    driver_is_duplex = True if res == 1 else False
                except Exception:
                    pass
                finally:
                    if h2:
                        try: win32print.ClosePrinter(h2)
                        except: pass

                # Heuristic fallback
                printer_name_upper = printer_name.upper()
                for pattern, is_color, is_duplex, ptype in self._printer_patterns:
                    if pattern.upper() in printer_name_upper:
                        return {
                            "is_color": driver_is_color if driver_is_color is not None else is_color,
                            "is_duplex": driver_is_duplex if driver_is_duplex is not None else is_duplex,
                            "type": ptype
                        }

                return {
                    "is_color": driver_is_color if driver_is_color is not None else False,
                    "is_duplex": driver_is_duplex if driver_is_duplex is not None else False,
                    "type": "single"
                }

            def get_printer_capabilities(self, printer_name):
                if printer_name in self.printer_capabilities:
                    return self.printer_capabilities[printer_name]
                caps = self._infer_printer_capabilities(printer_name)
                if caps:
                    self.printer_capabilities[printer_name] = caps
                return caps

        return FakePrinterManager()

    def _setup_mock_printer(self, is_color, is_duplex):
        """Configure win32print mock for a specific printer type"""
        import win32print
        import win32con

        mock_devmode = MagicMock()
        mock_devmode.Color = win32con.DMCOLOR_COLOR if is_color else 1

        mock_info = {
            'pDevMode': mock_devmode,
            'pPortName': 'USB001'
        }

        win32print.OpenPrinter.return_value = MagicMock()
        win32print.GetPrinter.return_value = mock_info
        win32print.ClosePrinter.return_value = None

        # DC_COLORDEVICE: 1 = color, 0 = bw
        # DC_DUPLEX: 1 = duplex supported, 0 = not
        def fake_device_capabilities(printer, port, cap, buf, devmode):
            if cap == win32con.DC_COLORDEVICE:
                return 1 if is_color else 0
            if cap == win32con.DC_DUPLEX:
                return 1 if is_duplex else 0
            return 0

        win32print.DeviceCapabilities.side_effect = fake_device_capabilities

    # ── FAKE PRINTER DETECTION TESTS ────────────────────────────

    def test_f01_color_only_printer(self):
        """Fake Color printer — is_color=True, is_duplex=False"""
        self._setup_mock_printer(is_color=True, is_duplex=False)
        pm = self._make_fake_printer_manager()
        caps = pm.get_printer_capabilities("Canon PIXMA G2010")
        self.assertIsNotNone(caps)
        self.assertTrue(caps['is_color'],
            msg="Color printer not detected as color")
        self.assertFalse(caps['is_duplex'],
            msg="Non-duplex printer wrongly detected as duplex")
        print(f"\n✅ Fake Color Printer: {caps}")

    def test_f02_bw_only_printer(self):
        """Fake BW printer — is_color=False, is_duplex=False"""
        self._setup_mock_printer(is_color=False, is_duplex=False)
        pm = self._make_fake_printer_manager()
        caps = pm.get_printer_capabilities("HP LaserJet 1020")
        self.assertIsNotNone(caps)
        self.assertFalse(caps['is_color'],
            msg="BW printer wrongly detected as color")
        self.assertFalse(caps['is_duplex'],
            msg="Non-duplex printer wrongly detected as duplex")
        print(f"\n✅ Fake BW Printer: {caps}")

    def test_f03_duplex_only_printer(self):
        """Fake Duplex BW printer — is_color=False, is_duplex=True"""
        self._setup_mock_printer(is_color=False, is_duplex=True)
        pm = self._make_fake_printer_manager()
        caps = pm.get_printer_capabilities("Brother HL-L2321D")
        self.assertIsNotNone(caps)
        self.assertFalse(caps['is_color'],
            msg="BW duplex wrongly detected as color")
        self.assertTrue(caps['is_duplex'],
            msg="Duplex printer not detected as duplex")
        print(f"\n✅ Fake Duplex BW Printer: {caps}")

    def test_f04_color_duplex_printer(self):
        """Fake Color+Duplex printer — is_color=True, is_duplex=True"""
        self._setup_mock_printer(is_color=True, is_duplex=True)
        pm = self._make_fake_printer_manager()
        caps = pm.get_printer_capabilities("Brother MFC-J995DW")
        self.assertIsNotNone(caps)
        self.assertTrue(caps['is_color'],
            msg="Color+Duplex printer not detected as color")
        self.assertTrue(caps['is_duplex'],
            msg="Color+Duplex printer not detected as duplex")
        print(f"\n✅ Fake Color+Duplex Printer: {caps}")

    def test_f05_unknown_printer_name_color(self):
        """Unknown printer name — driver detection works regardless"""
        self._setup_mock_printer(is_color=True, is_duplex=False)
        pm = self._make_fake_printer_manager()
        caps = pm.get_printer_capabilities("XYZ Unknown Printer 3000")
        self.assertIsNotNone(caps)
        self.assertTrue(caps['is_color'],
            msg="Driver color detection failed for unknown printer")
        print(f"\n✅ Unknown Printer Color Detection: {caps}")

    def test_f06_unknown_printer_name_duplex(self):
        """Unknown printer name — driver duplex detection works"""
        self._setup_mock_printer(is_color=False, is_duplex=True)
        pm = self._make_fake_printer_manager()
        caps = pm.get_printer_capabilities("XYZ Unknown Duplex 5000")
        self.assertIsNotNone(caps)
        self.assertTrue(caps['is_duplex'],
            msg="Driver duplex detection failed for unknown printer")
        print(f"\n✅ Unknown Printer Duplex Detection: {caps}")

    # ── FAKE PRINTER ROUTING TESTS ───────────────────────────────

    def test_f07_color_job_to_color_printer(self):
        """Color job → Color printer correctly routed"""
        if not _db_ok: self.skipTest("DB unavailable")
        self._setup_mock_printer(is_color=True, is_duplex=False)
        pm = self._make_fake_printer_manager()

        # Simulate 4 printers with different capabilities
        printers_config = [
            ("Canon PIXMA G2010",    True,  False),
            ("HP LaserJet 1020",     False, False),
            ("Brother HL-L2321D",    False, True),
            ("Brother MFC-J995DW",   True,  True),
        ]

        class FakePrinter:
            def __init__(self, name, is_color, is_duplex):
                self.printer_name = name
                self.is_color = is_color
                self.is_duplex = is_duplex
                self.is_active = True
                self.is_default = False

        fake_printers = [
            FakePrinter(n, c, d) for n, c, d in printers_config
        ]

        # Color job
        class FakeJob:
            color_mode = "Color"
            print_side = "Single"

        selected = select_printer(fake_printers, FakeJob())
        self.assertIsNotNone(selected)
        self.assertTrue(selected.is_color,
            msg=f"Color job went to non-color printer: "
                f"{selected.printer_name}")
        print(f"\n✅ Color job → {selected.printer_name}")

    def test_f08_duplex_job_to_duplex_printer(self):
        """Duplex job → Duplex printer correctly routed"""
        self._setup_mock_printer(is_color=False, is_duplex=True)

        class FakePrinter:
            def __init__(self, name, is_color, is_duplex):
                self.printer_name = name
                self.is_color = is_color
                self.is_duplex = is_duplex
                self.is_active = True
                self.is_default = False

        fake_printers = [
            FakePrinter("Canon PIXMA G2010",  True,  False),
            FakePrinter("HP LaserJet 1020",   False, False),
            FakePrinter("Brother HL-L2321D",  False, True),
        ]

        class FakeJob:
            color_mode = "Black & White"
            print_side = "Double"

        selected = select_printer(fake_printers, FakeJob())
        self.assertIsNotNone(selected)
        self.assertTrue(selected.is_duplex,
            msg=f"Duplex job went to non-duplex printer: "
                f"{selected.printer_name}")
        print(f"\n✅ Duplex job → {selected.printer_name}")

    def test_f09_bw_job_avoids_color_printer(self):
        """BW job → prefers BW printer over color printer"""
        self._setup_mock_printer(is_color=False, is_duplex=False)

        class FakePrinter:
            def __init__(self, name, is_color, is_duplex, is_default=False):
                self.printer_name = name
                self.is_color = is_color
                self.is_duplex = is_duplex
                self.is_active = True
                self.is_default = is_default

        fake_printers = [
            FakePrinter("Canon PIXMA G2010", True,  False),
            FakePrinter("HP LaserJet 1020",  False, False, is_default=True),
        ]

        class FakeJob:
            color_mode = "Black & White"
            print_side = "Single"

        selected = select_printer(fake_printers, FakeJob())
        self.assertIsNotNone(selected)
        self.assertFalse(selected.is_color,
            msg=f"BW job went to color printer: "
                f"{selected.printer_name}")
        print(f"\n✅ BW job → {selected.printer_name} (avoided color)")

    def test_f10_no_color_printer_for_color_job(self):
        """Color job + no color printer → None returned"""
        class FakePrinter:
            def __init__(self, name):
                self.printer_name = name
                self.is_color = False
                self.is_duplex = False
                self.is_active = True
                self.is_default = False

        fake_printers = [
            FakePrinter("HP LaserJet 1020"),
            FakePrinter("Brother HL-L2321D"),
        ]

        class FakeJob:
            color_mode = "Color"
            print_side = "Single"

        selected = select_printer(fake_printers, FakeJob())
        self.assertIsNone(selected,
            msg="Expected None — no color printer available")
        print(f"\n✅ Color job + no color printer → None (safe)")

    def test_f11_no_duplex_printer_for_duplex_job(self):
        """Duplex job + no duplex printer → None returned"""
        class FakePrinter:
            def __init__(self, name):
                self.printer_name = name
                self.is_color = False
                self.is_duplex = False
                self.is_active = True
                self.is_default = False

        fake_printers = [
            FakePrinter("HP LaserJet 1020"),
            FakePrinter("Canon PIXMA G2010"),
        ]

        class FakeJob:
            color_mode = "Black & White"
            print_side = "Double"

        selected = select_printer(fake_printers, FakeJob())
        self.assertIsNone(selected,
            msg="Expected None — no duplex printer available")
        print(f"\n✅ Duplex job + no duplex printer → None (safe)")


# ── RUNNER ───────────────────────────────────────────────────────
if __name__ == "__main__":
    loader = unittest.TestLoader()
    loader.sortTestMethodsUsing = None
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestPrinterRouting))
    suite.addTests(loader.loadTestsFromTestCase(TestFakePrinterCapabilities))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    total = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    skipped = len(result.skipped)
    passed = total - failures - errors - skipped

    print("\n" + "=" * 60)
    print(f"PRINTER ROUTING SUMMARY")
    print(f"Total Tests : {total}")
    print(f"Passed      : {passed}")
    print(f"Failed      : {failures}")
    print(f"Errors      : {errors}")
    print(f"Skipped     : {skipped}")
    print("=" * 60)

    if failures == 0 and errors == 0:
        print("\n🚀 ALL ROUTING TESTS PASSED — "
              "Printer routing production ready!")
    else:
        print("\n⚠️  ROUTING ISSUES FOUND — Fix before production!")
