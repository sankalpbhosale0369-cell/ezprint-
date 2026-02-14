"""
Thread-Safe WebSocket Client
============================

This module provides a thread-safe WebSocket client that runs in background threads
without interfering with Qt GUI operations. It uses pure Python threading and
avoids any Qt objects or operations.
"""

import asyncio
import websockets
import json
import logging
import threading
import time
import queue
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from shared.config import WEBSOCKET_HOST, WEBSOCKET_PORT, EZPRINT_WS_URL

logger = logging.getLogger(__name__)

@dataclass
class WebSocketMessage:
    """Thread-safe WebSocket message container"""
    message_type: str
    data: Dict[str, Any]
    timestamp: datetime

class ThreadSafeWebSocketClient:
    """
    Thread-safe WebSocket client that runs in background threads
    without touching Qt objects or GUI components
    """
    
    def __init__(self, shop_id: str, host: str = WEBSOCKET_HOST, port: int = WEBSOCKET_PORT, token: str = None):
        self.shop_id = shop_id
        self.host = host
        self.port = port
        self.token = token
        self.websocket = None
        self.running = False
        self.connected = False
        self.message_queue = queue.Queue()
        self.callback_queue = queue.Queue()
        self._lock = threading.Lock()
        self._reconnect_thread = None
        self._message_thread = None
        self._retry_count = 0
        self._max_retries = 10
        self._retry_delay = 5  # seconds
        self._last_retry_time = 0
        
    def start(self, callback: Optional[Callable[[WebSocketMessage], None]] = None):
        """Start WebSocket client in background thread"""
        # Ensure we have the loop/thread ready
        self._get_or_create_loop()
        
        with self._lock:
            if self.running:
                return
                
            self.running = True
            self.callback = callback
            
            # Start reconnection thread
            self._reconnect_thread = threading.Thread(
                target=self._reconnection_worker,
                name="WebSocketReconnect",
                daemon=True
            )
            self._reconnect_thread.start()
            
            # Start message processing thread
            self._message_thread = threading.Thread(
                target=self._message_worker,
                name="WebSocketMessage",
                daemon=True
            )
            self._message_thread.start()
            
            logger.info("Thread-safe WebSocket client started")
    
    def stop(self):
        """Stop WebSocket client"""
        with self._lock:
            if not self.running:
                return
                
            self.running = False
            self.connected = False
            
            # Close WebSocket connection with timeout
            if self.websocket:
                try:
                    # Use asyncio.run with timeout to prevent hanging
                    import asyncio
                    import concurrent.futures
                    
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(asyncio.run, self._close_websocket())
                        try:
                            future.result(timeout=1)  # 1 second timeout
                        except concurrent.futures.TimeoutError:
                            logger.warning("WebSocket close timed out, forcing close")
                            # Force close the websocket
                            if self.websocket:
                                try:
                                    asyncio.run(self.websocket.close())
                                except:
                                    pass
                                self.websocket = None
                except Exception as e:
                    logger.debug(f"Error closing WebSocket: {e}")
            
            # Stop the loop if it exists
            if hasattr(self, "_loop") and self._loop:
                try:
                    self._loop.call_soon_threadsafe(self._loop.stop)
                except:
                    pass
            
            # Wait for threads to finish with shorter timeout
            if self._reconnect_thread and self._reconnect_thread.is_alive():
                self._reconnect_thread.join(timeout=1)
            if self._message_thread and self._message_thread.is_alive():
                self._message_thread.join(timeout=1)
                
            logger.info("Thread-safe WebSocket client stopped")
    
    def send_message(self, message: Dict[str, Any]) -> bool:
        """Send message to WebSocket server (thread-safe, non-blocking)"""
        if not self.connected or not self.websocket:
            return False
        
        try:
            # Use background loop to send message to avoid blocking the caller
            loop = self._get_or_create_loop()
            asyncio.run_coroutine_threadsafe(self._send_websocket_message(message), loop)
            return True
        except Exception as e:
            logger.error(f"Error sending WebSocket message: {e}")
            return False
    
    def is_connected(self) -> bool:
        """Check if WebSocket is connected (thread-safe)"""
        with self._lock:
            return self.connected
    
    def _reconnection_worker(self):
        """Background worker for WebSocket reconnection"""
        logger.info("WebSocket reconnection worker started")
        
        while self.running:
            try:
                if not self.connected:
                    self._attempt_connection()
                
                # Wait before next attempt
                time.sleep(self._retry_delay)
                
            except Exception as e:
                logger.error(f"Error in WebSocket reconnection worker: {e}")
                time.sleep(5)  # Short delay before retry
        
        logger.info("WebSocket reconnection worker stopped")
    
    def _message_worker(self):
        """Background worker for processing WebSocket messages"""
        logger.info("WebSocket message worker started")
        
        while self.running:
            try:
                # Process messages from queue
                try:
                    message = self.message_queue.get(timeout=1)
                    self._process_message(message)
                except queue.Empty:
                    continue
                    
            except Exception as e:
                logger.error(f"Error in WebSocket message worker: {e}")
                time.sleep(1)
        
        logger.info("WebSocket message worker stopped")
    
    def _attempt_connection(self):
        """Attempt to connect to WebSocket server"""
        try:
            # Check retry limits
            current_time = time.time()
            if (self._retry_count >= self._max_retries and 
                current_time - self._last_retry_time < 60):  # Wait 1 minute after max retries
                return
            
            self._last_retry_time = current_time
            self._retry_count += 1
            
            # Attempt connection
            if self.host == WEBSOCKET_HOST and self.port == WEBSOCKET_PORT:
                uri = EZPRINT_WS_URL
            else:
                uri = f"ws://{self.host}:{self.port}"
            logger.info(f"Attempting WebSocket connection to {uri} (attempt {self._retry_count})")
            
            # Use a single background event loop to connect/reconnect
            loop = self._get_or_create_loop()
            fut = asyncio.run_coroutine_threadsafe(self._connect_websocket(uri), loop)
            try:
                # Use a reasonable timeout for the connection attempt
                fut.result(timeout=15)
            except Exception as e:
                raise e
            
        except Exception as e:
            logger.warning(f"WebSocket connection attempt {self._retry_count} failed: {e}")
            if self._retry_count >= self._max_retries:
                logger.error(f"WebSocket connection failed after {self._max_retries} attempts")
    
    async def _connect_websocket(self, uri: str):
        """Connect to WebSocket server (async)"""
        try:
            self.websocket = await websockets.connect(
                uri, 
                ping_interval=30, 
                ping_timeout=10,
                close_timeout=5
            )
            
            with self._lock:
                self.connected = True
                self._retry_count = 0  # Reset retry count on successful connection
            
            logger.info(f"WebSocket connected to {uri}")
            
            # Phase 5: Send shop registration with token
            register_msg = {
                'type': 'shop_register',
                'shop_id': self.shop_id
            }
            if self.token:
                register_msg['token'] = self.token
                
            await self._send_websocket_message(register_msg)
            
            # Start listening for messages
            await self._listen_for_messages()
            
        except Exception as e:
            with self._lock:
                self.connected = False
            raise e

    # --- Event loop management ---
    def _get_or_create_loop(self) -> asyncio.AbstractEventLoop:
        """Ensure a single asyncio event loop runs in a background thread."""
        if hasattr(self, "_loop") and self._loop and not self._loop.is_closed():
            return self._loop
        self._loop = asyncio.new_event_loop()
        def _run():
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()
        self._loop_thread = threading.Thread(target=_run, name="WS-Loop", daemon=True)
        self._loop_thread.start()
        return self._loop
    
    async def _listen_for_messages(self):
        """Listen for WebSocket messages (async)"""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    ws_message = WebSocketMessage(
                        message_type=data.get('type', 'unknown'),
                        data=data,
                        timestamp=datetime.now()
                    )
                    
                    # Add to message queue for processing
                    self.message_queue.put(ws_message)
                    
                except json.JSONDecodeError as e:
                    logger.error(f"Error decoding WebSocket message: {e}")
                except Exception as e:
                    logger.error(f"Error processing WebSocket message: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket connection closed")
            with self._lock:
                self.connected = False
        except Exception as e:
            logger.error(f"Error listening for WebSocket messages: {e}")
            with self._lock:
                self.connected = False
    
    async def _send_websocket_message(self, message: Dict[str, Any]):
        """Send message to WebSocket server (async)"""
        if self.websocket and self.connected:
            await self.websocket.send(json.dumps(message))
    
    async def _close_websocket(self):
        """Close WebSocket connection (async)"""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
    
    def _process_message(self, message: WebSocketMessage):
        """Process WebSocket message (thread-safe)"""
        try:
            # Add to callback queue for GUI thread processing
            self.callback_queue.put(message)
            
            # ALSO call the callback for immediate notification
            if self.callback:
                try:
                    self.callback(message)
                except Exception as e:
                    logger.error(f"Error in WebSocket client callback: {e}")
                
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")
    
    def get_pending_messages(self) -> list:
        """Get pending messages for GUI thread processing (thread-safe)"""
        messages = []
        try:
            while True:
                message = self.callback_queue.get_nowait()
                messages.append(message)
        except queue.Empty:
            pass
        return messages
    
    def get_connection_status(self) -> Dict[str, Any]:
        """Get connection status (thread-safe)"""
        with self._lock:
            return {
                'connected': self.connected,
                'retry_count': self._retry_count,
                'max_retries': self._max_retries,
                'running': self.running
            }

