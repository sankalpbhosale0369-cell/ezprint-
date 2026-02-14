"""
WebSocket client for real-time communication
"""
import asyncio
import websockets
import json
import logging
from datetime import datetime
import sys
import os

# Add parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import WEBSOCKET_HOST, WEBSOCKET_PORT, EZPRINT_WS_URL
from shared.database import PrintJob, SessionLocal
from shared.global_error_handler import (
    global_error_handler, safe_execute, safe_thread_action
)

logger = logging.getLogger(__name__)

class WebSocketClient:
    def __init__(self, shop_id, callback=None):
        self.shop_id = shop_id
        self.callback = callback
        self.websocket = None
        self.running = False
        self.db = SessionLocal()
    
    @safe_thread_action("WEBSOCKET_CONNECT")
    async def connect(self):
        """Connect to WebSocket server with retry logic"""
        uri = EZPRINT_WS_URL
        retry_count = 0
        max_retries = 3  # Reduced retries to prevent spam
        base_delay = 10  # Increased initial delay
        last_error_time = 0
        error_throttle = 30  # Only log errors every 30 seconds
        
        while self.running and retry_count < max_retries:
            try:
                self.websocket = await websockets.connect(uri, ping_interval=30, ping_timeout=10)
                self.running = True
                
                # Send shop identification
                await self.send_message({
                    'type': 'shop_register',
                    'shop_id': self.shop_id
                })
                
                logger.info(f"WebSocket connected for shop {self.shop_id}")
                # Notify UI
                if self.callback:
                    try:
                        self.callback({'type': 'ws_status', 'status': 'connected'})
                    except Exception:
                        pass
                
                # Reset retry count on successful connection
                retry_count = 0
                
                # Start listening for messages
                await self.listen()
                
                # If listen returns (disconnected), increment retry and try again
                retry_count += 1
                if retry_count < max_retries:
                    delay = min(base_delay * (2 ** (retry_count - 1)), 60)  # Cap at 60 seconds
                    current_time = asyncio.get_event_loop().time()
                    if current_time - last_error_time > error_throttle:
                        logger.warning(f"WebSocket disconnected. Retrying in {delay} seconds... (Attempt {retry_count}/{max_retries})")
                        last_error_time = current_time
                    if self.callback:
                        try:
                            self.callback({'type': 'ws_status', 'status': 'retrying', 'attempt': retry_count, 'max': max_retries})
                        except Exception:
                            pass
                    await asyncio.sleep(delay)
                    continue
                else:
                    break
                
            except ConnectionRefusedError:
                retry_count += 1
                current_time = asyncio.get_event_loop().time()
                if retry_count < max_retries:
                    delay = min(base_delay * (2 ** (retry_count - 1)), 60)  # Cap at 60 seconds
                    if current_time - last_error_time > error_throttle:
                        logger.warning(f"WebSocket server not available. Retrying in {delay} seconds... (Attempt {retry_count}/{max_retries})")
                        last_error_time = current_time
                    if self.callback:
                        try:
                            self.callback({'type': 'ws_status', 'status': 'retrying', 'attempt': retry_count, 'max': max_retries})
                        except Exception:
                            pass
                    await asyncio.sleep(delay)
                else:
                    if current_time - last_error_time > error_throttle:
                        logger.error("WebSocket connection failed after maximum retries. Server may be down.")
                        last_error_time = current_time
                    self.running = False
                    if self.callback:
                        try:
                            self.callback({'type': 'ws_status', 'status': 'failed'})
                        except Exception:
                            pass
                    break
                    
            except Exception as e:
                retry_count += 1
                current_time = asyncio.get_event_loop().time()
                if retry_count < max_retries:
                    delay = min(base_delay, 30)  # Cap at 30 seconds for general errors
                    if current_time - last_error_time > error_throttle:
                        logger.warning(f"WebSocket connection error: {e}. Retrying in {delay} seconds... (Attempt {retry_count}/{max_retries})")
                        last_error_time = current_time
                    if self.callback:
                        try:
                            self.callback({'type': 'ws_status', 'status': 'retrying', 'attempt': retry_count, 'max': max_retries})
                        except Exception:
                            pass
                    await asyncio.sleep(delay)
                else:
                    if current_time - last_error_time > error_throttle:
                        logger.error(f"WebSocket connection failed after maximum retries: {e}")
                        last_error_time = current_time
                    self.running = False
                    if self.callback:
                        try:
                            self.callback({'type': 'ws_status', 'status': 'failed'})
                        except Exception:
                            pass
                    break
    
    async def send_message(self, message):
        """Send message to server"""
        try:
            if self.websocket and not self.websocket.closed:
                await self.websocket.send(json.dumps(message))
        except Exception as e:
            logger.error(f"Error sending message: {e}")
    
    async def listen(self):
        """Listen for incoming messages"""
        try:
            while self.running:
                message = await self.websocket.recv()
                data = json.loads(message)
                await self.handle_message(data)
                
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket connection closed")
            # Keep running True so connect() loop can retry and inform UI
            if self.callback:
                try:
                    self.callback({'type': 'ws_status', 'status': 'disconnected'})
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Error listening for messages: {e}")
            if self.callback:
                try:
                    self.callback({'type': 'ws_status', 'status': 'disconnected'})
                except Exception:
                    pass
    
    async def handle_message(self, data):
        """Handle incoming messages"""
        try:
            message_type = data.get('type')
            
            if message_type == 'new_print_job':
                await self.handle_new_print_job(data)
            elif message_type == 'job_update':
                await self.handle_job_update(data)
            elif message_type == 'ping':
                await self.send_message({'type': 'pong'})
            
            # Call callback if provided
            if self.callback:
                self.callback(data)
                
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def handle_new_print_job(self, data):
        """Handle new print job notification"""
        try:
            job_data = data.get('job')
            if job_data:
                # Update job status in database
                job = self.db.query(PrintJob).filter(
                    PrintJob.job_id == job_data['job_id']
                ).first()
                
                if job:
                    job.status = 'Processing'
                    job.started_at = datetime.utcnow()
                    self.db.commit()
                    
                    logger.info(f"New print job received: {job_data['job_id']}")
                    
        except Exception as e:
            logger.error(f"Error handling new print job: {e}")
    
    async def handle_job_update(self, data):
        """Handle job status update"""
        try:
            job_id = data.get('job_id')
            status = data.get('status')
            
            if job_id and status:
                job = self.db.query(PrintJob).filter(
                    PrintJob.job_id == job_id
                ).first()
                
                if job:
                    job.status = status
                    # [LIFECYCLE PATCH]
                    if status in ['Completed', 'Failed', 'Cancelled'] and not job.completed_at:
                        job.completed_at = datetime.utcnow()
                    
                    if status == 'Failed':
                        job.error_message = data.get('error_message', 'Unknown error')
                    
                    self.db.commit()
                    
                    logger.info(f"Job {job_id} status updated to {status}")
                    
        except Exception as e:
            logger.error(f"Error handling job update: {e}")
    
    async def send_job_status(self, job_id, status, error_message=None):
        """Send job status update to server"""
        try:
            message = {
                'type': 'job_status_update',
                'job_id': job_id,
                'status': status,
                'shop_id': self.shop_id
            }
            
            if error_message:
                message['error_message'] = error_message
            
            await self.send_message(message)
            
        except Exception as e:
            logger.error(f"Error sending job status: {e}")
    
    def send_status_update(self, job_id, status, progress, details):
        """Send real-time status update (synchronous wrapper)"""
        try:
            if self.websocket and not self.websocket.closed:
                message = {
                    'type': 'job_status_update',
                    'job_id': job_id,
                    'status': status,
                    'progress': progress,
                    'details': details,
                    'shop_id': self.shop_id
                }
                # Use asyncio to send in the event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.send_message(message))
                loop.close()
        except Exception as e:
            logger.error(f"Error sending status update: {e}")
    
    def disconnect(self):
        """Disconnect from WebSocket"""
        self.running = False
        try:
            if self.websocket and not self.websocket.closed:
                asyncio.create_task(self.websocket.close())
        except Exception as e:
            logger.warning(f"Error closing WebSocket: {e}")
        finally:
            try:
                self.db.close()
            except Exception as e:
                logger.warning(f"Error closing database connection: {e}")
    
    @safe_thread_action("WEBSOCKET_START")
    def start(self):
        """Start WebSocket client"""
        try:
            self.running = True
            asyncio.run(self.connect())
        except Exception as e:
            logger.error(f"WebSocket client failed to start: {e}")
            self.running = False
            # Notify UI of failure
            if self.callback:
                try:
                    self.callback({'type': 'ws_status', 'status': 'failed'})
                except Exception:
                    pass
    
    def stop(self):
        """Stop WebSocket client"""
        self.disconnect()
