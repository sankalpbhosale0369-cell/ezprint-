"""
Test script for Step 5: SocketIO client-side migration.
This script tests the SocketIOClient without the PyQt GUI.
"""
import sys
import os
import time
import logging
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from shopkeeper_app.socketio_client import SocketIOClient
from shared.config import SECRET_KEY
import jwt

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TestClient")

def generate_test_token(shop_id="TEST_SHOP"):
    payload = {
        'shop_id': shop_id,
        'exp': datetime.utcnow().timestamp() + 3600
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')

def test_callback(data):
    logger.info(f"CALLBACK RECEIVED: {data}")

def main():
    server_url = "http://localhost:5000" # Default Flask port
    shop_id = "TEST_SHOP"
    token = generate_test_token(shop_id)
    
    logger.info(f"Starting test with shop_id={shop_id}")
    client = SocketIOClient(
        server_url=server_url,
        shop_id=shop_id,
        token=token,
        callback=test_callback
    )
    
    client.start()
    
    # Wait for connection and registration
    time.sleep(5)
    
    if client.is_connected():
        logger.info("Connection successful!")
        
        # Test status reporting
        logger.info("Testing status report...")
        success = client.emit('job_status_update', {
            'job_id': 'TEST_JOB_123',
            'status': 'Printing',
            'progress': 50
        })
        logger.info(f"Emit success: {success}")
        
    else:
        logger.error("Connection failed! Make sure the server is running on port 5025.")
        logger.info("Start the server using: python web_interface/app.py (ensure port is 5025 in app.py or env)")

    # Wait a bit more for any server responses
    time.sleep(2)
    
    logger.info("Stopping client...")
    client.stop()
    logger.info("Test finished.")

if __name__ == "__main__":
    main()
