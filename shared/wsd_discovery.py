"""
Web Services for Devices (WSD) Discovery Implementation
Provides comprehensive WSD discovery for modern Wi-Fi printers
"""
import logging
import time
import threading
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import socket
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

@dataclass
class WSDPrinterInfo:
    """Information about a WSD-discovered printer"""
    name: str
    ip_address: str
    port: int
    protocol: str
    status: str
    driver_installed: bool
    port_created: bool
    connectivity_test: bool
    discovery_method: str
    last_seen: datetime
    wsd_endpoint: str
    device_type: str
    manufacturer: str
    model: str

class WSDDiscovery:
    """
    Web Services for Devices (WSD) discovery implementation
    Discovers modern Wi-Fi printers using WSD protocol
    """
    
    def __init__(self):
        self.discovered_printers = {}
        self.running = False
        self.discovery_thread = None
        self._lock = threading.Lock()
        
        # WSD discovery parameters
        self.wsd_port = 3702
        self.discovery_timeout = 5.0
        self.retry_attempts = 3
        
        # Check if WSD is available
        self.wsd_available = self._check_wsd_availability()
        
    def _get_network_ranges(self) -> List[str]:
        """Get local network ranges to scan.

        Uses `netifaces` when available; otherwise returns common private ranges.
        """
        try:
            import netifaces
            ranges: List[str] = []
            for interface in netifaces.interfaces():
                addrs = netifaces.ifaddresses(interface)
                if netifaces.AF_INET in addrs:
                    for addr in addrs[netifaces.AF_INET]:
                        ip = addr.get('addr')
                        if ip and not ip.startswith('127.'):
                            parts = ip.split('.')
                            if len(parts) == 4:
                                ranges.append(f"{parts[0]}.{parts[1]}.{parts[2]}.0/24")
            return ranges or ["192.168.1.0/24", "192.168.0.0/24", "10.0.0.0/24"]
        except Exception:
            return ["192.168.1.0/24", "192.168.0.0/24", "10.0.0.0/24"]

    def _check_wsd_availability(self) -> bool:
        """Check if WSD is available on the system"""
        try:
            import win32com.client
            # Try to create WSD API object
            wsd = win32com.client.Dispatch("WSDAPI.WSDDeviceHost")
            return True
        except Exception as e:
            logger.warning(f"WSD not available: {e}")
            return False
    
    def start_discovery(self, interval: int = 30):
        """Start background WSD discovery"""
        if not self.wsd_available:
            logger.warning("WSD discovery not available, skipping")
            return
            
        with self._lock:
            if self.running:
                return
                
            self.running = True
            self.discovery_thread = threading.Thread(
                target=self._discovery_worker,
                name="WSDDiscovery",
                daemon=True
            )
            self.discovery_thread.start()
            logger.info("WSD discovery started")
    
    def stop_discovery(self):
        """Stop background WSD discovery"""
        with self._lock:
            if not self.running:
                return
                
            self.running = False
            if self.discovery_thread and self.discovery_thread.is_alive():
                self.discovery_thread.join(timeout=5)
            logger.info("WSD discovery stopped")
    
    def _discovery_worker(self):
        """Background worker for WSD discovery"""
        logger.info("WSD discovery worker started")
        
        while self.running:
            try:
                # Perform WSD discovery
                printers = self._discover_wsd_printers()
                
                # Update discovered printers
                with self._lock:
                    for printer in printers:
                        self.discovered_printers[printer.name] = printer
                
                logger.info(f"WSD discovery found {len(printers)} printers")
                
            except Exception as e:
                logger.error(f"Error in WSD discovery worker: {e}")
            
            # Wait before next discovery
            time.sleep(30)  # 30 second interval
        
        logger.info("WSD discovery worker stopped")
    
    def _discover_wsd_printers(self) -> List[WSDPrinterInfo]:
        """Discover printers using WSD protocol"""
        printers = []
        
        try:
            if not self.wsd_available:
                return printers
            
            # Method 1: Use Windows WSD API
            wsd_printers = self._discover_via_windows_wsd()
            printers.extend(wsd_printers)
            
            # Method 2: Use WSD multicast discovery
            multicast_printers = self._discover_via_multicast()
            printers.extend(multicast_printers)
            
            # Method 3: Use WSD unicast discovery
            unicast_printers = self._discover_via_unicast()
            printers.extend(unicast_printers)
            
        except Exception as e:
            logger.error(f"WSD discovery failed: {e}")
        
        return printers
    
    def _discover_via_windows_wsd(self) -> List[WSDPrinterInfo]:
        """Discover printers using Windows WSD API"""
        printers = []
        
        try:
            import win32com.client
            
            # Create WSD discovery object
            wsd = win32com.client.Dispatch("WSDAPI.WSDDeviceHost")
            
            # This is a simplified approach - in production, you'd use proper WSD discovery
            # For now, we'll look for WSD printers in the Windows printer list
            import win32print
            
            flags = (
                win32print.PRINTER_ENUM_LOCAL |
                win32print.PRINTER_ENUM_CONNECTIONS |
                win32print.PRINTER_ENUM_NETWORK |
                win32print.PRINTER_ENUM_REMOTE
            )
            
            printer_list = win32print.EnumPrinters(flags, None, 2)
            
            for info in printer_list:
                port_name = info.get('pPortName', '')
                if 'wsd' in port_name.lower():
                    name = info.get('pPrinterName', '')
                    ip = self._extract_ip_from_port(port_name)
                    
                    if ip:
                        printer = WSDPrinterInfo(
                            name=name,
                            ip_address=ip,
                            port=631,  # Default IPP port for WSD printers
                            protocol='WSD',
                            status='Online',
                            driver_installed=True,
                            port_created=True,
                            connectivity_test=True,
                            discovery_method='Windows WSD API',
                            last_seen=datetime.now(),
                            wsd_endpoint=f"http://{ip}:631/ipp/print",
                            device_type='Printer',
                            manufacturer='Unknown',
                            model='WSD Printer'
                        )
                        printers.append(printer)
                        
        except Exception as e:
            logger.error(f"Windows WSD discovery failed: {e}")
        
        return printers
    
    def _discover_via_multicast(self) -> List[WSDPrinterInfo]:
        """Discover printers using WSD multicast discovery"""
        printers = []
        
        try:
            # WSD multicast address and port
            multicast_addr = "239.255.255.250"
            multicast_port = 3702
            
            # Create UDP socket for multicast discovery
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self.discovery_timeout)
            
            # WSD Probe message
            probe_message = self._create_wsd_probe_message()
            
            # Send multicast probe
            sock.sendto(probe_message.encode(), (multicast_addr, multicast_port))
            
            # Listen for responses
            start_time = time.time()
            while time.time() - start_time < self.discovery_timeout:
                try:
                    data, addr = sock.recvfrom(4096)
                    printer = self._parse_wsd_response(data, addr[0])
                    if printer:
                        printers.append(printer)
                except socket.timeout:
                    break
                except Exception as e:
                    logger.debug(f"Error receiving WSD response: {e}")
                    continue
            
            sock.close()
            
        except Exception as e:
            logger.error(f"WSD multicast discovery failed: {e}")
        
        return printers
    
    def _discover_via_unicast(self) -> List[WSDPrinterInfo]:
        """Discover printers using WSD unicast discovery"""
        printers = []
        
        try:
            # Get local network ranges
            import netifaces
            ranges = []
            
            for interface in netifaces.interfaces():
                addrs = netifaces.ifaddresses(interface)
                if netifaces.AF_INET in addrs:
                    for addr in addrs[netifaces.AF_INET]:
                        ip = addr['addr']
                        if not ip.startswith('127.'):
                            parts = ip.split('.')
                            ranges.append(f"{parts[0]}.{parts[1]}.{parts[2]}.0/24")
            
            # Scan each range for WSD services
            for ip_range in ranges:
                base_ip = ip_range.split('/')[0]
                network_parts = base_ip.split('.')
                
                # Scan first 50 IPs for WSD services
                for i in range(1, 51):
                    ip = f"{network_parts[0]}.{network_parts[1]}.{network_parts[2]}.{i}"
                    
                    # Test WSD port
                    if self._test_wsd_service(ip, self.wsd_port):
                        printer = self._create_wsd_printer_from_ip(ip)
                        if printer:
                            printers.append(printer)
                            
        except Exception as e:
            logger.error(f"WSD unicast discovery failed: {e}")
        
        return printers
    
    def _create_wsd_probe_message(self) -> str:
        """Create WSD Probe message"""
        return """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" 
               xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" 
               xmlns:wsd="http://schemas.xmlsoap.org/ws/2005/04/discovery">
    <soap:Header>
        <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
        <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>
        <wsa:MessageID>uuid:12345678-1234-1234-1234-123456789012</wsa:MessageID>
    </soap:Header>
    <soap:Body>
        <wsd:Probe>
            <wsd:Types>printer</wsd:Types>
        </wsd:Probe>
    </soap:Body>
</soap:Envelope>"""
    
    def _parse_wsd_response(self, data: bytes, ip: str) -> Optional[WSDPrinterInfo]:
        """Parse WSD response and create printer info"""
        try:
            # Parse XML response
            root = ET.fromstring(data)
            
            # Extract printer information from WSD response
            # This is a simplified parser - in production, you'd parse the full WSD response
            
            printer = WSDPrinterInfo(
                name=f"WSD Printer ({ip})",
                ip_address=ip,
                port=631,
                protocol='WSD',
                status='Online',
                driver_installed=False,
                port_created=False,
                connectivity_test=True,
                discovery_method='WSD Multicast',
                last_seen=datetime.now(),
                wsd_endpoint=f"http://{ip}:631/ipp/print",
                device_type='Printer',
                manufacturer='Unknown',
                model='WSD Printer'
            )
            
            return printer
            
        except Exception as e:
            logger.debug(f"Error parsing WSD response from {ip}: {e}")
            return None
    
    def _test_wsd_service(self, ip: str, port: int) -> bool:
        """Test if WSD service is available on IP:port"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((ip, port))
            sock.close()
            return result == 0
        except Exception:
            return False
    
    def _create_wsd_printer_from_ip(self, ip: str) -> Optional[WSDPrinterInfo]:
        """Create WSD printer info from IP address"""
        try:
            # Test if it's actually a printer service
            if self._test_wsd_service(ip, 631):  # Test IPP port
                return WSDPrinterInfo(
                    name=f"WSD Printer ({ip})",
                    ip_address=ip,
                    port=631,
                    protocol='WSD',
                    status='Online',
                    driver_installed=False,
                    port_created=False,
                    connectivity_test=True,
                    discovery_method='WSD Unicast',
                    last_seen=datetime.now(),
                    wsd_endpoint=f"http://{ip}:631/ipp/print",
                    device_type='Printer',
                    manufacturer='Unknown',
                    model='WSD Printer'
                )
        except Exception as e:
            logger.debug(f"Error creating WSD printer from IP {ip}: {e}")
        
        return None
    
    def _extract_ip_from_port(self, port_name: str) -> Optional[str]:
        """Extract IP address from port name"""
        import re
        ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', port_name)
        return ip_match.group(1) if ip_match else None
    
    def get_discovered_printers(self) -> List[WSDPrinterInfo]:
        """Get list of discovered WSD printers"""
        with self._lock:
            return list(self.discovered_printers.values())
    
    def get_printer_by_name(self, name: str) -> Optional[WSDPrinterInfo]:
        """Get printer by name"""
        with self._lock:
            return self.discovered_printers.get(name)
    
    def is_running(self) -> bool:
        """Check if WSD discovery is running"""
        return self.running
