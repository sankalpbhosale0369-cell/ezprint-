import eventlet
eventlet.monkey_patch()
import threading
import time

def worker():
    print("Worker started")
    time.sleep(1)
    print("Worker finished")

t = threading.Thread(target=worker)
t.start()
t.join()
print("Main finished")
