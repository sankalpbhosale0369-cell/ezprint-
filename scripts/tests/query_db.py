
import sqlite3
import os

db_path = r'c:\Users\Asus\Desktop\success_MVP_7\ezprint.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT printer_name, is_active FROM printers")
    rows = cursor.fetchall()
    print("Printers (Name, Is_Active):")
    for row in rows:
        print(row)
    conn.close()
else:
    print(f"Database not found at {db_path}")
