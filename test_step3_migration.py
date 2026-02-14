import asyncio
import websockets
import json
import socketio
import requests
import time
import os

# Configuration
WEB_URL = "http://localhost:5010"
WS_URL = "ws://localhost:8765"
SHOP_ID = "shop_test_1"

async def test_migration_step_3():
    print("--- Starting Phase 1 Step 3 Test ---")
    
    # 1. Setup SocketIO Client
    sio = socketio.AsyncClient()
    sio_received = []

    @sio.on("new_print_job", namespace="/shops")
    async def on_new_job(data):
        print(f"DEBUG: SocketIO received new_print_job: {data['job']['job_id']}")
        sio_received.append(data)

    await sio.connect(WEB_URL, namespaces=["/shops"])
    print("✓ SocketIO connected to /shops")

    # 2. Setup Legacy WebSocket Client
    legacy_received = []
    async with websockets.connect(WS_URL) as ws:
        print("✓ Legacy WebSocket connected")
        # Register shop
        await ws.send(json.dumps({
            "type": "shop_register",
            "shop_id": SHOP_ID
        }))
        reg_resp = await ws.recv()
        print(f"✓ Legacy Registration Response: {reg_resp}")

        # 3. Trigger Job Upload
        print("--- Triggering Job Upload ---")
        # Create a dummy file
        with open("test_upload.txt", "w") as f:
            f.write("Migration Test Document Content")
        
        files = {'file': open('test_upload.txt', 'rb')}
        data = {
            'shop_id': SHOP_ID,
            'copies': '1',
            'color_mode': 'Black & White'
        }
        
        response = requests.post(f"{WEB_URL}/api/upload", files=files, data=data)
        print(f"✓ Upload Status Code: {response.status_code}")
        print(f"✓ Upload Response: {response.json()}")
        
        if response.status_code == 200:
            job_id = response.json().get('job_id')
            
            # 4. Wait for notifications on both sides
            print("Waiting for notifications...")
            
            # Check legacy
            try:
                # We expect registration_confirmed first, then new_print_job
                # Actually registration_confirmed was handled above.
                legacy_msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                legacy_data = json.loads(legacy_msg)
                print(f"✓ Legacy WebSocket Received: {legacy_data.get('type')}")
                legacy_received.append(legacy_data)
            except Exception as e:
                print(f"❌ Legacy WebSocket timeout/error: {e}")

            # Check SocketIO
            # Give it a bit more time for Redis propagation
            for _ in range(50):
                if sio_received:
                    break
                await asyncio.sleep(0.1)
            
            if sio_received:
                print(f"✓ SocketIO Received Notification")
            else:
                print(f"❌ SocketIO did NOT receive notification")

    await sio.disconnect()
    
    # Summary
    print("\n--- TEST SUMMARY ---")
    if legacy_received and sio_received:
        print("RESULT: SUCCESS - Parallel notifications confirmed")
    else:
        print(f"RESULT: FAILED - Legacy: {len(legacy_received)}, SocketIO: {len(sio_received)}")
    
    # Cleanup
    if os.path.exists("test_upload.txt"):
        os.remove("test_upload.txt")

if __name__ == "__main__":
    asyncio.run(test_migration_step_3())
