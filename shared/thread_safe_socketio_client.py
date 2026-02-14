"""
Thread-Safe SocketIO Client Wrapper
===================================

This module provides a thread-safe SocketIO client that coordinates with 
the SocketIOClient class and provides a clean queue-based interface for the PyQt GUI.
"""

import logging
import threading
import queue
import time
from typing import Optional, Callable, Dict, Any
from datetime import datetime
from shopkeeper_app.socketio_client import SocketIOClient
from shared.config import EZPRINT_BASE_URL

logger = logging.getLogger(__name__)

class SocketIOMessage:
    """Thread-safe SocketIO message container"""
    def __init__(self, message_type: str, data: Dict[str, Any], timestamp: datetime = None):
        self.message_type = message_type
        self.data = data
        self.timestamp = timestamp or datetime.now()

class ThreadSafeSocketIOManager:
    """
    Thread-safe SocketIO manager that coordinates with the client
    and provides a clean interface for the GUI (matches ThreadSafeWebSocketManager API).
    """
    
    def __init__(self, shop_id: str, server_url: str = EZPRINT_BASE_URL, token: str = None):
        self.shop_id = shop_id
        self.server_url = server_url
        self.token = token
        self.client = None
        self.message_callbacks = []
        self._lock = threading.Lock()
        self.running = False
        
    def start(self, callback: Optional[Callable[[SocketIOMessage], None]] = None):
        """Start SocketIO client in a background thread"""
        with self._lock:
            if self.running:
                return
            self.running = True
            if callback:
                self.message_callbacks.append(callback)
                
            # Initialize the core client
            self.client = SocketIOClient(
                server_url=self.server_url,
                shop_id=self.shop_id,
                token=self.token,
                callback=self._on_client_callback
            )
            
            # Start connection in a background thread (though sio.connect is usually fast)
            threading.Thread(
                target=self.client.start,
                name="SocketIOStart",
                daemon=True
            ).start()
            
            logger.info("Thread-safe SocketIO manager started")

    def stop(self):
        """Stop SocketIO client"""
        with self._lock:
            if not self.running:
                return
            self.running = False
            if self.client:
                self.client.stop()
            self.message_callbacks.clear()
            logger.info("Thread-safe SocketIO manager stopped")

    def _on_client_callback(self, data: Dict[str, Any]):
        """Internal callback from SocketIOClient to relay to GUI queue/callbacks"""
        message_type = data.get('type', 'unknown')
        msg = SocketIOMessage(message_type, data)
        
        with self._lock:
            for callback in self.message_callbacks:
                try:
                    callback(msg)
                except Exception as e:
                    logger.error(f"Error in SocketIO manager callback: {e}")

    def send_message(self, message: Dict[str, Any]) -> bool:
        """Send message (event) to server"""
        if not self.client:
            return False
        event_type = message.get('type', 'message')
        return self.client.emit(event_type, message)

    def is_connected(self) -> bool:
        """Check if connected"""
        if self.client:
            return self.client.is_connected()
        return False

    def report_job_status(self, job_id: str, status: str, progress: int = 0, details: str = '', printer_name: str = None) -> bool:
        """
        Report job status using event-based types
        """
        event_map = {
            'Printing': 'printing_started',
            'Completed': 'printing_completed',
            'Failed': 'printing_failed'
        }
        event_type = event_map.get(status, 'job_status_update')
        
        message = {
            'type': event_type,
            'job_id': job_id,
            'status': status,
            'progress': progress,
            'details': details,
            'printer_name': printer_name,
            'timestamp': datetime.now().isoformat()
        }
        
        return self.send_message(message)

    def get_connection_status(self) -> Dict[str, Any]:
        """Get connection status (matches old API)"""
        return {
            'connected': self.is_connected(),
            'running': self.running
        }

    def add_message_callback(self, callback: Callable[[SocketIOMessage], None]):
        """Add message callback"""
        with self._lock:
            self.message_callbacks.append(callback)

    def remove_message_callback(self, callback: Callable[[SocketIOMessage], None]):
        """Remove message callback"""
        with self._lock:
            if callback in self.message_callbacks:
                self.message_callbacks.remove(callback)