class ThreadSafeWebSocketManager:
    """
    Thread-safe WebSocket manager that coordinates with the client
    and provides a clean interface for the GUI
    """
    
    def __init__(self, shop_id: str, host: str = WEBSOCKET_HOST, port: int = WEBSOCKET_PORT, token: str = None):
        self.client = ThreadSafeWebSocketClient(shop_id, host, port, token)
        self.message_callbacks = []
        self._lock = threading.Lock()
    
    @property
    def running(self):
        """Get the running status from the underlying client"""
        return self.client.running
        
    def start(self, callback: Optional[Callable[[WebSocketMessage], None]] = None):
        """Start WebSocket client"""
        if callback:
            self.message_callbacks.append(callback)
        self.client.start(callback=self._on_message_received)
    
    def stop(self):
        """Stop WebSocket client"""
        self.client.stop()
        with self._lock:
            self.message_callbacks.clear()
    
    def _on_message_received(self, message: WebSocketMessage):
        """Callback for received messages (thread-safe)"""
        with self._lock:
            for callback in self.message_callbacks:
                try:
                    callback(message)
                except Exception as e:
                    logger.error(f"Error in WebSocket message callback: {e}")
    
    def send_message(self, message: Dict[str, Any]) -> bool:
        """Send message to WebSocket server"""
        return self.client.send_message(message)
    
    def is_connected(self) -> bool:
        """Check if WebSocket is connected"""
        return self.client.is_connected()
    
    def report_job_status(self, job_id: str, status: str, progress: int = 0, details: str = '', printer_name: str = None) -> bool:
        """
        Report job status using event-based types (Phase 5)
        
        Args:
            job_id: Unique job identifier
            status: Printing/Completed/Failed (will be mapped to events)
            progress: 0-100
            details: Error message or details
            printer_name: Name of the printer used
        """
        # Map DB status to event types
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
        """Get connection status"""
        return self.client.get_connection_status()
    
    def add_message_callback(self, callback: Callable[[WebSocketMessage], None]):
        """Add message callback"""
        with self._lock:
            self.message_callbacks.append(callback)
    
    def remove_message_callback(self, callback: Callable[[WebSocketMessage], None]):
        """Remove message callback"""
        with self._lock:
            if callback in self.message_callbacks:
                self.message_callbacks.remove(callback)
