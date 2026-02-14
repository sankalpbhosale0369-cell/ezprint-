"""
Thread-Safe Printer Discovery System
====================================

This module provides thread-safe printer discovery that can run in background threads
without interfering with Qt GUI operations. It uses pure Python threading and
avoids any Qt objects or operations.
"""

import threading
import time
import logging
import queue
import re
import socket
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime

# Windows-specific imports
try:
    import win32print
    import win32api
    import win32con
    WINDOWS_AVAILABLE = True
except ImportError:
    WINDOWS_AVAILABLE = False

logger = logging.getLogger(__name__)

@dataclass
class PrinterInfo:
    """Thread-safe printer information container"""
    name: str
    id: str
    description: str
    connection_type: str
    status: str
    port_name: str
    attributes: int
    driver_name: str = ""
    is_virtual: bool = False
    ip_address: Optional[str] = None
    discovery_method: Optional[str] = None
    last_verified: float = 0.0
    connection_verified: bool = False

class ThreadSafePrinterDiscovery:
    """
    Thread-safe printer discovery that runs in background threads
    without touching Qt objects or GUI components
    """
    
    def __init__(self, callback: Optional[Callable[[List[PrinterInfo]], None]] = None):
        self.callback = callback
        self.discovery_thread = None
        self.running = False
        self.discovery_queue = queue.Queue()
        self.last_discovery_time = 0
        self.discovery_interval = 30  # seconds
        self._lock = threading.Lock()
        self._network_status_cache = {}  # ip -> (is_online, timestamp)
        self._cache_ttl = 15  # seconds
        
    def start_discovery(self, interval: int = 30):
        """Start background printer discovery"""
        with self._lock:
            if self.running:
                return
                
            self.running = True
            self.discovery_interval = interval
            
            self.discovery_thread = threading.Thread(
                target=self._discovery_worker,
                name="PrinterDiscovery",
                daemon=True
            )
            self.discovery_thread.start()
            logger.info("Thread-safe printer discovery started")
    
    def stop_discovery(self):
        """Stop background printer discovery"""
        with self._lock:
            if not self.running:
                return
                
            self.running = False
            if self.discovery_thread and self.discovery_thread.is_alive():
                self.discovery_thread.join(timeout=1)  # Reduced from 5 to 1 second
            logger.info("Thread-safe printer discovery stopped")
    
    def _discovery_worker(self):
        """Background worker for printer discovery"""
        logger.info("Printer discovery worker started")
        
        while self.running:
            try:
                # Perform discovery
                printers = self._discover_printers()
                
                # Notify callback if available
                if self.callback and printers:
                    try:
                        self.callback(printers)
                    except Exception as e:
                        logger.error(f"Error in printer discovery callback: {e}")
                
                # Wait for next discovery cycle
                time.sleep(self.discovery_interval)
                
            except Exception as e:
                logger.error(f"Error in printer discovery worker: {e}")
                time.sleep(5)  # Short delay before retry
        
        logger.info("Printer discovery worker stopped")
    
    def update_interval(self, new_interval: int):
        """Update the discovery interval (thread-safe)"""
        with self._lock:
            self.discovery_interval = new_interval
            logger.info(f"Printer discovery interval updated to {new_interval} seconds")
    
    def _discover_printers(self) -> List[PrinterInfo]:
        """Discover printers using Windows API (thread-safe)"""
        if not WINDOWS_AVAILABLE:
            logger.warning("Windows API not available for printer discovery")
            return []
        
        printers = []
        
        try:
            # LAYER A — WINDOWS SPOOLER (AUTHORITATIVE) (STEP 1)
            # Use only LOCAL and CONNECTIONS to get real Windows print queues
            # This covers USB, TCP/IP, WSD, IPP, and Shared network printers
            flags = (
                win32print.PRINTER_ENUM_LOCAL |
                win32print.PRINTER_ENUM_CONNECTIONS
            )
            
            logger.debug("Starting authoritative spooler discovery...")
            
            # Enumerate printers
            printer_list = win32print.EnumPrinters(flags, None, 2)
            logger.debug(f"Windows Spooler returned {len(printer_list)} authoritative entries")
            
            for info in printer_list:
                try:
                    name = info.get('pPrinterName') or ''
                    comment = info.get('pComment') or ''
                    port_name = info.get('pPortName') or ''
                    attributes = info.get('Attributes') or 0
                    driver_name = info.get('pDriverName') or ''
                    
                    # Get printer status
                    status = 0 # Ensure status is always an integer
                    open_failed = False
                    try:
                        h = win32print.OpenPrinter(name)
                        try:
                            info6 = win32print.GetPrinter(h, 6)
                            status = info6.get('dwStatus') if isinstance(info6, dict) else info.get('Status', 0)
                        finally:
                            win32print.ClosePrinter(h)
                    except Exception:
                        open_failed = True
                        status = info.get('Status') or 0
                    
                    # Ensure status is an integer for bitwise operations (Objective 3)
                    if status is None:
                        status = 0
                    
                    # Determine connection type and is_virtual (Rule 2)
                    connection_type, is_virtual = self._infer_connection_type(name, port_name, driver_name, attributes)
                    
                    # Extract IP address for network printers
                    ip_address = self._extract_ip_from_port(port_name) if connection_type == 'WiFi/Ethernet' else None
                    
                    # STEP 3: INDUSTRY-STANDARD ONLINE / OFFLINE DETECTION
                    online = False
                    status_text = 'Offline'
                    connection_verified = False

                    if connection_type == 'USB':
                        # USB Rule: Authoritative flags check
                        # PRINTER_STATUS_OFFLINE (0x80), ERROR (0x02), PAPER_OUT (0x10), PAUSED (0x01)
                        critical_flags = 0x00000080 | 0x00000002 | 0x00000010 | 0x00000001
                        online = not (status & critical_flags)
                        status_text = 'Online' if online else 'Offline'
                        connection_verified = online
                    elif connection_type == 'WiFi/Ethernet':
                        # INDUSTRY-STANDARD NETWORK PRINTER STATUS LOGIC
                        # Windows Spooler (EnumPrinters) returns cached/stale status (0 = Ready)
                        # even when unplugged. Real-time active reachability is authoritative.
                        
                        reachable = False
                        if ip_address:
                            # Primary Check: Active socket probe
                            reachable = self._test_network_reachability(ip_address)
                        
                        # Spooler Check (Secondary): Only used if physical reachability is confirmed.
                        # This prevents 'Ready (0)' spooler status from forcing a disconnected printer Online.
                        major_offline_flags = 0x00000080 | 0x00000002 | 0x00001000 # OFFLINE, ERROR, NOT_AVAILABLE
                        spooler_online = (status == 0) or not (status & major_offline_flags)
                        
                        # RULE: Must be physically reachable via network AND not reported in error by Spooler.
                        # If unreachable, the printer is Offline even if Spooler says 'Ready'.
                        online = reachable and spooler_online
                        
                        connection_verified = reachable # Physical reachability is the 'verified' signal
                        status_text = 'Online' if online else 'Offline'
                    else:
                        # Fallback for virtual or other printers
                        online = self._is_status_online_fallback(status)
                        status_text = 'Online' if online else 'Offline'
                        connection_verified = online
                    
                    # Respect work-offline attribute
                    try:
                        if attributes & getattr(win32print, 'PRINTER_ATTRIBUTE_WORK_OFFLINE', 0x00000400):
                            if not is_virtual:
                                online = False
                                status_text = 'Offline'
                                connection_verified = False
                    except Exception:
                        pass
                    
                    if name:
                        printer_info = PrinterInfo(
                            name=name,
                            id=name,
                            description=comment or name,
                            connection_type=connection_type,
                            status=status_text,
                            port_name=port_name,
                            attributes=attributes,
                            driver_name=driver_name,
                            is_virtual=is_virtual,
                            ip_address=ip_address,
                            connection_verified=connection_verified,
                            last_verified=time.time()
                        )
                        printers.append(printer_info)
                except Exception as e:
                    logger.debug(f"Error processing printer info: {e}")
                    continue
            
            # LAYER B — NETWORK DISCOVERY (SUPPORTING) (STEP 2)
            # Use active discovery to find IP addresses for spooler printers that lack them
            hints = self._discover_wifi_printers()
            for hint in hints:
                if not hint.ip_address:
                    continue
                
                # Try to find a matching spooler printer by name or port
                for p in printers:
                    if p.connection_type == 'WiFi/Ethernet' and not p.ip_address:
                        # Match by name similarity or if the hint name is part of the spooler name
                        if hint.name.lower() in p.name.lower() or p.name.lower() in hint.name.lower():
                            p.ip_address = hint.ip_address
                            # If hint says it's online, update spooler status if it was offline
                            if hint.status == 'Online' and p.status == 'Offline':
                                p.status = 'Online'
                                p.connection_verified = True
                            logger.debug(f"Enriched spooler printer {p.name} with IP {p.ip_address}")
            
            logger.info(f"Discovery found {len(printers)} authoritative printers")
            return printers
            
        except Exception as e:
            logger.error(f"Error in thread-safe printer discovery: {e}")
            return []
    
    def _infer_connection_type(self, name: str, port_name: str, driver_name: str, attributes: int) -> tuple[str, bool]:
        """Infer connection type and virtual status with refined priority rules"""
        p = (port_name or '').upper()
        n = (name or '').upper()
        d = (driver_name or '').upper()
        
        # Default values
        connection_type = 'Network'
        is_virtual = False
        
        # A. Port-based priority (HIGHEST PRIORITY)
        if p.startswith('USB'):
            connection_type = 'USB'
            is_virtual = False
        elif any(ind in p for ind in ['TCP', 'IP_', 'WSD', 'IPP', 'HTTP', 'HTTPS']):
            connection_type = 'WiFi/Ethernet'
            is_virtual = False
        elif p.startswith('LPT') or p.startswith('COM'):
            connection_type = 'Serial/Parallel'
            is_virtual = False
        elif p == 'NUL:':
            connection_type = 'Virtual'
            is_virtual = True
        
        # Attributes check for network
        try:
            if attributes & win32print.PRINTER_ATTRIBUTE_NETWORK:
                if connection_type != 'USB':  # USN still takes priority
                    connection_type = 'WiFi/Ethernet'
        except Exception:
            pass

        # B. Name-based virtual filter (STRICT ONLY)
        virtual_indicators = ["MICROSOFT PRINT TO PDF", "XPS", "ONENOTE", "FAX"]
        if any(ind in n for ind in virtual_indicators):
            is_virtual = True
            
        # C. Driver-based refinement
        # Specifically avoid classifying as virtual based on driver alone if port is physical
        # Physical printer with Class Driver or Microsoft IPP
        if ("CLASS DRIVER" in d or "MICROSOFT IPP" in d) and (connection_type in ['USB', 'WiFi/Ethernet']):
            is_virtual = False
            
        return connection_type, is_virtual
    
    def _is_status_online_fallback(self, status: int) -> bool:
        """Fallback check if printer status indicates online"""
        # Common Windows printer status flags
        OFFLINE_FLAGS = {
            0x00000001,  # PRINTER_STATUS_PAUSED
            0x00000002,  # PRINTER_STATUS_ERROR
            0x00000004,  # PRINTER_STATUS_PENDING_DELETION
            0x00000008,  # PRINTER_STATUS_PAPER_JAM
            0x00000010,  # PRINTER_STATUS_PAPER_OUT
            0x00000020,  # PRINTER_STATUS_MANUAL_FEED
            0x00000040,  # PRINTER_STATUS_PAPER_PROBLEM
            0x00000080,  # PRINTER_STATUS_OFFLINE
            0x00000100,  # PRINTER_STATUS_IO_ACTIVE
            0x00000200,  # PRINTER_STATUS_BUSY
            0x00000400,  # PRINTER_STATUS_PRINTING
            0x00000800,  # PRINTER_STATUS_OUTPUT_BIN_FULL
            0x00001000,  # PRINTER_STATUS_NOT_AVAILABLE
            0x00002000,  # PRINTER_STATUS_WAITING
            0x00004000,  # PRINTER_STATUS_PROCESSING
            0x00008000,  # PRINTER_STATUS_INITIALIZING
            0x00010000,  # PRINTER_STATUS_WARMING_UP
            0x00020000,  # PRINTER_STATUS_TONER_LOW
            0x00040000,  # PRINTER_STATUS_NO_TONER
            0x00080000,  # PRINTER_STATUS_PAGE_PUNT
            0x00100000,  # PRINTER_STATUS_USER_INTERVENTION
            0x00200000,  # PRINTER_STATUS_OUT_OF_MEMORY
            0x00400000,  # PRINTER_STATUS_DOOR_OPEN
            0x00800000,  # PRINTER_STATUS_SERVER_UNKNOWN
            0x01000000,  # PRINTER_STATUS_POWER_SAVE
        }
        
        # Check for offline flags
        for flag in OFFLINE_FLAGS:
            if status & flag:
                return False
        
        return True
    
    def _test_network_reachability(self, ip_address: str) -> bool:
        """
        Test if a network printer is actually reachable via common ports (STEP 1).
        Uses a short-lived cache to avoid redundant network scans.
        """
        if not ip_address:
            return False
            
        with self._lock:
            now = time.time()
            if ip_address in self._network_status_cache:
                is_online, timestamp = self._network_status_cache[ip_address]
                if now - timestamp < self._cache_ttl:
                    return is_online
        
        # Perform real network check
        # common printer ports: 9100 (RAW), 631 (IPP), 515 (LPR)
        ports = [9100, 631, 515]
        is_reachable = False
        
        for port in ports:
            try:
                # Use a short timeout to prevent UI freeze (though this should be in background)
                with socket.create_connection((ip_address, port), timeout=1.0):
                    is_reachable = True
                    break
            except (socket.timeout, ConnectionRefusedError, OSError):
                continue
        
        with self._lock:
            self._network_status_cache[ip_address] = (is_reachable, time.time())
            
        return is_reachable

    def _test_wifi_printer_connectivity(self, printer_name: str, default_online: bool) -> bool:
        """
        FIX 1: Network reachability check (STEP 1).
        Does NOT rely on OpenPrinter() for connectivity logic.
        """
        ip_address = None
        try:
            # Attempt to find IP from spooler info
            h = win32print.OpenPrinter(printer_name)
            try:
                info = win32print.GetPrinter(h, 2)
                port_name = info.get('pPortName', '')
                ip_address = self._extract_ip_from_port(port_name)
            finally:
                win32print.ClosePrinter(h)
        except:
            pass
            
        if ip_address:
            # Real network check
            return self._test_network_reachability(ip_address)
            
        # Check if it's a network printer by attributes
        try:
            h = win32print.OpenPrinter(printer_name)
            try:
                info = win32print.GetPrinter(h, 2)
                if (info.get('Attributes', 0) & win32print.PRINTER_ATTRIBUTE_NETWORK):
                    # Network printer but no IP found -> Mark unreachable
                    return False
            finally:
                win32print.ClosePrinter(h)
        except:
            pass
            
        # Fallback for USB/Virtual - rely on spooler access
        try:
            h = win32print.OpenPrinter(printer_name)
            win32print.ClosePrinter(h)
            return True
        except:
            return default_online
    
    def _discover_wifi_printers(self) -> List[PrinterInfo]:
        """Discover WiFi printers using enhanced network scanning (thread-safe)"""
        wifi_printers = []
        
        try:
            logger.info("Starting enhanced WiFi printer discovery...")
            
            # Method 1: Windows API Network Discovery
            network_printers = self._discover_network_printers_windows_api()
            wifi_printers.extend(network_printers)
            logger.info(f"Windows API found {len(network_printers)} network printers")
            
            # Method 2: WSD (Web Services for Devices) Discovery
            wsd_printers = self._discover_printers_wsd()
            wifi_printers.extend(wsd_printers)
            logger.info(f"WSD discovery found {len(wsd_printers)} printers")
            
            # Method 3: IPP (Internet Printing Protocol) Discovery
            ipp_printers = self._discover_printers_ipp()
            wifi_printers.extend(ipp_printers)
            logger.info(f"IPP discovery found {len(ipp_printers)} printers")
            
            # Method 4: Network Port Scanning
            port_printers = self._discover_printers_port_scan()
            wifi_printers.extend(port_printers)
            logger.info(f"Port scanning found {len(port_printers)} printers")
            
            # Remove duplicates based on name and IP
            unique_printers = []
            seen = set()
            for printer in wifi_printers:
                key = (printer.name, printer.ip_address)
                if key not in seen:
                    seen.add(key)
                    unique_printers.append(printer)
            
            logger.info(f"Total unique WiFi printers discovered: {len(unique_printers)}")
            return unique_printers
                    
        except Exception as e:
            logger.error(f"Error in enhanced WiFi printer discovery: {e}")
            return []
    
    def _discover_network_printers_windows_api(self) -> List[PrinterInfo]:
        """Discover network printers using Windows API"""
        printers = []
        
        try:
            # Try different enumeration levels for better coverage
            for level in [1, 2, 4]:
                try:
                    flags = win32print.PRINTER_ENUM_NETWORK
                    printer_list = win32print.EnumPrinters(flags, None, level)
                    
                    for info in printer_list:
                        try:
                            name = info.get('pPrinterName') or ''
                            port_name = info.get('pPortName') or ''
                            comment = info.get('pComment') or ''
                            
                            if name and self._is_network_port(port_name):
                                ip_address = self._extract_ip_from_port(port_name)
                                
                                printer_info = PrinterInfo(
                                    name=name,
                                    id=name,
                                    description=comment or f"Network Printer ({ip_address})" if ip_address else name,
                                    connection_type='WiFi/Ethernet',
                                    status='Online' if self._test_network_reachability(ip_address) else 'Offline',
                                    port_name=port_name,
                                    attributes=info.get('Attributes', 0),
                                    ip_address=ip_address,
                                    connection_verified=self._test_network_reachability(ip_address) if ip_address else False,
                                    last_verified=time.time(),
                                    discovery_method=f'Windows API Level {level}'
                                )
                                printers.append(printer_info)
                                logger.debug(f"Found network printer: {name} at {ip_address}")
                                
                        except Exception as e:
                            logger.debug(f"Error processing printer info: {e}")
                            continue
                            
                except Exception as e:
                    logger.debug(f"Error with enumeration level {level}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error in Windows API network discovery: {e}")
        
        return printers
    
    def _discover_printers_wsd(self) -> List[PrinterInfo]:
        """Discover printers using WSD (Web Services for Devices)"""
        printers = []
        
        try:
            # WSD discovery using Windows API
            try:
                # Try to enumerate WSD printers
                wsd_flags = win32print.PRINTER_ENUM_NETWORK
                wsd_printers = win32print.EnumPrinters(wsd_flags, None, 2)
                
                for info in wsd_printers:
                    try:
                        name = info.get('pPrinterName') or ''
                        port_name = info.get('pPortName') or ''
                        comment = info.get('pComment') or ''
                        
                        # Check if it's a WSD printer (usually has WSD in the name or port)
                        if name and ('wsd' in name.lower() or 'wsd' in port_name.lower()):
                            ip_address = self._extract_ip_from_port(port_name)
                            
                            printer_info = PrinterInfo(
                                name=name,
                                id=name,
                                description=comment or f"WSD Printer ({ip_address})" if ip_address else name,
                                connection_type='WiFi/Ethernet',
                                status='Online' if self._test_network_reachability(ip_address) else 'Offline',
                                port_name=port_name,
                                attributes=info.get('Attributes', 0),
                                ip_address=ip_address,
                                connection_verified=self._test_network_reachability(ip_address) if ip_address else False,
                                last_verified=time.time(),
                                discovery_method='WSD Discovery'
                            )
                            printers.append(printer_info)
                            logger.debug(f"Found WSD printer: {name}")
                            
                    except Exception as e:
                        logger.debug(f"Error processing WSD printer: {e}")
                        continue
                        
            except Exception as e:
                logger.debug(f"WSD discovery not available: {e}")
                
        except Exception as e:
            logger.error(f"Error in WSD discovery: {e}")
        
        return printers
    
    def _discover_printers_ipp(self) -> List[PrinterInfo]:
        """Discover printers using IPP (Internet Printing Protocol)"""
        printers = []
        
        try:
            # Look for IPP printers in the system
            try:
                flags = win32print.PRINTER_ENUM_NETWORK
                printer_list = win32print.EnumPrinters(flags, None, 2)
                
                for info in printer_list:
                    try:
                        name = info.get('pPrinterName') or ''
                        port_name = info.get('pPortName') or ''
                        comment = info.get('pComment') or ''
                        
                        # Check if it's an IPP printer
                        if name and ('ipp' in port_name.lower() or 'ipp://' in port_name.lower()):
                            ip_address = self._extract_ip_from_port(port_name)
                            
                            printer_info = PrinterInfo(
                                name=name,
                                id=name,
                                description=comment or f"IPP Printer ({ip_address})" if ip_address else name,
                                connection_type='WiFi/Ethernet',
                                status='Online' if self._test_network_reachability(ip_address) else 'Offline',
                                port_name=port_name,
                                attributes=info.get('Attributes', 0),
                                ip_address=ip_address,
                                connection_verified=self._test_network_reachability(ip_address) if ip_address else False,
                                last_verified=time.time(),
                                discovery_method='IPP Discovery'
                            )
                            printers.append(printer_info)
                            logger.debug(f"Found IPP printer: {name}")
                            
                    except Exception as e:
                        logger.debug(f"Error processing IPP printer: {e}")
                        continue
                        
            except Exception as e:
                logger.debug(f"IPP discovery not available: {e}")
                
        except Exception as e:
            logger.error(f"Error in IPP discovery: {e}")
        
        return printers
    
    def _discover_printers_port_scan(self) -> List[PrinterInfo]:
        """Discover printers by scanning common printer ports (STEP 2: SUPPORTING ONLY)"""
        printers = []
        
        try:
            import socket
            import threading
            import time
            
            # Common printer ports
            printer_ports = [9100, 631, 515]
            
            # Get local network range
            local_ips = self._get_local_network_ips()
            
            def scan_ip_port(ip, port, results):
                """Scan a specific IP and port"""
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.5)  # Short timeout for faster discovery
                    result = sock.connect_ex((ip, port))
                    sock.close()
                    
                    if result == 0:  # Port is open
                        results.append((ip, port))
                except Exception:
                    pass
            
            # Scan in parallel
            results = []
            threads = []
            
            # Limit scan range to avoid massive thread count
            for ip in local_ips:
                for port in printer_ports:
                    thread = threading.Thread(target=scan_ip_port, args=(ip, port, results))
                    thread.daemon = True
                    thread.start()
                    threads.append(thread)
            
            # Wait for all threads to complete
            for thread in threads:
                thread.join(timeout=2)
            
            # Create HINTS for found ports (Note: No "Network Printer IP:PORT" names anymore)
            for ip, port in results:
                # Use a generic name that can be matched against spooler printers
                printer_info = PrinterInfo(
                    name=f"Network Device {ip}",
                    id=ip,
                    description=f"Network printer at {ip}",
                    connection_type='WiFi/Ethernet',
                    status='Online',
                    port_name=str(port),
                    attributes=0,
                    ip_address=ip,
                    connection_verified=True,
                    last_verified=time.time(),
                    discovery_method='Port Scan'
                )
                printers.append(printer_info)
                
        except Exception as e:
            logger.error(f"Error in port scanning: {e}")
        
        return printers
    
    def _is_network_port(self, port_name: str) -> bool:
        """Check if port name indicates network connection"""
        if not port_name:
            return False
        
        port_lower = port_name.lower()
        network_indicators = ['tcp', 'ip_', 'ipp', 'wsd', 'http', 'https']
        
        return any(indicator in port_lower for indicator in network_indicators)
    
    def _extract_ip_from_port(self, port_name: str) -> str:
        """Extract IP address from port name"""
        if not port_name:
            return None
        
        try:
            # Handle different port formats
            if 'tcp://' in port_name.lower():
                return port_name.split('tcp://')[1].split(':')[0]
            elif 'ip_' in port_name.lower():
                return port_name.split('ip_')[1].split(':')[0]
            elif 'ipp://' in port_name.lower():
                return port_name.split('ipp://')[1].split(':')[0]
            elif 'wsd://' in port_name.lower():
                return port_name.split('wsd://')[1].split(':')[0]
            else:
                # Try to extract IP from various formats
                import re
                ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
                match = re.search(ip_pattern, port_name)
                return match.group() if match else None
                
        except Exception:
            return None
    
    def _get_local_network_ips(self) -> List[str]:
        """Get list of local network IPs to scan"""
        ips = []
        
        try:
            import socket
            
            # Get local IP
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            
            # Extract network prefix (e.g., 192.168.1 from 192.168.1.100)
            ip_parts = local_ip.split('.')
            if len(ip_parts) == 4:
                network_prefix = '.'.join(ip_parts[:3])
                
                # Scan common local network ranges
                for i in range(1, 255):  # Skip .0 and .255
                    ips.append(f"{network_prefix}.{i}")
                    
        except Exception as e:
            logger.debug(f"Error getting local network IPs: {e}")
            # Fallback to common local IPs
            ips = [f"192.168.1.{i}" for i in range(1, 255)]
        
        return ips
    
    def get_cached_printers(self) -> List[PrinterInfo]:
        """Get last discovered printers (thread-safe)"""
        try:
            return self.discovery_queue.get_nowait()
        except queue.Empty:
            return []
    
    def force_discovery(self) -> List[PrinterInfo]:
        """Force immediate printer discovery (thread-safe)"""
        return self._discover_printers()

