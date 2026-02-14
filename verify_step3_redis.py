import eventlet
eventlet.monkey_patch()
from flask import Flask
from flask_socketio import SocketIO
import redis
import json

app = Flask(__name__)
socketio = SocketIO(app, message_queue="redis://localhost:6379/0", async_mode="eventlet")

def test_redis_publish():
    print("Step 3 Logic Verification: Publishing Parallel Notification...")
    # Mock payload
    payload = {
        'type': 'new_print_job',
        'job': {'job_id': 'test-123', 'status': 'Pending'}
    }
    
    # Connect to redis to check for the message
    r = redis.Redis(host='localhost', port=6379, db=0)
    p = r.pubsub()
    # Flask-SocketIO default channel is 'flask-socketio'
    p.subscribe('flask-socketio')
    print("✓ Subscribed to Redis channel 'flask-socketio'")
    
    # Emit (this should publish to Redis because message_queue is set)
    socketio.emit(
        "new_print_job",
        payload,
        room="test_shop",
        namespace="/shops"
    )
    print("✓ SocketIO emit called")
    
    # Check for message in Redis
    # We need to skip the subscribe confirmation message
    msg = p.get_message(timeout=2.0) # Subscribe confirmation
    msg = p.get_message(timeout=2.0) # Actual message
    
    if msg and msg['type'] == 'message':
        data = json.loads(msg['data'])
        print(f"✓ Redis Received Published Event: {data['method']}")
        if data['method'] == 'emit' and data['event'] == 'new_print_job':
            print("✓ Verification COMPLETE: Redis publish successful")
        else:
            print(f"❌ Unexpected Redis message: {data}")
    else:
        print("❌ No message received from Redis")

if __name__ == "__main__":
    test_redis_publish()
