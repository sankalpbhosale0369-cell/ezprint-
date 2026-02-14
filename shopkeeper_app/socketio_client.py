"""
SocketIO client for real-time communication in the shopkeeper application.
"""
import socketio
import logging
import time
import threading
from datetime import datetime
from typing import Optional, Callable, Dict, Any

logger = logging.getLogger(__name__)

class SocketIOClient:
    """
    SocketIO client with automatic reconnection and JWT authentication.
    """
    def __init__(self, server_url: str, shop_id: str, token: str, callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.server_url = server_url
        self.shop_id = shop_id
        self.token = token
        self.callback = callback
        self.running = False
        self.connected = False
        
        # Initialize SocketIO Client
        # reconnection=True is default, but we can tune it
        self.sio = socketio.Client(
            reconnection=True,
            reconnection_attempts=0, # Infinite
            reconnection_delay=1,
            reconnection_delay_max=30,
            logger=False,
            engineio_logger=False
        )
        
        self._setup_handlers()

    def _setup_handlers(self):
        @self.sio.on('connect', namespace='/shops')
        def on_connect():
            logger.info(f"SocketIO connected to {self.server_url} [/shops]")
            self.connected = True
            # Objective 4: Emit register_shop with token immediately after connection
            self.sio.emit('register_shop', {'token': self.token}, namespace='/shops')

        @self.sio.on('connect_error', namespace='/shops')
        def on_connect_error(data):
            logger.warning(f"SocketIO connection error: {data}")
            self.connected = False
            if self.callback:
                self.callback({'type': 'ws_status', 'status': 'disconnected'})

        @self.sio.on('disconnect', namespace='/shops')
        def on_disconnect():
            logger.info("SocketIO disconnected from /shops")
            self.connected = False
            if self.callback:
                self.callback({'type': 'ws_status', 'status': 'disconnected'})

        @self.sio.on('registration_confirmed', namespace='/shops')
        def on_registration_confirmed(data):
            logger.info(f"SocketIO registration confirmed: {data}")
            if self.callback:
                if isinstance(data, dict) and 'type' not in data:
                    data['type'] = 'registration_confirmed'
                # Map to status event for UI
                self.callback({'type': 'ws_status', 'status': 'connected'})
                self.callback(data)

        @self.sio.on('new_print_job', namespace='/shops')
        def on_new_print_job(data):
            logger.info(f"SocketIO received new_print_job: {data.get('job', {}).get('job_id')}")
            if self.callback:
                if isinstance(data, dict) and 'type' not in data:
                    data['type'] = 'new_print_job'
                self.callback(data)

        @self.sio.on('*', namespace='/shops')
        def catch_all(event, data):
            logger.debug(f"SocketIO received event [{event}]: {data}")
            if self.callback:
                if isinstance(data, dict):
                    if 'type' not in data:
                        data['type'] = event
                    self.callback(data)
                else:
                    self.callback({'type': event, 'data': data})

    def start(self):
        """Start the client and connect to the server"""
        if self.running:
            return
            
        self.running = True
        # Use a background thread for the connection loop to avoid blocking
        threading.Thread(target=self._connection_loop, name="SocketIOConnectionLoop", daemon=True).start()

    def _connection_loop(self):
        """Infinite connection loop for initial and subsequent connection attempts"""
        retry_delay = 1
        max_delay = 30
        
        while self.running and not self.connected:
            try:
                logger.info(f"Attempting SocketIO connection to {self.server_url} namespace /shops")
                self.sio.connect(
                    self.server_url,
                    namespaces=['/shops'],
                    wait_timeout=10
                )
                # If connect returns, it's successful (or already connecting)
                # reconnection=True handles lost connections from here
                break
            except Exception as e:
                logger.warning(f"SocketIO connection failed: {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_delay)


    def stop(self):
        """Stop the client and disconnect"""
        self.running = False
        try:
            if self.sio.connected:
                self.sio.disconnect()
        except Exception as e:
            logger.warning(f"Error during SocketIO disconnect: {e}")

    def emit(self, event: str, data: Any):
        """Send an event to the server"""
        try:
            if self.sio.connected:
                self.sio.emit(event, data, namespace='/shops')
                return True
            return False
        except Exception as e:
            logger.error(f"Error emitting SocketIO event {event}: {e}")
            return False

    def is_connected(self):
        return self.sio.connected
