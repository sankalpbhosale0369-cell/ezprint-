import eventlet
eventlet.monkey_patch()
from flask import Flask
from flask_socketio import SocketIO

app = Flask(__name__)
socketio = SocketIO(app, message_queue="redis://localhost:6379/0", async_mode="eventlet")
print("SocketIO initialized with Redis")

@app.route("/health")
def health():
    return "OK"

if __name__ == "__main__":
    print("Starting test server...")
    socketio.run(app, host="0.0.0.0", port=5678)