class ThreadSafePrinterManager:
    """
    Thread-safe printer manager that coordinates with the discovery system
    and provides a clean interface for the GUI
    """
    
    def __init__(self):
        self.discovery = ThreadSafePrinterDiscovery(callback=self._on_printers_discovered)
        self.cached_printers = []
        self._lock = threading.Lock()
        
    def start_discovery(self, interval: int = 30):
        """Start background printer discovery"""
        self.discovery.start_discovery(interval)
    
    def stop_discovery(self):
        """Stop background printer discovery"""
        self.discovery.stop_discovery()
    
    def update_discovery_interval(self, interval: int):
        """Update the background discovery interval"""
        self.discovery.update_interval(interval)
    
    def _on_printers_discovered(self, printers: List[PrinterInfo]):
        """Callback for when printers are discovered (thread-safe)"""
        with self._lock:
            self.cached_printers = printers
            logger.info(f"Updated cached printers: {len(printers)} found")
    
    def get_available_printers(self) -> List[Dict]:
        """Get available printers as dictionaries (thread-safe)"""
        with self._lock:
            return [
                {
                    'name': p.name,
                    'id': p.id,
                    'description': p.description,
                    'connection_type': p.connection_type,
                    'is_virtual': p.is_virtual,
                    'status': p.status,
                    'port_name': p.port_name,
                    'attributes': p.attributes,
                    'driver_name': p.driver_name,
                    'ip_address': p.ip_address,
                    'discovery_method': p.discovery_method,
                    'connection_verified': p.connection_verified,
                    'last_verified': p.last_verified
                }
                for p in self.cached_printers
            ]
    
    def force_refresh(self) -> List[Dict]:
        """Force immediate printer refresh (thread-safe)"""
        printers = self.discovery.force_discovery()
        with self._lock:
            self.cached_printers = printers
        return self.get_available_printers()
