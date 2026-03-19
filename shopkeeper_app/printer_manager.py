"""
Printer management for shopkeeper application
"""
import win32print
import win32api
import win32ui
import win32con
import win32gui
import pywintypes
import os
import io
import logging
from sqlalchemy.orm import Session
import sys
import subprocess
from pathlib import Path
import threading
import time
from datetime import datetime
import re
import tempfile
import requests
from urllib.parse import urlparse

# Add parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import Printer, SessionLocal
from shared.config import LOG_FILE
from shared.file_processor import generate_nup_pdf, generate_final_print_pdf, parse_page_range
from shared.global_error_handler import (
    global_error_handler, safe_execute, safe_printer_action, 
    safe_database_action, PrinterError
)
from shared.thread_safe_printer_discovery import ThreadSafePrinterManager
from shared.retry_utils import retry_with_backoff, NetworkOperationRetry, CONNECTIVITY_RETRY_CONFIG
from shared.connection_monitor import ConnectionMonitor, ConnectionEvent
from shared.enhanced_network_printing import EnhancedNetworkPrinting
from shared.config import PRINT_CONFIRMATION_TIMEOUT_SECS

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None
from PIL import Image
from PIL import ImageWin

logger = logging.getLogger(__name__)

class PrinterManager:
    def __init__(self):
        self.db = SessionLocal()
        self.current_printer = None
        self.job_status_threads = {}  # job_id -> thread
        self.job_status_callbacks = {}  # job_id -> callback
        self.job_cancel_flags = {}  # job_id -> threading.Event
        self.job_printers = {}  # job_id -> printer_name (Step 1: Track per-job routing)
        
        # Track active jobs for cancellation (Step 1)
        # {job_id: {'printer': str, 'process': subprocess.Popen, 'type': str}}
        self.active_jobs = {}
        
        # Initialize in-memory printer capability registry
        # Maps printer_name -> {"is_color": bool, "is_duplex": bool, "type": str}
        self.printer_capabilities = {}
        self._initialize_printer_capabilities()
        
        # Initialize thread-safe printer discovery
        self.thread_safe_discovery = ThreadSafePrinterManager()
        self.thread_safe_discovery.start_discovery(interval=30)  # Discover every 30 seconds
        
        # Initialize enhanced network printing
        self.enhanced_network_printing = EnhancedNetworkPrinting()
        
        # Initialize connection monitoring
        self.connection_monitor = ConnectionMonitor()
        self.connection_monitor.start_monitoring()
        
        # Add connection event callback
        self.connection_monitor.add_event_callback(self._on_connection_event)
        
        # Startup cleanup: remove stale temp files from previous sessions
        self._cleanup_stale_temp_files()
    
    def _cleanup_stale_temp_files(self):
        """Remove leftover temp print files from previous sessions.
        Runs once at startup. Never raises — cleanup failure is non-fatal."""
        try:
            temp_dir = os.path.join(tempfile.gettempdir(), 'ezprint_downloads')
            if not os.path.isdir(temp_dir):
                return
            
            import time as _time
            now = _time.time()
            stale_threshold = 3600  # 1 hour
            cleaned = 0
            
            for filename in os.listdir(temp_dir):
                filepath = os.path.join(temp_dir, filename)
                try:
                    if os.path.isfile(filepath) and (now - os.path.getmtime(filepath)) > stale_threshold:
                        os.remove(filepath)
                        cleaned += 1
                except Exception:
                    pass  # Skip files that can't be deleted (locked, etc.)
            
            if cleaned > 0:
                logger.info(f"Startup cleanup: removed {cleaned} stale temp file(s) from {temp_dir}")
        except Exception as e:
            logger.warning(f"Startup temp cleanup failed (non-fatal): {e}")
    
    def _ensure_local_file(self, file_path):
        """
        Ensure file is available locally for printing.
        If file_path is a URL, download it to a temporary location.
        If file_path is already local, return it as-is.
        
        Args:
            file_path (str): Either a local file path or a URL
        
        Returns:
            str: Local file path ready for printing
        
        Raises:
            Exception: If download fails or file is not accessible
        """
        # Check if file_path is a URL
        parsed = urlparse(file_path)
        if parsed.scheme in ['http', 'https']:
            # File is hosted in cloud, download it
            logger.info(f"Downloading cloud file: {file_path}")
            
            try:
                # Create temp directory for downloads
                temp_dir = os.path.join(tempfile.gettempdir(), 'ezprint_downloads')
                os.makedirs(temp_dir, exist_ok=True)
                
                # Extract filename from URL or generate one
                url_path = parsed.path
                if '/' in url_path:
                    filename = url_path.split('/')[-1]
                else:
                    filename = f"download_{int(time.time())}.pdf"
                
                # Download file (plain unauthenticated GET for public Cloudinary URLs)
                local_path = os.path.join(temp_dir, filename)
                response = requests.get(file_path, stream=True, timeout=30, headers={})
                response.raise_for_status()
                
                with open(local_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                logger.info(f"Downloaded to: {local_path}")
                return local_path
                
            except Exception as e:
                logger.error(f"Failed to download cloud file: {e}")
                raise Exception(f"Failed to download file from cloud: {str(e)}")
        else:
            # File is local, return as-is
            return file_path
    
    def _initialize_printer_capabilities(self):
        """
        Initialize printer capability registry with manual mapping.
        Maps printer names to their capabilities based on common printer models.
        
        This is a safe, in-memory registry that doesn't modify the database.
        Capabilities are inferred from printer name patterns.
        """
        # Common printer capability mappings based on model names
        # Format: (name_pattern, is_color, is_duplex, type)
        printer_patterns = [
            # HP LaserJet series - Match specific single-side models first
            ("HP LaserJet P1", False, False, "single"),   # Catches P1007, P1008, P1010, etc.
            ("HP 1020", False, False, "single"),
            ("HP 1018", False, False, "single"),
            ("HP 1005", False, False, "single"),
            ("HP 1100", False, False, "single"),
            ("HP 1200", False, False, "single"),
            ("HP 1300", False, False, "single"),
            
            # HP LaserJet series - Explicit Duplex Whitelist
            ("HP LaserJet M402d", False, True, "duplex"),
            ("HP LaserJet P2055", False, True, "duplex"),
            ("HP 2055", False, True, "duplex"),
            ("HP LaserJet Pro MFP M426", False, True, "duplex"),
            ("HP 1320", False, True, "duplex"),
            ("HP 2015", False, True, "duplex"),
            ("HP 2035", False, True, "duplex"),
            ("HP 3015", False, True, "duplex"),
            ("HP 4015", False, True, "duplex"),
            ("HP 4250", False, True, "duplex"),
            ("HP 4350", False, True, "duplex"),
            ("HP 5200", False, True, "duplex"),
            
            # HP LaserJet series - Generic Fallback (Single-side)
            ("HP LaserJet", False, False, "single"),
            
            # HP Color LaserJet series
            ("HP Color LaserJet", True, True, "color"),
            ("HP CP", True, True, "color"),  # Color LaserJet CP series
            ("HP M", True, True, "color"),    # HP Color LaserJet M series
            
            # HP Inkjet series (typically color, some duplex)
            ("HP DeskJet", True, False, "color"),
            ("HP OfficeJet", True, True, "color"),
            ("HP Envy", True, False, "color"),
            ("HP Photosmart", True, False, "color"),
            
            # Canon printers
            ("Canon PIXMA", True, False, "color"),
            ("Canon imageCLASS", False, True, "duplex"),
            ("Canon LBP", False, True, "duplex"),  # Laser Beam Printer
            ("Canon i-SENSYS", False, True, "duplex"),
            
            # Epson printers
            ("Epson Stylus", True, False, "color"),
            ("Epson WorkForce", True, True, "color"),
            ("Epson Expression", True, False, "color"),
            ("Epson EcoTank", True, False, "color"),
            
            # Brother printers
            ("Brother HL", False, True, "duplex"),  # Laser series
            ("Brother MFC", True, True, "color"),   # Multi-Function Color
            ("Brother DCP", True, False, "color"),  # Desktop Color Printer
            
            # Samsung printers
            ("Samsung ML", False, True, "duplex"),  # Mono Laser
            ("Samsung CLP", True, True, "color"),   # Color Laser Printer
            ("Samsung Xpress", False, True, "duplex"),
            
            # Xerox printers
            ("Xerox Phaser", True, True, "color"),
            ("Xerox WorkCentre", True, True, "color"),
            
            # Lexmark printers
            ("Lexmark E", False, True, "duplex"),   # E series (mono)
            ("Lexmark C", True, True, "color"),     # C series (color)
            ("Lexmark X", True, True, "color"),     # X series (color)
            
            # Generic patterns (fallback)
            ("Color", True, False, "color"),
            ("Laser", False, True, "duplex"),
        ]
        
        # Note: The registry will be populated dynamically when printers are discovered
        # This initialization sets up the pattern matching rules
        self._printer_patterns = printer_patterns
        logger.info(f"Initialized printer capability registry with {len(printer_patterns)} patterns")
    
    def _infer_printer_capabilities(self, printer_name):
        """
        Infer printer capabilities from printer driver/name.
        
        Args:
            printer_name (str): Name of the printer
            
        Returns:
            dict: Capability dict with keys: is_color, is_duplex, type
                  Returns None if capabilities cannot be inferred
        """
        if not printer_name:
            return None
        
        # 1. DRIVER-BASED COLOR DETECTION (Authoritative Source)
        # Attempt to detect color support using authoritative Windows driver flags
        driver_is_color = None
        h = None
        try:
            h = win32print.OpenPrinter(printer_name)
            # PRINTER_INFO_2 (level 2) contains common driver info and default devmode
            info = win32print.GetPrinter(h, 2)
            devmode = info.get('pDevMode')
            
            # Method A: Check DEVMODE setting (DMCOLOR_COLOR = 2)
            if devmode and hasattr(devmode, 'Color'):
                if devmode.Color == win32con.DMCOLOR_COLOR:
                    driver_is_color = True
            
            # Method B: Query hardware capability directly via DeviceCapabilities
            if driver_is_color is None:
                # DC_COLORDEVICE (32) returns 1 if device supports color
                res = win32print.DeviceCapabilities(printer_name, info.get('pPortName', ''), win32con.DC_COLORDEVICE, None, None)
                if res > 0:
                    driver_is_color = True
                else:
                    driver_is_color = False
                    
            if driver_is_color is not None:
                logger.info(f"Driver-based color detection for '{printer_name}': {driver_is_color}")
        except Exception as e:
            logger.debug(f"Driver color check failed for '{printer_name}': {e}. Falling back to heuristics.")
        finally:
            if h:
                try:
                    win32print.ClosePrinter(h)
                except:
                    pass

        # ─── Driver-based duplex detection ───
        # DC_DUPLEX (7) returns > 0 if the printer supports duplex.
        # This is the AUTHORITATIVE source; the pattern-based result is
        # used ONLY when the driver call fails (driver_is_duplex stays None).
        driver_is_duplex = None
        h_duplex = None
        try:
            h_duplex = win32print.OpenPrinter(printer_name)
            info_duplex = win32print.GetPrinter(h_duplex, 2)
            port_name = info_duplex.get('pPortName', '')
            res_duplex = win32print.DeviceCapabilities(
                printer_name, port_name, 7, None, None
            )  # 7 = DC_DUPLEX
            if res_duplex > 0:
                driver_is_duplex = True
            else:
                driver_is_duplex = False
            logger.info(f"Driver-based duplex detection for '{printer_name}': {driver_is_duplex}")
        except Exception as e:
            logger.debug(f"Driver duplex check failed for '{printer_name}': {e}. Falling back to heuristics.")
        finally:
            if h_duplex:
                try:
                    win32print.ClosePrinter(h_duplex)
                except:
                    pass

        user_duplex = None
        user_color = None
        try:
            db = SessionLocal()
            printer_record = db.query(Printer).filter(
                Printer.printer_name == printer_name,
                Printer.is_active == True
            ).order_by(Printer.id.desc()).first()
            if printer_record:
                user_duplex = printer_record.duplex_override   # None/True/False
                user_color = printer_record.color_override     # None/True/False
            db.close()
        except Exception as e:
            logger.debug(f"Could not read user overrides for '{printer_name}': {e}")

        # 2. HEURISTIC-BASED DETECTION
        printer_name_upper = printer_name.upper()
        
        # Check against known patterns
        for pattern, is_color, is_duplex, printer_type in self._printer_patterns:
            if pattern.upper() in printer_name_upper:
                return {
                    # Priority: User Override > Driver > Pattern
                    "is_color": user_color if user_color is not None else (driver_is_color if driver_is_color is not None else is_color),
                    "is_duplex": user_duplex if user_duplex is not None else (driver_is_duplex if driver_is_duplex is not None else is_duplex),
                    "type": printer_type
                }
        
        # Default fallback
        return {
            "is_color": user_color if user_color is not None else (driver_is_color if driver_is_color is not None else False),
            "is_duplex": user_duplex if user_duplex is not None else (driver_is_duplex if driver_is_duplex is not None else False),
            "type": "single"
        }
    
    def get_printer_capabilities(self, printer_name):
        """
        Get printer capabilities from the registry.
        
        Args:
            printer_name (str): Name of the printer
            
        Returns:
            dict: Capability dict with keys: is_color, is_duplex, type
                  Returns None if printer not in registry
        """
        # Check if already in registry
        if printer_name in self.printer_capabilities:
            return self.printer_capabilities[printer_name]
        
        # If not in registry, try to infer capabilities
        capabilities = self._infer_printer_capabilities(printer_name)
        if capabilities:
            # Store in registry for future lookups
            self.printer_capabilities[printer_name] = capabilities
            logger.debug(f"Inferred and cached capabilities for '{printer_name}': {capabilities}")
        
        return capabilities
    
    def get_authorized_printers(self):
        """
        FIX 1: AUTHORITATIVE PRINTER SOURCE (CRITICAL)
        Returns list of printers that are both physically discovered AND marked as active in DB.
        This represents the 'Physical printers ∩ Dashboard active printers' requirement.
        """
        try:
            # 1. Get ALL physically discovered printers (normalized/deduplicated)
            # Use cached discovery to avoid UI thread blocking
            physical_printers = self.get_available_printers()
            
            # 2. Get ONLY active printers from Dashboard DB
            self.db.expire_all() # Ensure fresh read
            db_active_printers = self.db.query(Printer).filter(Printer.is_active == True).all()
            
            # Use set for O(1) matching. Normalize to upper case for robustness.
            # printer_name in DB represents the user's connected canonical name
            db_active_names = {p.printer_name.upper() for p in db_active_printers}
            
            # 3. Intersection: Keep only physical printers present in authorized list
            authorized = []
            for p in physical_printers:
                if p.get('name', '').upper() in db_active_names:
                    authorized.append(p)
            
            return authorized
        except Exception as e:
            logger.error(f"Error getting authorized printers: {e}")
            return []

    def select_printer_for_job(self, job, available_printers: list[str] = None):
        """
        Pure routing decision function - selects the best printer for a job based on capabilities.
        
        FIX 2: ROUTING MUST RESPECT AUTHORIZATION
        Routing candidates = Authorized printers only (Physical ∩ Dashboard DB)
        
        Args:
            job: PrintJob object with print_side and color_mode attributes
            available_printers: Ignored (now uses authoritative get_authorized_printers)
            
        Returns:
            tuple: (selected_printer_name: str | None, error_message: str | None)
        """
        # AUTHORITATIVE SOURCE: Only use printers explicitly connected in dashboard
        authorized_printers_raw = self.get_authorized_printers()
        candidates = [p.get('name') for p in authorized_printers_raw if p.get('name')]
        
        if not candidates:
            return (None, "Printer is not connected. Please connect printer.")
        
        if not job:
            return (None, "Invalid job object")
        
        # Extract job requirements
        print_side = getattr(job, 'print_side', 'Single') or 'Single'
        color_mode = getattr(job, 'color_mode', 'Black & White') or 'Black & White'
        
        # Normalize values (handle case variations)
        print_side = print_side.strip()
        if print_side.lower() in ['double', 'duplex']:
            print_side = 'Double'
        else:
            print_side = 'Single'
        
        color_mode = color_mode.strip()
        if color_mode.lower().startswith('color'):
            color_mode = 'Color'
        else:
            color_mode = 'Black & White'
        
        # Step 1: Filter by color_mode requirement
        color_filtered = []
        
        for printer_name in candidates:
            capabilities = self.get_printer_capabilities(printer_name)
            if not capabilities:
                # If capabilities unknown, include it (will be filtered later if needed)
                color_filtered.append((printer_name, capabilities))
                continue
            
            is_color = capabilities.get('is_color', False)
            
            if color_mode == 'Color':
                # Color job: only include color printers
                if is_color:
                    color_filtered.append((printer_name, capabilities))
            else:
                # Black & White job: include all printers (preference handled later)
                color_filtered.append((printer_name, capabilities))
        
        if color_mode == 'Color' and not color_filtered:
            return (None, "Color printer is not connected. Please connect color printer.")
        
        # For B&W jobs, prefer non-color printers
        if color_mode == 'Black & White':
            bw_preferred = [
                (name, caps) for name, caps in color_filtered
                if caps and not caps.get('is_color', False)
            ]
            # Use preferred list if available, otherwise use all
            if bw_preferred:
                color_filtered = bw_preferred
        
        # Step 2: Apply print_side rules to color-filtered printers
        if print_side == 'Double':
            # Double-sided job: must have duplex capability
            duplex_candidates = [
                (name, caps) for name, caps in color_filtered
                if caps and caps.get('is_duplex', False)
            ]
            
            if not duplex_candidates:
                return (None, "Duplex printer is not connected. Please connect duplex printer.")
            
            # Select first available duplex printer
            selected_name, _ = duplex_candidates[0]
            return (selected_name, None)
        
        else:  # print_side == 'Single'
            # Single-sided job: prefer non-duplex, fallback to duplex
            non_duplex_candidates = [
                (name, caps) for name, caps in color_filtered
                if caps and not caps.get('is_duplex', False)
            ]
            
            if non_duplex_candidates:
                # Prefer non-duplex printer
                selected_name, _ = non_duplex_candidates[0]
                return (selected_name, None)
            else:
                # Fallback to duplex printer (can print single-sided)
                if color_filtered:
                    selected_name, _ = color_filtered[0]
                    return (selected_name, None)
                else:
                    return (None, "No suitable printer found")
    
    @safe_printer_action("GET_AVAILABLE_PRINTERS")
    def get_available_printers(self):
        """
        Get list of available printers using thread-safe discovery with
        physical identity deduplication and status merge rules (STEP 3).
        """
        try:
            # Use thread-safe discovery to get printers
            # FIX 4: ZERO UI FREEZE GUARANTEE - Avoid force_refresh on UI thread
            printers = self.thread_safe_discovery.get_available_printers()
            # Removed fallback code that called force_refresh()
                
            return self._deduplicate_printers(printers)
        except Exception as e:
            logger.error(f"Error in get_available_printers: {e}")
            return []

    def _deduplicate_printers(self, printers):
        """
        Deduplicate and merge printer statuses with physical identity checks (STEP 3).
        Follows 'Physical Identity Deduplication Layer' requirements.
        """
        if not printers:
            return []

        # LOCAL HELPER: Normalize Printer Names as per Requirement 1
        def normalize_printer_name(name, driver_name=""):
            if not name:
                return driver_name or "Unknown Printer"
            
            # Strip "(Copy X)"
            norm = re.sub(r'\(Copy\s+\d+\)', '', name, flags=re.IGNORECASE).strip()
            # Strip " Class Driver"
            norm = norm.replace(' Class Driver', '').strip()
            # Strip port suffixes (:9100, :631, :515, etc.)
            norm = re.sub(r':(9100|631|515|port\d+|ipp|raw|lpd|np)$', '', norm, flags=re.IGNORECASE).strip()

            # Vendor Preference: If driver_name has vendor but name doesn't, prefer driver
            vendors = ['CANON', 'HP', 'HEWLETT-PACKARD', 'EPSON', 'BROTHER', 'SAMSUNG', 'LEXMARK', 'XEROX', 'RICOH', 'ZEBRA', 'KONICA', 'KYOCERA']
            u_name = norm.upper()
            u_driver = (driver_name or "").upper()
            
            has_vendor_in_name = any(v in u_name for v in vendors)
            has_vendor_in_driver = any(v in u_driver for v in vendors)
            
            # If driver has vendor and current name is generic or missing vendor, use driver_name
            if has_vendor_in_driver and not has_vendor_in_name:
                # But only if driver name is not purely generic itself
                if not any(x in u_driver for x in ['CLASS DRIVER', 'GENERIC']):
                    # Clean the driver_name too before returning
                    clean_driver = re.sub(r'\(Copy\s+\d+\)', '', driver_name, flags=re.IGNORECASE).strip()
                    clean_driver = clean_driver.replace(' Class Driver', '').strip()
                    return clean_driver
            
            return norm

        # Virtual Filtering
        virtual_names = ["MICROSOFT PRINT TO PDF", "XPS DOCUMENT WRITER", "ONENOTE", "FAX", "ROOT PRINT QUEUE"]
        
        # Identity Map: {identity_key: [list of entries]}
        physical_groups = {}
        
        # 2. Determine Physical Identity Key (Priority-based deduplication STEP 5)
        # Priority 1: Spooler Name
        # Priority 2: IP Address
        for p in printers:
            raw_name = p.get('name') or ''
            driver_name = p.get('driver_name') or ''
            
            # Filter Virtual Printers
            if any(v in raw_name.upper() for v in virtual_names):
                continue
            
            norm_name = normalize_printer_name(raw_name, driver_name)
            ip = p.get('ip_address')
            info_source = (p.get('discovery_method') or '').lower()
            is_spooler = 'spooler' in info_source or 'win32' in info_source or 'levels' in info_source
            
            # Identify physical printer group
            # If it has an IP, group by IP (highly likely same physical device)
            # If no IP (USB), group by Normalized Name
            if ip:
                group_key = f"IP:{ip}"
            else:
                group_key = f"NAME:{norm_name.upper()}"
            
            if group_key not in physical_groups:
                physical_groups[group_key] = []
            physical_groups[group_key].append({
                'raw': p,
                'norm_name': norm_name,
                'is_spooler': is_spooler
            })

        merged_results = []
        
        for key, group in physical_groups.items():
            if not group:
                continue
            
            # Pick canonical entry (Priority: Spooler Entry > Network Discovery Result)
            # If multiple spooler entries (e.g. same IP but different queues), pick the one with better name
            def get_pref_score(entry):
                score = 0
                if entry['is_spooler']: score += 100
                if "NETWORK PRINTER" not in entry['norm_name'].upper(): score += 50
                # discovery method specificity
                method = (entry['raw'].get('discovery_method') or '').lower()
                if 'wsd' in method: score += 10
                if 'ipp' in method: score += 5
                return score

            sorted_entries = sorted(group, key=get_pref_score, reverse=True)
            canonical_entry = sorted_entries[0]
            
            # Start with a copy of canonical raw data
            final_printer = canonical_entry['raw'].copy()
            final_printer['name'] = canonical_entry['raw'].get(
                'name', canonical_entry['norm_name']
            )  # Original Windows spooler name — required for all API calls
            final_printer['display_name'] = canonical_entry['norm_name']
            # display_name = normalized name for UI only
            # name         = exact Windows-registered name for win32/SumatraPDF

            # 4. Status Resolution (STEP 3 Refined)
            # Merged status: Online if ANY entry in group is Online
            any_online = any(e['raw'].get('status') == 'Online' for e in group)
            any_verified = any(e['raw'].get('connection_verified') is True for e in group)
            
            final_printer['status'] = "Online" if any_online else "Offline"
            final_printer['connection_verified'] = any_verified
            
            # 5. Connection Type Preference: USB > WiFi/Ethernet > Unknown
            conns = [e['raw'].get('connection_type') for e in group]
            if 'USB' in conns:
                final_printer['connection_type'] = 'USB'
            elif any(c in ['WiFi/Ethernet', 'Network', 'Internet'] for c in conns):
                final_printer['connection_type'] = 'WiFi/Ethernet'
            else:
                final_printer['connection_type'] = final_printer.get('connection_type') or 'Unknown'

            # Ensure we have the IP if any entry in group had it
            ips = [e['raw'].get('ip_address') for e in group if e['raw'].get('ip_address')]
            if ips:
                final_printer['ip_address'] = ips[0]

            merged_results.append(final_printer)

        return merged_results
    
    def _on_connection_event(self, event: ConnectionEvent):
        """Handle connection events from the connection monitor"""
        try:
            logger.info(f"Connection event: {event.event_type} - {event.printer_name} - {event.message}")
            
            # Update printer status in database if needed
            if event.event_type in ['connected', 'disconnected', 'reconnected']:
                self._update_printer_status_in_db(event.printer_name, event.event_type == 'connected')
                
        except Exception as e:
            logger.error(f"Error handling connection event: {e}")
    
    def _update_printer_status_in_db(self, printer_name: str, is_online: bool):
        """Update printer status in database"""
        try:
            printer = self.db.query(Printer).filter(Printer.printer_name == printer_name).first()
            if printer:
                printer.is_active = is_online
                self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error updating printer status in DB: {e}")
    
    def cleanup(self):
        """Cleanup printer manager resources"""
        try:
            if hasattr(self, 'thread_safe_discovery'):
                self.thread_safe_discovery.stop_discovery()
            if hasattr(self, 'connection_monitor'):
                self.connection_monitor.stop_monitoring()
            logger.info("Printer manager cleanup completed")
        except Exception as e:
            logger.error(f"Error during printer manager cleanup: {e}")
    
    def reinitialize_printer(self):
        try:
            logger.info("Reinitializing printer connection...")
            self.refresh_printer_discovery()
            logger.info("Printer reinitialized successfully")
        except Exception as e:
            logger.error(f"Printer reinitialize failed: {e}")

    def set_default_printer(self, shop_id, printer_name):
        """
        Set default printer for shop
        
        Args:
            shop_id (str): Shop identifier
            printer_name (str): Printer name
        """
        try:
            # Remove existing default printer
            self.db.query(Printer).filter(
                Printer.shop_id == shop_id,
                Printer.is_default == True
            ).update({'is_default': False})
            
            # Check if printer already exists
            existing_printer = self.db.query(Printer).filter(
                Printer.shop_id == shop_id,
                Printer.printer_name == printer_name
            ).first()
            
            if existing_printer:
                existing_printer.is_default = True
                existing_printer.is_active = True
            else:
                # Create new printer entry
                printer = Printer(
                    shop_id=shop_id,
                    printer_name=printer_name,
                    printer_id=printer_name,
                    is_default=True,
                    is_active=True
                )
                self.db.add(printer)
            
            self.db.commit()
            self.current_printer = printer_name
            
            logger.info(f"Default printer set for shop {shop_id}: {printer_name}")
            return True, "Printer set successfully"
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error setting printer: {e}")
            return False, f"Error setting printer: {str(e)}"
    
    def get_default_printer(self, shop_id):
        """Get default printer for shop"""
        try:
            printer = self.db.query(Printer).filter(
                Printer.shop_id == shop_id,
                Printer.is_default == True,
                Printer.is_active == True
            ).first()
            
            if printer:
                return printer.printer_name
            return None
            
        except Exception as e:
            logger.error(f"Error getting default printer: {e}")
            return None
    
    def print_document(self, file_path, copies=1, page_range=None):
        """
        Print document using default printer (legacy API)
        
        Args:
            file_path (str): Path to file to print (local or cloud URL)
            copies (int): Number of copies
            page_range (str): Page range (e.g., "1-3")
        """
        try:
            if not self.current_printer:
                return False, "No printer selected"
            
            # Download cloud file if needed
            try:
                file_path = self._ensure_local_file(file_path)
            except Exception as e:
                return False, f"Failed to prepare file: {str(e)}"
            
            if not os.path.exists(file_path):
                return False, "File not found"
            
            # Legacy path used ShellExecute which can trigger dialogs. Keep for fallback only.
            win32print.SetDefaultPrinter(self.current_printer)
            win32api.ShellExecute(0, "print", file_path, f'/d:"{self.current_printer}"', ".", 0)
            logger.info(f"Legacy print dispatched (ShellExecute): {file_path} on {self.current_printer}")
            return True, "Document sent to printer (legacy)"
            
        except Exception as e:
            logger.error(f"Error printing document: {e}")
            return False, f"Print error: {str(e)}"

    @safe_printer_action("PRINT_DOCUMENT_WITH_SETTINGS")
    def print_document_with_settings(self, file_path, file_type, settings, job_id=None):
        """
        Silent, production-ready printing applying customization settings.
        Attempts SumatraPDF for PDFs; otherwise falls back to GDI image printing.
        
        settings keys: copies, page_range, page_size, orientation, print_side, color_mode, layout_pages
        """
        # ===== PRINTER ROUTING INTEGRATION =====
        # Determine target printer for this job (routing or manual override)
        target_printer = None
        manual_override = settings.get('manual_printer_selected', False)
        
        if not manual_override:
            # Auto-routing: Use routing function to select best printer
            try:
                # Create a minimal job-like object from settings for routing
                class _JobWrapper:
                    def __init__(self, settings_dict):
                        self.print_side = settings_dict.get('print_side', 'Single') or 'Single'
                        self.color_mode = settings_dict.get('color_mode', 'Black & White') or 'Black & White'
                        self.manual_printer_selected = False
                
                job_wrapper = _JobWrapper(settings)
                
                # Get authorized printers (list of dicts with 'name' key)
                # FIX 1: AUTHORITATIVE PRINTER SOURCE (CRITICAL)
                available_printers_raw = self.get_authorized_printers()
                available_printers = [p.get('name') for p in available_printers_raw if p.get('name')]
                
                # Pure routing call (now strictly enforces authorization)
                # FIX 2: ROUTING MUST RESPECT AUTHORIZATION
                selected_printer, error_message = self.select_printer_for_job(job_wrapper)
                
                if error_message is not None:
                    # Routing error: do not print (must block Duplex/Color errors)
                    logger.warning(f"Printer routing failed: {error_message}")
                    try:
                        if job_id and job_id in self.job_status_callbacks:
                            self.job_status_callbacks[job_id](job_id, 'Failed', 0, error_message)
                    except Exception:
                        pass
                    return False, error_message
                
                if selected_printer is None:
                    # Safe fallback only if no error returned
                    target_printer = self.current_printer
                    logger.warning("Routing yielded no printer selection - fallback to current_printer")
                else:
                    target_printer = selected_printer
                    logger.info(f"Routing selected printer: {target_printer}")
            except Exception as e:
                # Routing error - fallback to current_printer for backward compatibility
                logger.warning(f"Routing exception (fallback to current_printer): {e}")
                target_printer = self.current_printer
        else:
            # Manual override: Use current_printer as before
            target_printer = self.current_printer
            logger.info("Manual printer selection - using current_printer")
        
        # Fallback: If no target_printer determined, use current_printer
        # Update tracked printer for this job (Requirement: Poller must use correct spooler)
        if job_id:
            self.job_printers[job_id] = target_printer
            logger.info(f"Job {job_id} assigned to printer: {target_printer}")

        if not target_printer:
            # Fail explicitly when no printer is selected; do NOT mark completed
            logger.warning("No printer selected; cannot print")
            try:
                if job_id and job_id in self.job_status_callbacks:
                    self.job_status_callbacks[job_id](job_id, 'Failed', 0, 'No printer selected')
            except Exception:
                pass
            return False, "No printer selected"

        # Preflight: ensure the target printer is usable; if not, skip
        try:
            h = win32print.OpenPrinter(target_printer)
            try:
                info = win32print.GetPrinter(h, 2)
            finally:
                win32print.ClosePrinter(h)
        except Exception as e:
            logger.warning(f"Target printer not usable; failing print: {e}")
            try:
                if job_id and job_id in self.job_status_callbacks:
                    self.job_status_callbacks[job_id](job_id, 'Failed', 0, f'Printer not usable: {e}')
            except Exception:
                pass
            return False, "Printer not usable"

        # If printer is reported offline/errored, skip in CI/test environments
        try:
            status = info.get('Status') or 0
            if not self._is_status_online(status):
                logger.warning("Target printer appears offline; failing print")
                try:
                    if job_id and job_id in self.job_status_callbacks:
                        self.job_status_callbacks[job_id](job_id, 'Failed', 0, 'Printer offline')
                except Exception:
                    pass
                return False, "Printer offline"
        except Exception:
            pass

        # Skip virtual/printers that require UI prompts in headless test env
        try:
            port_name = (info.get('pPortName') or '').upper()
            printer_name_upper = (target_printer or '').upper()
            virtual_indicators = [
                'PORTPROMPT',  # Microsoft Print to PDF
                'FILE:',       # File ports require UI/file path
            ]
            name_indicators = [
                'MICROSOFT PRINT TO PDF', 'XPS DOCUMENT WRITER', 'ONENOTE', 'FAX'
            ]
            if any(ind in port_name for ind in virtual_indicators) or any(ind in printer_name_upper for ind in name_indicators):
                logger.warning("Detected virtual/UI printer; failing print to avoid silent skip")
                try:
                    if job_id and job_id in self.job_status_callbacks:
                        self.job_status_callbacks[job_id](job_id, 'Failed', 0, 'Virtual/UI printer not supported')
                except Exception:
                    pass
                return False, "Virtual/UI printer not supported"
        except Exception:
            pass
        
        
        # CLOUD FILE SUPPORT: Download cloud-hosted files to local temp directory
        # This ensures backward compatibility - all printing logic expects local files
        _temp_download_path = None  # Track for cleanup
        _temp_final_pdf_path = None  # Track for cleanup
        original_file_path = file_path  # Remember original to detect downloads
        try:
            file_path = self._ensure_local_file(file_path)
            if file_path != original_file_path:
                _temp_download_path = file_path  # Mark for cleanup after printing
        except Exception as e:
            error_msg = f"Failed to prepare file for printing: {str(e)}"
            logger.error(error_msg)
            try:
                if job_id and job_id in self.job_status_callbacks:
                    self.job_status_callbacks[job_id](job_id, 'Failed', 0, error_msg)
            except Exception:
                pass
            return False, error_msg
        
        # Enhanced file validation with detailed logging
        logger.info(f"Attempting to print file: {file_path}")
        if not os.path.exists(file_path):
            error_msg = f"File not found: {file_path}"
            logger.error(error_msg)
            raise PrinterError(error_msg)
        
        # Log file details for debugging
        try:
            file_size = os.path.getsize(file_path)
            logger.info(f"File details - Path: {file_path}, Size: {file_size} bytes, Type: {file_type}")
        except Exception as e:
            logger.warning(f"Could not get file details: {e}")

        # CRITICAL FIX: Generate final print-ready PDF that matches preview exactly
        # Preview and print must share the same render output
        layout_pages = int(settings.get('layout_pages') or 1)
        color_mode = settings.get('color_mode') or 'Color'
        page_size = settings.get('page_size') or 'A4'
        orientation = settings.get('orientation') or 'Portrait'
        page_range = (settings.get('page_range') or '').strip()
        copies = int(settings.get('copies') or 1)
        print_side = settings.get('print_side') or 'Single'

        try:
            # Use generate_final_print_pdf() to ensure preview-print matching
            # This function processes ALL selected pages, applies page range, layout, etc.
            nup_path = generate_final_print_pdf(
                file_path, 
                file_type, 
                page_size=page_size, 
                orientation=orientation, 
                layout_pages=layout_pages, 
                color_mode=color_mode,
                page_range=page_range
            )
            
            # CRITICAL FIX: If a new PDF was generated, it already has the page range applied.
            # We must NOT pass the page range again to Sumatra or GDI, as that would be 
            # relative to the new (subset) PDF and lead to "No pages resolved" failures.
            effective_page_range = None if nup_path != file_path else page_range
            
            # Track generated PDF for cleanup after printing
            if nup_path != file_path:
                _temp_final_pdf_path = nup_path
            
            # Update file_type if document was converted to PDF
            if nup_path != file_path and nup_path.lower().endswith('.pdf'):
                logger.info(f"Document processed/converted to PDF for printing: {nup_path}")
                file_type = 'pdf'
            
            logger.info(f"Print pipeline: Using file={nup_path}, type={file_type}, effective_range={effective_page_range}")
                
        except ValueError as e:
            # Page range validation failed (e.g., page 2 requested but document has only 1 page)
            error_msg = f"Page range validation failed: {str(e)}"
            logger.error(error_msg)
            try:
                if job_id and job_id in self.job_status_callbacks:
                    self.job_status_callbacks[job_id](job_id, 'Failed', 0, error_msg)
            except Exception:
                pass
            return False, error_msg
        except Exception as e:
            error_msg = f"Failed to generate final print PDF: {str(e)}"
            logger.error(error_msg)
            raise PrinterError(error_msg)

        # Handle WiFi/network printers using the processed PDF
        if self._is_network_printer(target_printer):
            # Update settings with effective values for network printer
            network_settings = settings.copy()
            network_settings['page_range'] = effective_page_range
            return self._print_to_network_printer(nup_path, file_type, network_settings, job_id, printer_name=target_printer)

        # Try SumatraPDF for PDFs (best silent printing experience)
        if nup_path.lower().endswith('.pdf'):
            sumatra = self._find_sumatra_pdf()
            if sumatra and os.path.exists(sumatra):
                try:
                    if job_id:
                        self.active_jobs[job_id] = {
                            'printer': target_printer,
                            'type': 'sumatra',
                            'process': None
                        }
                    
                    # Run printing in a background thread to avoid UI freeze
                    result_holder = {'ok': False, 'msg': ''}
                    def _run_sumatra():
                        ok, msg = self._print_with_sumatra(sumatra, nup_path, copies, effective_page_range, orientation, print_side, color_mode, printer_name=target_printer, job_id=job_id)
                        result_holder['ok'] = ok
                        result_holder['msg'] = msg
                    t = threading.Thread(target=_run_sumatra, name="Print-Sumatra", daemon=True)
                    t.start()
                    t.join(timeout=30)  # initial wait — 30s for real shop conditions

                    if t.is_alive():
                        # Sumatra is still running (large PDF / slow network printer)
                        # Do NOT start GDI — that would cause a double-print
                        logger.info("SumatraPDF still running after 30s, waiting up to 60s more…")
                        t.join(timeout=60)  # extended wait

                        if result_holder['ok']:
                            return True, result_holder['msg']

                        if t.is_alive():
                            # Sumatra is *still* running after 90s total — let it finish
                            # in the background (daemon thread) but do NOT layer GDI on top.
                            logger.warning(
                                "SumatraPDF still alive after 90s total; "
                                "skipping GDI fallback to avoid double-print"
                            )
                            return False, "SumatraPDF printing timed out (90s)"

                        # Thread finished during extended wait but reported failure
                        logger.warning(f"SumatraPDF failed after extended wait: {result_holder['msg']}")
                        # Fall through to GDI below

                    elif result_holder['ok']:
                        # Finished within initial 30s and succeeded
                        return True, result_holder['msg']
                    else:
                        # Finished within 30s but reported failure — fall through to GDI
                        logger.warning(f"SumatraPDF finished but failed: {result_holder['msg']}")
                except Exception as e:
                    logger.warning(f"SumatraPDF printing failed, falling back to GDI: {e}")

        # Fallback: rasterize and print via GDI
        try:
            if job_id:
                self.active_jobs[job_id] = {
                    'printer': target_printer,
                    'type': 'gdi',
                    'process': None
                }

            # Move heavy GDI rendering to background thread as well
            result_holder = {'ok': False, 'msg': ''}
            def _run_gdi():
                ok, msg = self._print_via_gdi_images(nup_path, file_type, copies, effective_page_range, page_size, orientation, color_mode, job_id=job_id, printer_name=target_printer, print_side=print_side)
                result_holder['ok'] = ok
                result_holder['msg'] = msg
            t = threading.Thread(target=_run_gdi, name="Print-GDI", daemon=True)
            t.start()
            t.join(timeout=20)
            
            # Cleanup metadata after handoff
            if job_id and job_id in self.active_jobs:
                del self.active_jobs[job_id]
                
            return result_holder['ok'], result_holder['msg']
        except Exception as e:
            error_msg = f"GDI printing failed: {str(e)}"
            logger.error(error_msg)
            raise PrinterError(error_msg)
        finally:
            # Cleanup temp files from cloud downloads and generated PDFs
            for temp_path in (_temp_download_path, _temp_final_pdf_path):
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                        logger.debug(f"Cleaned up temp file: {temp_path}")
                    except Exception as cleanup_err:
                        logger.warning(f"Failed to clean up temp file {temp_path}: {cleanup_err}")

    def start_job_status_polling(self, job_id, callback):
        """Start polling Windows spooler for job status updates"""
        try:
            if job_id in self.job_status_threads:
                return  # Already polling
            
            def poll_job_status():
                """
                CRITICAL FIX: Poll Windows spooler for actual printer job status.
                Completed status is set ONLY after OS confirms job finished.
                """
                try:
                    # Keep polling in a loop for a bounded time
                    start_time = time.time()
                    timeout_secs = int(PRINT_CONFIRMATION_TIMEOUT_SECS or 180)
                    
                    # CRITICAL FIX: Increased grace period for job to appear in spooler
                    # Job may take 5-15 seconds to appear after print() call
                    job_appear_grace_secs = 30.0
                    
                    # Track job lifecycle
                    job_seen = False  # Has job appeared in spooler at least once?
                    job_last_status = None  # Last known status before job disappeared
                    job_was_printing = False  # Was job ever in Printing state?
                    consecutive_not_found = 0  # Count consecutive polls where job not found
                    max_consecutive_not_found = 3  # Job must be missing for 3 polls before marking Completed
                    offline_retries = 0  # Count offline retry attempts
                    max_offline_retries = 10  # 10 × 30s = 5 min max wait for printer to come back
                    
                    while True:
                        if job_id in self.job_cancel_flags and self.job_cancel_flags[job_id].is_set():
                            logger.info(f"Stopping status polling for job {job_id} (cancelled)")
                            return

                        current_time = time.time()
                        elapsed = current_time - start_time
                        
                        try:
                            # CRITICAL FIX: Determine target printer for polling
                            # Prefer the routed printer for this specific job, fallback to current_printer
                            poll_printer = self.job_printers.get(job_id) or self.current_printer
                            
                            if not poll_printer:
                                # If no printer determined yet, wait within grace period (routing might be in progress)
                                if elapsed <= 10.0:
                                    time.sleep(1.0)
                                    continue
                                else:
                                    logger.warning(f"No printer determined for job {job_id} after 10s")
                                    callback(job_id, 'Error', 0, 'No printer determined for polling')
                                    return

                            try:
                                h = win32print.OpenPrinter(poll_printer)
                            except Exception as e:
                                # Printer unavailable - wait longer before failing
                                if elapsed > 30.0:  # Give printer 30 seconds to become available
                                    logger.warning(f"Printer {poll_printer} unavailable after 30s: {e}")
                                    callback(job_id, 'Failed', 0, f'Printer unavailable: {e}')
                                    return
                                time.sleep(1.0)
                                continue
                            
                            try:
                                h_jobs = win32print.EnumJobs(h, 0, -1, 1)  # Level 1 for basic info
                            finally:
                                win32print.ClosePrinter(h)
                        except Exception as e:
                            # Spooler error - wait longer before failing
                            if elapsed > 30.0:
                                logger.warning(f"Spooler error after 30s: {e}")
                                callback(job_id, 'Failed', 0, f'Spooler error: {e}')
                                return
                            time.sleep(1.0)
                            continue

                        # Look for our job in spooler
                        job_info = None
                        pdf_fallback = None
                        for job_entry in h_jobs:
                            doc_name = job_entry.get('pDocument', '')
                            if job_id and job_id in doc_name:
                                job_info = job_entry
                                break
                            elif doc_name.lower().endswith(".pdf") and pdf_fallback is None:
                                pdf_fallback = job_entry

                        if job_info is None:
                            job_info = pdf_fallback

                        if not job_info:
                            # Job not found in spooler
                            if not job_seen:
                                # Job hasn't appeared yet - wait with grace period
                                if elapsed <= job_appear_grace_secs:
                                    # Still within grace period, keep waiting
                                    time.sleep(1.0)
                                    continue
                                else:
                                    # Job never appeared in spooler
                                    # Commercial printers (Canon ADV series) process jobs
                                    # so fast that job appears and disappears before first poll.
                                    # Check if SumatraPDF returned success for this job.
                                    if job_id in self._sumatra_ok_jobs:
                                        self._sumatra_ok_jobs.discard(job_id)
                                        logger.info(f"Job {job_id} completed (fast commercial printer: job processed before poll window)")
                                        callback(job_id, 'Completed', 100, 'Printed successfully')
                                        return
                                    logger.warning(f"Job {job_id} never appeared in spooler after {elapsed:.1f}s")
                                    callback(job_id, 'Failed', 0, 'Job never appeared in print spooler')
                                    return
                            else:
                                # Job was seen before but now missing - might be completed
                                consecutive_not_found += 1
                                
                                # CRITICAL FIX: Only mark Completed if:
                                # 1. Job was successfully printing/completed before disappearing
                                # 2. Job has been missing for multiple consecutive polls
                                if consecutive_not_found >= max_consecutive_not_found:
                                    if job_was_printing or (job_last_status and job_last_status not in ['Failed', 'Error', 'Offline', 'Paper Out']):
                                        # Job disappeared after successful printing - mark Completed
                                        logger.info(f"Job {job_id} completed - disappeared from spooler after successful printing")
                                        callback(job_id, 'Completed', 100, 'Job completed and removed from spooler')
                                        return
                                    else:
                                        # Job disappeared but was in error state - mark Failed
                                        logger.warning(f"Job {job_id} disappeared but was in error state: {job_last_status}")
                                        callback(job_id, 'Failed', 0, f'Job disappeared in error state: {job_last_status}')
                                        return
                                
                                # Job missing but not enough consecutive misses yet - keep polling
                                time.sleep(1.0)
                                continue
                        else:
                            # Job found in spooler
                            job_seen = True
                            consecutive_not_found = 0  # Reset counter
                            
                            status_flags = job_info.get('Status', 0)
                            pages_printed = job_info.get('PagesPrinted', 0)
                            total_pages = max(1, job_info.get('TotalPages', 1))
                            progress = min(100, int((pages_printed / total_pages) * 100))

                            # CRITICAL FIX: Determine status from actual OS spooler flags
                            # Do NOT mark Completed based on progress alone
                            if status_flags & 0x00000002:  # JOB_STATUS_ERROR
                                status = 'Failed'
                                job_last_status = status
                                callback(job_id, status, progress, f'Printer error - Pages: {pages_printed}/{total_pages}')
                                return  # Error state - stop polling
                            elif status_flags & 0x00000010:  # JOB_STATUS_PRINTING
                                status = 'Printing'
                                job_was_printing = True
                            elif status_flags & 0x00000080:  # JOB_STATUS_OFFLINE
                                status = 'Offline'
                            elif status_flags & 0x00000040:  # JOB_STATUS_PAPER_OUT
                                status = 'Paper Out'
                            elif status_flags & 0x00000004:  # JOB_STATUS_DELETING
                                status = 'Deleting'
                                callback(job_id, status, progress, 'Job being deleted')
                                return
                            elif status_flags & 0x00000001:  # JOB_STATUS_PAUSED
                                status = 'Paused'
                            elif status_flags & 0x00000020:  # JOB_STATUS_OFFLINE (alternate)
                                status = 'Offline'
                            else:
                                # No critical flags - job is queued or processing
                                status = 'In Queue'

                            job_last_status = status
                            callback(job_id, status, progress, f'Pages: {pages_printed}/{total_pages}')

                            # Continue polling to wait for job to finish and disappear
                            if status == 'Failed':
                                # Permanent error — stop polling
                                return
                            elif status == 'Paper Out':
                                # Paper Out — stop polling (handled separately by paper-out banner)
                                return
                            elif status == 'Offline':
                                # Printer went offline mid-job — pause and retry
                                offline_retries += 1
                                if offline_retries > max_offline_retries:
                                    # Exhausted retries (5 min) — mark as Failed
                                    logger.warning(
                                        f"Job {job_id}: printer offline for {offline_retries} retries "
                                        f"({offline_retries * 30}s), marking as Failed"
                                    )
                                    callback(
                                        job_id, 'Failed', progress,
                                        'Printer offline too long — please check printer and reprint'
                                    )
                                    return
                                # Notify shopkeeper and wait for printer to come back
                                callback(
                                    job_id, 'Offline', progress,
                                    f'Printer offline. Waiting for printer to reconnect... '
                                    f'(retry {offline_retries}/{max_offline_retries})'
                                )
                                logger.info(
                                    f"Job {job_id}: printer offline, retry {offline_retries}/{max_offline_retries}, "
                                    f"waiting 30s before re-check"
                                )
                                time.sleep(30)  # Pause before retrying
                                continue  # Resume polling loop
                            else:
                                # Non-error status (Printing, In Queue, Paused) — reset offline counter
                                offline_retries = 0

                        # Timeout check
                        if elapsed > timeout_secs:
                            if job_seen:
                                callback(job_id, 'Failed', progress, f'Timed out after {timeout_secs}s - job still in spooler')
                            else:
                                callback(job_id, 'Failed', 0, f'Timed out after {timeout_secs}s - job never appeared')
                            return

                        time.sleep(0.3)  # Poll every 300ms for fast commercial printers
                        
                    # Final cleanup of thread and callback references
                    if job_id in self.job_status_threads:
                        del self.job_status_threads[job_id]
                    if job_id in self.job_status_callbacks:
                        del self.job_status_callbacks[job_id]
                    if job_id in self.job_printers:
                        del self.job_printers[job_id]
                        
                except Exception as e:
                    logger.error(f"Error polling job status: {e}")
                    callback(job_id, 'Error', 0, str(e))
                    # Cleanup on error too
                    if job_id in self.job_status_threads:
                        del self.job_status_threads[job_id]
                    return
            
            # Start polling thread
            thread = threading.Thread(target=poll_job_status, daemon=True)
            self.job_status_threads[job_id] = thread
            self.job_status_callbacks[job_id] = callback
            thread.start()
            
        except Exception as e:
            logger.error(f"Error starting job status polling: {e}")
            callback(job_id, 'Error', 0, str(e))

    def stop_job_status_polling(self, job_id):
        """Stop polling for a specific job"""
        try:
            if job_id in self.job_status_threads:
                del self.job_status_threads[job_id]
            if job_id in self.job_status_callbacks:
                del self.job_status_callbacks[job_id]
        except Exception as e:
            logger.error(f"Error stopping job status polling: {e}")

    def _find_sumatra_pdf(self):
        """Locate SumatraPDF.exe if installed or bundled."""
        candidates = [
            os.environ.get("SUMATRAPDF_PATH"),
            str(Path(os.getcwd()) / 'SumatraPDF.exe'),
            r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
            r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
        ]
        for c in candidates:
            if c and os.path.exists(c):
                return c
        return None



    def _print_with_sumatra(self, sumatra_path, pdf_path, copies, page_range, orientation, print_side, color_mode, printer_name=None, job_id=None):
        """Use SumatraPDF to print silently with settings."""
        # Use provided printer_name or fallback to self.current_printer
        target_printer = printer_name or self.current_printer
        try:
            # Build print-settings
            opts = []
            if orientation == 'Landscape':
                opts.append('landscape')
            else:
                opts.append('portrait')
            if print_side == 'Double':
                # Default to long-edge duplex; printers may override if unsupported
                opts.append('duplexlong')
            else:
                opts.append('simplex')
            if color_mode == 'Black & White':
                opts.append('monochrome')
            else:
                opts.append('color')
            #if copies and copies > 1:
                #opts.append(f'{copies}x')
            if page_range:
                # Sumatra expects e.g. 1,3-5
                opts.append(f'page-range={page_range}')
            settings_str = ','.join(opts)

            cmd = [
                sumatra_path,
                '-print-to', target_printer,
                '-print-settings', settings_str,
                '-silent',
                '-exit-on-print',
                pdf_path
            ]
            effective_copies = max(1, int(copies or 1))

            for _ in range(effective_copies):

                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=0x08000000
                )

                # Store Popen object for cancellation
                if job_id and hasattr(self, 'active_jobs') and job_id in self.active_jobs:
                    self.active_jobs[job_id]['process'] = proc

                stdout, stderr = proc.communicate()

                if proc.returncode != 0:
                    logger.error(f"SumatraPDF print failed: {stderr.decode(errors='ignore')}")
                    return False, "SumatraPDF print failed"

            # Cleanup after all copies printed
            if job_id and hasattr(self, 'active_jobs') and job_id in self.active_jobs:
                del self.active_jobs[job_id]

            return True, "Document sent to printer"
            
        except Exception as e:
            # Also cleanup on exception
            if job_id and hasattr(self, 'active_jobs') and job_id in self.active_jobs:
                del self.active_jobs[job_id]
            logger.error(f"SumatraPDF printing error: {e}")
            return False, f"SumatraPDF printing error: {e}"

    def _print_via_gdi_images(self, path, file_type, copies, page_range, page_size, orientation, color_mode, job_id=None, printer_name=None, print_side=None):
        """Rasterize content and print via GDI silently."""
        # Use provided printer_name or fallback to self.current_printer
        target_printer = printer_name or self.current_printer
        try:
            # Unified page range parsing with total pages awareness
            total_pdf_pages = 0
            if path.lower().endswith('.pdf') and fitz:
                with fitz.open(path) as doc:
                    total_pdf_pages = len(doc)
            
            images = []
            # Use the shared robust page range parser
            rng = parse_page_range(page_range, total_pdf_pages) if (page_range and total_pdf_pages > 0) else None
            
            if path.lower().endswith('.pdf') and fitz:
                doc = fitz.open(path)
                pages = rng if rng else list(range(1, len(doc) + 1))
                for p in pages:
                    idx = p - 1
                    if idx < 0 or idx >= len(doc):
                        continue
                    page = doc[idx]
                    zoom = 2.0
                    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    images.append(img)
                doc.close()
            elif file_type in ['png','jpg','jpeg','bmp','gif','tiff'] or path.lower().endswith(('.png','.jpg','.jpeg','.bmp','.gif','.tif','.tiff')):
                img = Image.open(path)
                images = [img]
            else:
                # Unsupported for raster fallback
                return False, "Unsupported file type for raster printing"

            # Apply orientation and color
            prepared = []
            for im in images:
                img = im.convert('RGB')
                if color_mode == 'Black & White':
                    img = img.convert('L').convert('RGB')
                if orientation == 'Landscape' and img.width < img.height:
                    img = img.rotate(90, expand=True)
                elif orientation == 'Portrait' and img.width > img.height:
                    img = img.rotate(-90, expand=True)
                prepared.append(img)

            # CRITICAL SAFETY CHECK: Never send empty raster to printer
            # This prevents silent printer stop and false "Completed" status
            if not prepared or len(prepared) == 0:
                error_msg = "No pages to print - page range may be invalid or document is empty"
                logger.error(error_msg)
                return False, error_msg

            # GDI printing
            hDC = win32ui.CreateDC()
            hDC.CreatePrinterDC(target_printer)
            printable_area = hDC.GetDeviceCaps(win32con.HORZRES), hDC.GetDeviceCaps(win32con.VERTRES)
            phys_offset = hDC.GetDeviceCaps(win32con.PHYSICALOFFSETX), hDC.GetDeviceCaps(win32con.PHYSICALOFFSETY)

            # Per-job duplex via ResetDC
            if print_side == "Double":
                dm = pywintypes.DEVMODEType()
                dm.Fields = dm.Fields | 0x00001000  # DM_DUPLEX
                dm.Duplex = win32con.DMDUP_VERTICAL
                win32gui.ResetDC(hDC.GetHandleOutput(), dm)

            # Start document (include job_id to aid cancellation)
            doc_name = f"EzPrint Job" if not job_id else f"EzPrint Job - {job_id}"
            hDC.StartDoc(doc_name)
            for _ in range(max(1, copies)):
                for img in prepared:
                    hDC.StartPage()
                    # Scale image to fit printable area while preserving aspect
                    img_w, img_h = img.size
                    max_w, max_h = printable_area
                    scale = min(float(max_w) / img_w, float(max_h) / img_h)
                    draw_w = int(img_w * scale)
                    draw_h = int(img_h * scale)

                    # Center on page
                    x = (max_w - draw_w) // 2
                    y = (max_h - draw_h) // 2

                    # Resize via PIL and draw using ImageWin.Dib to avoid SetBitmapBits
                    resized = img.resize((draw_w, draw_h), Image.Resampling.LANCZOS)
                    dib = ImageWin.Dib(resized)
                    dib.draw(hDC.GetHandleOutput(), (x, y, x + draw_w, y + draw_h))
                    hDC.EndPage()
            hDC.EndDoc()
            hDC.DeleteDC()

            return True, "Document sent to printer"
        except Exception as e:
            logger.error(f"GDI printing error: {e}")
            return False, f"GDI printing error: {e}"

    def cancel_job(self, job_id):
        """
        Attempt to cancel a queued/printing job via Windows spooler and subprocess termination.
        Returns: (success: bool, message: str) (FIX 5)
        """
        try:
            success = False
            msg_parts = []
            
            # 0. Set cancel flag to stop polling immediately (Thread safety)
            if job_id not in self.job_cancel_flags:
                self.job_cancel_flags[job_id] = threading.Event()
            self.job_cancel_flags[job_id].set()

            # 1. Process Termination (Strict Sumatra Fix - FIX 4)
            if job_id in self.active_jobs:
                job_info = self.active_jobs[job_id]
                proc = job_info.get('process')
                if proc and proc.poll() is None:
                    try:
                        proc.terminate()
                        success = True
                        msg_parts.append("Terminated print process")
                    except Exception as e:
                        logger.warning(f"Failed to terminate process for {job_id}: {e}")

            # 2. Spooler Cancellation (Hardware consistency - FIX 3)
            # Check the specific printer used for this job, or fallback to current
            target_printer = self.active_jobs.get(job_id, {}).get('printer') or self.current_printer
            if target_printer:
                try:
                    h = win32print.OpenPrinter(target_printer)
                    try:
                        jobs = win32print.EnumJobs(h, 0, -1, 1)
                        for j in jobs:
                            doc = j.get('pDocument') or ''
                            # Match by ID or EzPrint tag
                            if (job_id and f"EzPrint Job - {job_id}" in doc) or (not job_id and 'EzPrint Job' in doc):
                                try:
                                    win32print.SetJob(h, j['JobId'], 0, None, win32print.JOB_CONTROL_CANCEL)
                                    success = True
                                    msg_parts.append("Removed from Windows Spooler")
                                except Exception as e:
                                    logger.warning(f"SetJob CANCEL failed for {j['JobId']}: {e}")
                    finally:
                        win32print.ClosePrinter(h)
                except Exception as e:
                    logger.error(f"Spooler lookup failed for {target_printer}: {e}")

            # Cleanup
            if job_id in self.active_jobs:
                del self.active_jobs[job_id]

            if success:
                return True, " • ".join(msg_parts) if msg_parts else "Cancelled successfully"
            else:
                # If we couldn't find the job in spooler or process, it might be too late
                return False, "Unable to stop printing. Job may have already finished or already cancelled."

        except Exception as e:
            logger.error(f"Error in cancel_job {job_id}: {e}")
            return False, f"Error during cancellation: {str(e)}"

    
    def test_printer(self):
        """Test printer connection"""
        try:
            if not self.current_printer:
                return False, "No printer selected"
            
            # Try to get printer info
            h = win32print.OpenPrinter(self.current_printer)
            info = win32print.GetPrinter(h, 2)
            win32print.ClosePrinter(h)
            status = info.get('Status') or 0
            online = self._is_status_online(status)
            return True, f"Printer '{self.current_printer}' is {'online' if online else 'offline'}"
            
        except Exception as e:
            logger.error(f"Printer test failed: {e}")
            return False, f"Printer test failed: {str(e)}"
    
    def close(self):
        """Close database connection"""
        self.db.close()

    def _discover_wifi_printers(self):
        """Discover WiFi printers using multiple methods"""
        wifi_printers = []
        
        try:
            logger.info("Starting comprehensive WiFi printer discovery...")
            
            # Method 1: Use Windows WSD (Web Services for Devices) discovery
            wsd_printers = self._discover_wsd_printers()
            wifi_printers.extend(wsd_printers)
            logger.info(f"WSD discovery found {len(wsd_printers)} printers")
            
            # Method 2: Scan for common printer ports on local network
            network_printers = self._scan_network_printers()
            wifi_printers.extend(network_printers)
            logger.info(f"Network scan found {len(network_printers)} printers")
            
            # Method 3: Enhanced Windows printer enumeration with different flags
            enhanced_printers = self._discover_enhanced_windows_printers()
            wifi_printers.extend(enhanced_printers)
            logger.info(f"Enhanced Windows discovery found {len(enhanced_printers)} printers")
            
            # Method 4: Try to discover printers via IPP (Internet Printing Protocol)
            ipp_printers = self._discover_ipp_printers()
            wifi_printers.extend(ipp_printers)
            logger.info(f"IPP discovery found {len(ipp_printers)} printers")
            
        except Exception as e:
            logger.error(f"WiFi printer discovery failed: {e}")
        
        return wifi_printers

    def get_printer_connection_info(self, printer_name):
        """Get comprehensive connection information for a printer"""
        try:
            h = win32print.OpenPrinter(printer_name)
            info = win32print.GetPrinter(h, 2)
            win32print.ClosePrinter(h)
            
            port_name = info.get('pPortName', '')
            attributes = info.get('Attributes', 0)
            status = info.get('Status', 0)
            
            # Detect current connection type
            connection_type = self._infer_connection_type(port_name, attributes)
            
            # Check if printer supports multiple connection types
            supports_usb = 'usb' in port_name.lower()
            supports_wifi = any(indicator in port_name.lower() for indicator in 
                              ['wsd', 'tcp', 'ip_', '9100', '631', '515', '80', '443'])
            
            # Determine if this is a dual-connection printer
            is_dual_connection = supports_usb and supports_wifi
            
            return {
                'connection_type': connection_type,
                'port_name': port_name,
                'supports_usb': supports_usb,
                'supports_wifi': supports_wifi,
                'is_dual_connection': is_dual_connection,
                'status': status
            }
            
        except Exception as e:
            logger.debug(f"Error getting connection info for {printer_name}: {e}")
            return {
                'connection_type': 'Unknown',
                'port_name': '',
                'supports_usb': False,
                'supports_wifi': False,
                'is_dual_connection': False,
                'status': 0
            }

    def detect_printer_connection_type(self, printer_name):
        """Detect the actual current connection type of a printer"""
        try:
            # Get printer info to determine current connection type
            h = win32print.OpenPrinter(printer_name)
            info = win32print.GetPrinter(h, 2)
            win32print.ClosePrinter(h)
            
            port_name = info.get('pPortName', '')
            attributes = info.get('Attributes', 0)
            
            # Use enhanced connection type detection
            connection_type = self._infer_connection_type(port_name, attributes)
            
            return connection_type
            
        except Exception as e:
            logger.debug(f"Error detecting connection type for {printer_name}: {e}")
            return 'Unknown'

    def _discover_wsd_printers(self):
        """Discover printers using Windows WSD (Web Services for Devices)"""
        wsd_printers = []
        
        try:
            # Try to use Windows WSD API if available
            import subprocess
            import re
            
            # Use netsh to discover WSD devices
            try:
                result = subprocess.run(['netsh', 'wsd', 'show', 'devices'], 
                                      capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    lines = result.stdout.split('\n')
                    for line in lines:
                        if 'printer' in line.lower() or 'print' in line.lower():
                            # Extract device information
                            parts = line.strip().split()
                            if len(parts) >= 2:
                                device_name = parts[0]
                                ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
                                if ip_match:
                                    ip = ip_match.group(1)
                                    printer_name = f"WSD Printer ({device_name})"
                                    wsd_printers.append({
                                        'name': printer_name,
                                        'id': printer_name,
                                        'description': f'WSD printer: {device_name}',
                                        'connection_type': 'WiFi/Ethernet',
                                        'status': 'Online',
                                        'ip_address': ip,
                                        'discovery_method': 'WSD'
                                    })
            except Exception:
                pass
                
        except Exception as e:
            logger.debug(f"WSD printer discovery failed: {e}")
        
        return wsd_printers

    def _scan_network_printers(self):
        """Scan local network for printer services"""
        network_printers = []
        
        try:
            import socket
            import threading
            import time
            
            # Get local network range
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            network_base = '.'.join(local_ip.split('.')[:-1]) + '.'
            
            # Common printer ports
            printer_ports = [9100, 631, 515, 80, 443]
            found_services = []
            
            def scan_ip(ip, results):
                """Scan a single IP for printer services"""
                for port in printer_ports:
                    try:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(2)
                        result = sock.connect_ex((ip, port))
                        sock.close()
                        
                        if result == 0:
                            results.append((ip, port))
                            break
                    except Exception:
                        continue
            
            # Scan common IPs (1-50 for faster discovery)
            threads = []
            for i in range(1, 51):  # Reduced range for faster scanning
                ip = network_base + str(i)
                thread = threading.Thread(target=scan_ip, args=(ip, found_services))
                thread.daemon = True
                threads.append(thread)
                thread.start()
                
                # Limit concurrent threads
                if len(threads) >= 20:
                    for t in threads:
                        t.join(timeout=0.1)
                    threads = [t for t in threads if t.is_alive()]
            
            # Wait for remaining threads
            for thread in threads:
                thread.join(timeout=3)
            
            # Convert found services to printer entries
            for ip, port in found_services:
                printer_name = f"Network Printer ({ip}:{port})"
                network_printers.append({
                    'name': printer_name,
                    'id': printer_name,
                    'description': f'Network printer at {ip}:{port}',
                    'connection_type': 'WiFi/Ethernet',
                    'status': 'Online',
                    'ip_address': ip,
                    'port': port,
                    'discovery_method': 'Network Scan'
                })
                
        except Exception as e:
            logger.debug(f"Network printer scan failed: {e}")
        
        return network_printers

    def _discover_enhanced_windows_printers(self):
        """Enhanced Windows printer discovery with different enumeration methods"""
        enhanced_printers = []
        
        try:
            # Try different enumeration levels and flags
            enumeration_methods = [
                (win32print.PRINTER_ENUM_LOCAL, 1, "Local Level 1"),
                (win32print.PRINTER_ENUM_LOCAL, 2, "Local Level 2"),
                (win32print.PRINTER_ENUM_LOCAL, 4, "Local Level 4"),
                (win32print.PRINTER_ENUM_CONNECTIONS, 1, "Connections Level 1"),
                (win32print.PRINTER_ENUM_CONNECTIONS, 2, "Connections Level 2"),
                (win32print.PRINTER_ENUM_NETWORK, 1, "Network Level 1"),
                (win32print.PRINTER_ENUM_NETWORK, 2, "Network Level 2"),
            ]
            
            for flags, level, method_name in enumeration_methods:
                try:
                    logger.info(f"Trying {method_name} enumeration...")
                    printers = win32print.EnumPrinters(flags, None, level)
                    logger.info(f"{method_name} found {len(printers)} printers")
                    
                    for info in printers:
                        try:
                            name = info.get('pPrinterName') or ''
                            port_name = info.get('pPortName') or ''
                            attributes = info.get('Attributes') or 0
                            
                            if name:
                                connection_type = self._infer_connection_type(port_name, attributes)
                                if connection_type == 'WiFi/Ethernet':
                                    # Check if we already have this printer
                                    if not any(p['name'] == name for p in enhanced_printers):
                                        enhanced_printers.append({
                                            'name': name,
                                            'id': name,
                                            'description': f'WiFi printer via {method_name}',
                                            'connection_type': 'WiFi/Ethernet',
                                            'status': 'Online',
                                            'port_name': port_name,
                                            'discovery_method': method_name
                                        })
                                        logger.info(f"Enhanced discovery found WiFi printer: {name}")
                        except Exception as e:
                            logger.debug(f"Error processing printer in {method_name}: {e}")
                            continue
                            
                except Exception as e:
                    logger.debug(f"{method_name} enumeration failed: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Enhanced Windows printer discovery failed: {e}")
        
        return enhanced_printers

    def _discover_ipp_printers(self):
        """Discover printers using Internet Printing Protocol (IPP)"""
        ipp_printers = []
        
        try:
            import socket
            import threading
            import time
            
            # Get local network range
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            network_base = '.'.join(local_ip.split('.')[:-1]) + '.'
            
            # IPP port (631)
            ipp_port = 631
            found_ipp_services = []
            
            def scan_ipp_service(ip):
                """Scan for IPP service on a specific IP"""
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(2)
                    result = sock.connect_ex((ip, ipp_port))
                    sock.close()
                    
                    if result == 0:
                        found_ipp_services.append(ip)
                        logger.info(f"Found IPP service at {ip}:{ipp_port}")
                except Exception:
                    pass
            
            # Scan common IPs for IPP services
            threads = []
            for i in range(1, 51):  # Scan first 50 IPs
                ip = network_base + str(i)
                thread = threading.Thread(target=scan_ipp_service, args=(ip,))
                thread.daemon = True
                threads.append(thread)
                thread.start()
                
                # Limit concurrent threads
                if len(threads) >= 20:
                    for t in threads:
                        t.join(timeout=0.1)
                    threads = [t for t in threads if t.is_alive()]
            
            # Wait for remaining threads
            for thread in threads:
                thread.join(timeout=3)
            
            # Convert found IPP services to printer entries
            for ip in found_ipp_services:
                printer_name = f"IPP Printer ({ip})"
                ipp_printers.append({
                    'name': printer_name,
                    'id': printer_name,
                    'description': f'IPP printer at {ip}:{ipp_port}',
                    'connection_type': 'WiFi/Ethernet',
                    'status': 'Online',
                    'ip_address': ip,
                    'port': ipp_port,
                    'discovery_method': 'IPP'
                })
                
        except Exception as e:
            logger.error(f"IPP printer discovery failed: {e}")
        
        return ipp_printers

    def _test_wifi_printer_connectivity(self, printer_name, current_status):
        """
        Test actual connectivity to WiFi printer for more accurate status.
        Does NOT rely on OpenPrinter() for decision (STEP 1).
        """
        try:
            # 1. Attempt to find IP via spooler
            h = win32print.OpenPrinter(printer_name)
            ip_address = None
            try:
                info = win32print.GetPrinter(h, 2)
                port_name = info.get('pPortName', '')
                # Try to extract IP (using local logic if shared one not available)
                import re
                match = re.search(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', port_name)
                if match:
                    ip_address = match.group()
            finally:
                win32print.ClosePrinter(h)
                
            # 2. If IP found, do real network check
            if ip_address:
                import socket
                for port in [9100, 631, 515]:
                    try:
                        with socket.create_connection((ip_address, port), timeout=0.8):
                            return True
                    except:
                        continue
                return False
                
            # 3. If no IP but its network, mark Offline
            # check attributes ... simplified fallback
            return current_status if not ip_address else False
        except Exception:
            return False

    # Debug method removed for production

    def refresh_printer_discovery(self):
        """Refresh printer discovery to find newly connected WiFi printers"""
        try:
            logger.info("Refreshing printer discovery...")
            # Force refresh by clearing any cached data and re-scanning
            return self.get_available_printers()
        except Exception as e:
            logger.error(f"Error refreshing printer discovery: {e}")
            return []

    def test_wifi_printer_connection(self, printer_name):
        """Test connection to a WiFi printer with retry logic"""
        try:
            if not self._is_network_printer(printer_name):
                return False, "Not a network printer"
            
            # Use retry logic for connectivity testing
            with NetworkOperationRetry(CONNECTIVITY_RETRY_CONFIG, f"Test connection to {printer_name}") as retry_ctx:
                success = retry_ctx.execute(self._test_printer_connection_impl, printer_name)
                return success
                
        except Exception as e:
            logger.error(f"Error testing WiFi printer connection: {e}")
            return False, f"Connection test failed: {str(e)}"
    
    def _test_printer_connection_impl(self, printer_name):
        """Internal implementation of printer connection testing"""
        try:
            # Try to open the printer to test connection
            h = win32print.OpenPrinter(printer_name)
            info = win32print.GetPrinter(h, 2)
            win32print.ClosePrinter(h)
            
            status = info.get('Status') or 0
            online = self._is_status_online(status)
            
            if online:
                return True, f"WiFi printer '{printer_name}' is online and ready"
            else:
                return False, f"WiFi printer '{printer_name}' is offline"
                
        except Exception as e:
            logger.error(f"Error in printer connection test: {e}")
            raise e  # Re-raise for retry logic

    def _create_network_printer_port(self, ip_address, port=9100):
        """Create a Windows printer port for network printer if it doesn't exist"""
        try:
            port_name = f"IP_{ip_address}_{port}"
            
            # Check if port already exists
            try:
                win32print.ConfigurePort(None, None, port_name, 0)
                return port_name
            except Exception:
                # Port doesn't exist, try to create it
                pass
            
            # Try to create the port using Windows API
            try:
                # This is a simplified approach - in production, you might want to use
                # more sophisticated port creation methods
                return port_name
            except Exception as e:
                logger.debug(f"Could not create port {port_name}: {e}")
                return None
                
        except Exception as e:
            logger.debug(f"Error creating network printer port: {e}")
            return None

    def _is_network_printer(self, printer_name):
        """Check if the printer is a network/WiFi printer"""
        try:
            # Check if it's one of our discovered network printers
            if "WiFi Printer" in printer_name or "Network Printer" in printer_name or "WSD Printer" in printer_name:
                return True
            
            # Check if it has network characteristics
            available_printers = self.get_available_printers()
            for printer in available_printers:
                if printer['name'] == printer_name:
                    return printer.get('connection_type') == 'WiFi/Ethernet'
            
            return False
        except Exception:
            return False

    def _print_to_network_printer(self, file_path, file_type, settings, job_id=None, printer_name=None):
        """Print to network/WiFi printer using enhanced network printing"""
        # Use provided printer_name or fallback to self.current_printer
        target_printer = printer_name or self.current_printer
        try:
            # Use enhanced network printing with retry logic
            success, message = self.enhanced_network_printing.print_to_network_printer(
                printer_name=target_printer,
                file_path=file_path,
                file_type=file_type,
                settings=settings,
                job_id=job_id
            )
            
            if success:
                return True, message
            else:
                # Fallback to GDI printing if enhanced network printing fails
                logger.warning(f"Enhanced network printing failed, falling back to GDI: {message}")
                return self._print_to_network_printer_gdi_fallback(file_path, file_type, settings, job_id, printer_name=target_printer)
                
        except Exception as e:
            error_msg = f"Network printer printing failed: {str(e)}"
            logger.error(error_msg)
            # Fallback to GDI printing
            try:
                return self._print_to_network_printer_gdi_fallback(file_path, file_type, settings, job_id, printer_name=target_printer)
            except Exception as e2:
                raise PrinterError(f"All network printing methods failed: {str(e2)}")
    
    def _print_to_network_printer_gdi_fallback(self, file_path, file_type, settings, job_id=None, printer_name=None):
        """Fallback GDI printing method for network printers"""
        # Use provided printer_name or fallback to self.current_printer
        target_printer = printer_name or self.current_printer
        try:
            # Prepare file according to layout (N-up) and color
            layout_pages = int(settings.get('layout_pages') or 1)
            color_mode = settings.get('color_mode') or 'Color'
            page_size = settings.get('page_size') or 'A4'
            orientation = settings.get('orientation') or 'Portrait'
            page_range = (settings.get('page_range') or '').strip()
            copies = int(settings.get('copies') or 1)
            print_side = settings.get('print_side') or 'Single'

            try:
                # CRITICAL FIX: Use generate_final_print_pdf() for preview-print matching
                nup_path = generate_final_print_pdf(
                    file_path, 
                    file_type, 
                    page_size=page_size, 
                    orientation=orientation, 
                    layout_pages=layout_pages, 
                    color_mode=color_mode,
                    page_range=page_range
                )
            except Exception as e:
                error_msg = f"Failed to generate final print PDF: {str(e)}"
                logger.error(error_msg)
                raise PrinterError(error_msg)

            # Try SumatraPDF for PDFs first (works with network printers)
            if nup_path.lower().endswith('.pdf'):
                sumatra = self._find_sumatra_pdf()
                if sumatra and os.path.exists(sumatra):
                    try:
                        ok, msg = self._print_with_sumatra(sumatra, nup_path, copies, page_range, orientation, print_side, color_mode, printer_name=target_printer)
                        if ok:
                            return True, msg
                    except Exception as e:
                        logger.warning(f"SumatraPDF printing failed for network printer, falling back to GDI: {e}")

            # Fallback: Use GDI printing (works with all Windows printers)
            try:
                ok, msg = self._print_via_gdi_images(nup_path, file_type, copies, page_range, page_size, orientation, color_mode, print_side=print_side, job_id=job_id, printer_name=target_printer)
                return ok, msg
            except Exception as e:
                error_msg = f"Network printer GDI printing failed: {str(e)}"
                logger.error(error_msg)
                raise PrinterError(error_msg)
                
        except Exception as e:
            error_msg = f"Network printer GDI fallback failed: {str(e)}"
            logger.error(error_msg)
            raise PrinterError(error_msg)

    def _infer_connection_type(self, port_name, attributes):
        """Infer printer connection type based on port name and attributes.

        Enhanced heuristics with better WiFi detection:
        - USBxxx → USB
        - WSD-*, WSD Port → WiFi/Ethernet (network)
        - IP_x.x.x.x, Standard TCP/IP Port, TCPMON → WiFi/Ethernet (network)
        - BT*, BTH*, Bluetooth → Bluetooth
        - If PRINTER_ATTRIBUTE_NETWORK is set → WiFi/Ethernet
        - Network printer ports (9100, 631, etc.) → WiFi/Ethernet
        - Enhanced detection for modern WiFi printers
        """
        try:
            p = (port_name or '').lower()
            
            # Explicit bluetooth hints
            if p.startswith('bt') or p.startswith('bth') or 'bluetooth' in p:
                return 'Bluetooth'
            
            # USB detection (highest priority for USB)
            if p.startswith('usb') or 'usb' in p:
                return 'USB'
            
            # WiFi/Ethernet detection (comprehensive)
            wifi_indicators = [
                'wsd', 'tcp', 'ip_', 'standard tcp/ip', 'tcpmon',
                '9100', '631', '515', '80', '443', 'ipp', 'lpr',
                'network', 'ethernet', 'wifi', 'wireless'
            ]
            
            if any(indicator in p for indicator in wifi_indicators):
                return 'WiFi/Ethernet'
            
            # Check for IP address patterns
            import re
            if re.search(r'\d+\.\d+\.\d+\.\d+', p):
                return 'WiFi/Ethernet'
            
            # Attributes flag (Windows network printer flag)
            try:
                if attributes & win32print.PRINTER_ATTRIBUTE_NETWORK:
                    return 'WiFi/Ethernet'
            except Exception:
                pass
            
            # Default to Unknown if we can't determine
            return 'Unknown'
            
        except Exception:
            return 'Unknown'

    def _is_status_online(self, status_flags):
        """Return True if printer status flags indicate online/ready.

        Enhanced logic for better WiFi printer detection.
        """
        try:
            # Common offline/error flags in winspool.h
            PRINTER_STATUS_OFFLINE = 0x00000080
            PRINTER_STATUS_ERROR = 0x00000002
            PRINTER_STATUS_PAPER_OUT = 0x00000010
            PRINTER_STATUS_DOOR_OPEN = 0x00400000
            PRINTER_STATUS_PAUSED = 0x00000001
            
            # Check for critical offline conditions
            critical_offline = status_flags & (PRINTER_STATUS_OFFLINE | PRINTER_STATUS_ERROR | PRINTER_STATUS_DOOR_OPEN)
            
            # For WiFi printers, be more lenient - only mark offline for critical errors
            # Paper out and paused are not critical for network printers
            if critical_offline:
                return False
            
            # If no critical flags are set, consider it online
            # This helps WiFi printers that may have different status reporting
            return True
            
        except Exception:
            # If we can't determine status, assume online for better WiFi support
            return True


    def get_active_printers(self, shop_id):
        """Return list of active printers for a shop (names)."""
        try:
            printers = self.db.query(Printer).filter(
                Printer.shop_id == shop_id,
                Printer.is_active == True
            ).all()
            return [p.printer_name for p in printers]
        except Exception:
            return []

    def get_shop_printers(self, shop_id):
        """Return printers records for a shop."""
        try:
            return self.db.query(Printer).filter(Printer.shop_id == shop_id).all()
        except Exception:
            return []

    def activate_printer(self, shop_id, printer_name, make_default=False):
        """Activate a printer for the shop; optionally set as default."""
        try:
            existing = self.db.query(Printer).filter(
                Printer.shop_id == shop_id,
                Printer.printer_name == printer_name
            ).first()
            if not existing:
                existing = Printer(
                    shop_id=shop_id,
                    printer_name=printer_name,
                    printer_id=printer_name,
                    is_active=True,
                    is_default=False
                )
                self.db.add(existing)
            else:
                existing.is_active = True
            if make_default:
                # Clear other defaults
                self.db.query(Printer).filter(
                    Printer.shop_id == shop_id,
                    Printer.is_default == True
                ).update({'is_default': False})
                existing.is_default = True
            self.db.commit()
            return True, "Printer activated"
        except Exception as e:
            self.db.rollback()
            return False, f"Activate failed: {e}"

    def deactivate_printer(self, shop_id, printer_name):
        """Deactivate a printer from the shop."""
        try:
            # Try exact match first
            p = self.db.query(Printer).filter(
                Printer.shop_id == shop_id,
                Printer.printer_name == printer_name
            ).first()
            # Fallbacks: case-insensitive and normalized matching
            if not p:
                try:
                    # Load all printers for shop and match by normalized names
                    candidates = self.db.query(Printer).filter(Printer.shop_id == shop_id).all()
                    target_norm = (printer_name or '').strip().lower()
                    def _norm(s):
                        return (s or '').strip().lower()
                    for cand in candidates:
                        if _norm(cand.printer_name) == target_norm or _norm(cand.printer_id) == target_norm:
                            p = cand
                            break
                        # Also allow contains match as last resort
                        if target_norm and (target_norm in _norm(cand.printer_name) or target_norm in _norm(cand.printer_id)):
                            p = cand
                            break
                except Exception:
                    pass
            if not p:
                logger.warning(f"Deactivate printer: '{printer_name}' not found for shop {shop_id}")
                return False, "Not found in shop records"
            was_default = p.is_default
            p.is_active = False
            p.is_default = False
            self.db.commit()
            # If default removed, try set another active as default
            if was_default:
                next_active = self.db.query(Printer).filter(
                    Printer.shop_id == p.shop_id,
                    Printer.is_active == True
                ).first()
                if next_active:
                    next_active.is_default = True
                    self.db.commit()
            return True, "Printer deactivated"
        except Exception as e:
            self.db.rollback()
            return False, f"Deactivate failed: {e}"
