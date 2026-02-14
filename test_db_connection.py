"""
Database connection test utility for EzPrint migration
"""
import sys
import os
from sqlalchemy import create_engine, text

# Add parent directory to path to import shared config
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from shared.config import DATABASE_URL

def test_connection():
    print("Testing Database Connection...")
    
    if not DATABASE_URL or "YOUR_DATABASE_URL_HERE" in DATABASE_URL:
        print("[-] ERROR: DATABASE_URL is not set or still contains placeholder.")
        print("Please update your .env file with a valid connection string.")
        return False

    # Mask sensitive info for logging
    db_type = DATABASE_URL.split(":")[0]
    print(f"[+] Attempting to connect to: {db_type}://***@***")

    try:
        engine = create_engine(DATABASE_URL)
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))
            if result.scalar() == 1:
                print("[+] SUCCESS: Database connection established!")
                return True
            else:
                print("[-] FAILED: Connection established but query failed.")
                return False
    except Exception as e:
        print(f"[-] ERROR: Could not connect to database.")
        print(f"Details: {str(e)}")
        return False

if __name__ == "__main__":
    test_connection()
