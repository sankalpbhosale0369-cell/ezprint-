"""
Connection Monitoring System for Network Printers
Provides real-time monitoring of printer connectivity and automatic reconnection
"""
import logging
import time
import threading
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
import socket
import queue

logger = logging.getLogger(__name__)

@dataclass
class PrinterStatus:
    """Current status of a printer"""
    name: str
    ip_address: str
    port: int
    protocol: str
    is_online: bool
    last_seen: datetime
    last_error: Optional[str]
    connection_attempts: int
    consecutive_failures: int
    last_successful_connection: Optional[datetime]

@dataclass
class ConnectionEvent:
    """Connection event notification"""
    event_type: str  # 'connected', 'disconnected', 'reconnected', 'failed'
    printer_name: str
    ip_address: str
    timestamp: datetime
    message: str
    error: Optional[str] = None

class ConnectionMonitor:
    """
    Real-time connection monitoring for network printers
    Monitors printer connectivity and triggers reconnection attempts
    """
    
    def __init__(self, check_interval: int = 30, timeout: int = 5):
        self.check_interval = check_interval
        self.timeout = timeout
        self.running = False
        self.monitor_thread = None
        self.printer_statuses = {}
        self.event_callbacks = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        
        # Connection retry configuration
        self.max_retry_attempts = 5
        self.retry_delay = 10  # seconds
        self.backoff_multiplier = 2.0
        
    def start_monitoring(self):
        """Start background connection monitoring"""
        with self._lock:
            if self.running:
                return
                
            self.running = True
            self._stop_event.clear()
            
            self.monitor_thread = threading.Thread(
                target=self._monitoring_worker,
                name="ConnectionMonitor",
                daemon=True
            )
            self.monitor_thread.start()
            logger.info("Connection monitoring started")
    
    def stop_monitoring(self):
        """Stop background connection monitoring"""
        with self._lock:
            if not self.running:
                return
                
            self.running = False
            self._stop_event.set()
            
            if self.monitor_thread and self.monitor_thread.is_alive():
                self.monitor_thread.join(timeout=5)
            logger.info("Connection monitoring stopped")
    
    def add_printer(self, printer_info: Dict[str, Any]):
        """Add printer to monitoring list"""
        with self._lock:
            name = printer_info.get('name')
            ip = printer_info.get('ip_address')
            port = printer_info.get('port', 9100)
            protocol = printer_info.get('protocol', 'RAW')
            
            if not name or not ip:
                logger.warning(f"Cannot add printer to monitoring: missing name or IP")
                return
            
            status = PrinterStatus(
                name=name,
                ip_address=ip,
                port=port,
                protocol=protocol,
                is_online=False,
                last_seen=datetime.now(),
                last_error=None,
                connection_attempts=0,
                consecutive_failures=0,
                last_successful_connection=None
            )
            
            self.printer_statuses[name] = status
            logger.info(f"Added printer to monitoring: {name} ({ip}:{port})")
    
    def remove_printer(self, printer_name: str):
        """Remove printer from monitoring list"""
        with self._lock:
            if printer_name in self.printer_statuses:
                del self.printer_statuses[printer_name]
                logger.info(f"Removed printer from monitoring: {printer_name}")
    
    def get_printer_status(self, printer_name: str) -> Optional[PrinterStatus]:
        """Get current status of a printer"""
        with self._lock:
            return self.printer_statuses.get(printer_name)
    
    def get_all_statuses(self) -> Dict[str, PrinterStatus]:
        """Get status of all monitored printers"""
        with self._lock:
            return self.printer_statuses.copy()
    
    def add_event_callback(self, callback: Callable[[ConnectionEvent], None]):
        """Add callback for connection events"""
        self.event_callbacks.append(callback)
    
    def remove_event_callback(self, callback: Callable[[ConnectionEvent], None]):
        """Remove callback for connection events"""
        if callback in self.event_callbacks:
            self.event_callbacks.remove(callback)
    
    def _monitoring_worker(self):
        """Background worker for connection monitoring"""
        logger.info("Connection monitoring worker started")
        
        while self.running and not self._stop_event.is_set():
            try:
                # Check all monitored printers
                self._check_all_printers()
                
                # Wait for next check
                self._stop_event.wait(self.check_interval)
                
            except Exception as e:
                logger.error(f"Error in connection monitoring worker: {e}")
                time.sleep(5)  # Wait before retrying
        
        logger.info("Connection monitoring worker stopped")
    
    def _check_all_printers(self):
        """Check connectivity of all monitored printers"""
        with self._lock:
            printers_to_check = list(self.printer_statuses.values())
        
        for status in printers_to_check:
            try:
                self._check_printer_connection(status)
            except Exception as e:
                logger.error(f"Error checking printer {status.name}: {e}")
    
    def _check_printer_connection(self, status: PrinterStatus):
        """Check connection to a specific printer"""
        try:
            # Test connection based on protocol
            is_online = self._test_printer_connection(status)
            
            # Update status
            with self._lock:
                old_status = status.is_online
                status.last_seen = datetime.now()
                
                if is_online:
                    if not old_status:
                        # Printer came online
                        status.is_online = True
                        status.consecutive_failures = 0
                        status.last_successful_connection = datetime.now()
                        status.last_error = None
                        
                        self._notify_event(ConnectionEvent(
                            event_type='connected',
                            printer_name=status.name,
                            ip_address=status.ip_address,
                            timestamp=datetime.now(),
                            message=f"Printer {status.name} is now online"
                        ))
                    else:
                        # Printer still online
                        status.is_online = True
                        status.consecutive_failures = 0
                else:
                    if old_status:
                        # Printer went offline
                        status.is_online = False
                        status.consecutive_failures += 1
                        
                        self._notify_event(ConnectionEvent(
                            event_type='disconnected',
                            printer_name=status.name,
                            ip_address=status.ip_address,
                            timestamp=datetime.now(),
                            message=f"Printer {status.name} is now offline"
                        ))
                    else:
                        # Printer still offline
                        status.is_online = False
                        status.consecutive_failures += 1
                        
                        # Try to reconnect if we haven't tried recently
                        if self._should_attempt_reconnection(status):
                            self._attempt_reconnection(status)
                
        except Exception as e:
            logger.error(f"Error checking connection to {status.name}: {e}")
            with self._lock:
                status.last_error = str(e)
                status.consecutive_failures += 1
    
    def _test_printer_connection(self, status: PrinterStatus) -> bool:
        """Test connection to printer based on protocol"""
        try:
            if status.protocol == 'RAW':
                return self._test_raw_connection(status.ip_address, status.port)
            elif status.protocol == 'IPP':
                return self._test_ipp_connection(status.ip_address, status.port)
            elif status.protocol == 'LPR':
                return self._test_lpr_connection(status.ip_address, status.port)
            elif status.protocol == 'WSD':
                return self._test_wsd_connection(status.ip_address, status.port)
            else:
                # Default to RAW connection test
                return self._test_raw_connection(status.ip_address, status.port)
                
        except Exception as e:
            logger.debug(f"Connection test failed for {status.name}: {e}")
            return False
    
    def _test_raw_connection(self, ip: str, port: int) -> bool:
        """Test RAW connection to printer"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                result = sock.connect_ex((ip, port))
                return result == 0
        except Exception:
            return False
    
    def _test_ipp_connection(self, ip: str, port: int) -> bool:
        """Test IPP connection to printer"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                result = sock.connect_ex((ip, port))
                return result == 0
        except Exception:
            return False
    
    def _test_lpr_connection(self, ip: str, port: int) -> bool:
        """Test LPR connection to printer"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                result = sock.connect_ex((ip, port))
                return result == 0
        except Exception:
            return False
    
    def _test_wsd_connection(self, ip: str, port: int) -> bool:
        """Test WSD connection to printer"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                result = sock.connect_ex((ip, port))
                return result == 0
        except Exception:
            return False
    
    def _should_attempt_reconnection(self, status: PrinterStatus) -> bool:
        """Check if we should attempt reconnection"""
        if status.consecutive_failures >= self.max_retry_attempts:
            return False
        
        # Don't retry too frequently
        if status.last_successful_connection:
            time_since_success = datetime.now() - status.last_successful_connection
            if time_since_success.total_seconds() < self.retry_delay:
                return False
        
        return True
    
    def _attempt_reconnection(self, status: PrinterStatus):
        """Attempt to reconnect to printer"""
        try:
            status.connection_attempts += 1
            
            # Test connection
            is_online = self._test_printer_connection(status)
            
            if is_online:
                # Reconnection successful
                status.is_online = True
                status.consecutive_failures = 0
                status.last_successful_connection = datetime.now()
                status.last_error = None
                
                self._notify_event(ConnectionEvent(
                    event_type='reconnected',
                    printer_name=status.name,
                    ip_address=status.ip_address,
                    timestamp=datetime.now(),
                    message=f"Printer {status.name} reconnected successfully"
                ))
            else:
                # Reconnection failed
                self._notify_event(ConnectionEvent(
                    event_type='failed',
                    printer_name=status.name,
                    ip_address=status.ip_address,
                    timestamp=datetime.now(),
                    message=f"Reconnection attempt {status.connection_attempts} failed for {status.name}",
                    error="Connection timeout"
                ))
                
        except Exception as e:
            logger.error(f"Reconnection attempt failed for {status.name}: {e}")
            self._notify_event(ConnectionEvent(
                event_type='failed',
                printer_name=status.name,
                ip_address=status.ip_address,
                timestamp=datetime.now(),
                message=f"Reconnection attempt failed for {status.name}",
                error=str(e)
            ))
    
    def _notify_event(self, event: ConnectionEvent):
        """Notify all callbacks of a connection event"""
        for callback in self.event_callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Error in connection event callback: {e}")
    
    def get_connection_metrics(self) -> Dict[str, Any]:
        """Get connection monitoring metrics"""
        with self._lock:
            total_printers = len(self.printer_statuses)
            online_printers = sum(1 for status in self.printer_statuses.values() if status.is_online)
            offline_printers = total_printers - online_printers
            
            return {
                'total_printers': total_printers,
                'online_printers': online_printers,
                'offline_printers': offline_printers,
                'uptime_percentage': (online_printers / total_printers * 100) if total_printers > 0 else 0,
                'monitoring_active': self.running
            }
    
    def force_check_printer(self, printer_name: str) -> bool:
        """Force immediate check of a specific printer"""
        with self._lock:
            status = self.printer_statuses.get(printer_name)
            if not status:
                return False
        
        try:
            self._check_printer_connection(status)
            return status.is_online
        except Exception as e:
            logger.error(f"Error in force check for {printer_name}: {e}")
            return False
