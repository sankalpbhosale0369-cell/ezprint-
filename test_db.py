import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

db_url = os.getenv("DATABASE_URL")

print("Loaded DB URL:")
print(db_url)

engine = create_engine(db_url)

with engine.connect() as conn:
    print("Connected:", conn.execute(text("SELECT 1")).scalar())
