import os
from sqlalchemy import create_engine, text

# Check local SQLite
sqlite_url = "sqlite:///ezprint.db"
if os.path.exists("ezprint.db"):
    engine = create_engine(sqlite_url)
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT username, email FROM shopkeepers"))
            users = result.fetchall()
            print(f"Found {len(users)} users in SQLite:")
            for user in users:
                print(f"Username: {user[0]}, Email: {user[1]}")
    except Exception as e:
        print(f"SQLite Error: {e}")
else:
    print("ezprint.db not found")

# Check current config (Postgres)
from dotenv import load_dotenv
load_dotenv()
db_url = os.getenv("DATABASE_URL")
if db_url:
    print(f"\nChecking current DATABASE_URL: {db_url.split('@')[-1] if '@' in db_url else db_url}")
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT username, email FROM shopkeepers"))
            users = result.fetchall()
            print(f"Found {len(users)} users in current DB:")
            for user in users:
                print(f"Username: {user[0]}, Email: {user[1]}")
    except Exception as e:
        print(f"Postgres Error: {e}")
