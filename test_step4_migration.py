import asyncio
import socketio
import jwt
from datetime import datetime, timedelta
import os
import sys

# Add path for imports
sys.path.append(os.path.join(os.getcwd(), "web_interface"))

# Constants for testing
SECRET_KEY = os.getenv('SECRET_KEY', 'ezprint-dev-secret-key-change-in-production')
WEB_URL = "http://localhost:5025"
SHOP_ID = "authenticated_shop_1"

def generate_test_token(shop_id, username="testuser"):
    payload = {
        "shop_id": shop_id,
        "username": username,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=8)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

async def test_migration_step_4():
    print(f"--- Starting Phase 1 Step 4 Test ---")
    
    sio = socketio.AsyncClient()
    sio_events = []

    @sio.on("registration_confirmed", namespace="/shops")
    async def on_reg_confirmed(data):
        print(f"✓ Received registration_confirmed: {data}")
        sio_events.append(data)

    @sio.on("disconnect", namespace="/shops")
    async def on_disconnect():
        print("ℹ SocketIO Disconnected from /shops")

    # 1. Test connection
    try:
        await sio.connect(WEB_URL, namespaces=["/shops"])
        print("✓ Connected to /shops namespace")
    except Exception as e:
        print(f"❌ Failed to connect to {WEB_URL}/shops: {e}")
        return

    # 2. Test registration with valid token
    token = generate_test_token(SHOP_ID)
    print(f"--- Registering shop {SHOP_ID} with valid JWT ---")
    await sio.emit("register_shop", {"token": token}, namespace="/shops")
    
    # Wait for confirmation
    for _ in range(50):
        if sio_events:
            break
        await asyncio.sleep(0.1)
    
    if sio_events:
        print("✓ Authenticated registration SUCCESSFUL")
    else:
        print("❌ Authenticated registration FAILED (No confirmation received)")

    # 3. Test room isolation (optional but good)
    # We would need another client to verify room isolation, 
    # but for Step 4, joining the room and getting confirmation is the core task.

    await sio.disconnect()
    
    print("\n--- TEST SUMMARY ---")
    if sio_events:
        print("RESULT: SUCCESS - SocketIO JWT Authentication and Room Joining verified")
    else:
        print("RESULT: FAILED")

if __name__ == "__main__":
    # Note: This test requires a running server with Redis
    asyncio.run(test_migration_step_4())
