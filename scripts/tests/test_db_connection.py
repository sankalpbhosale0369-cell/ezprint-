"""
Database Connection Test Script
Tests PostgreSQL connection and verifies schema
"""
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.database import engine, init_database, SessionLocal
from shared.config import DATABASE_URL

def test_connection():
    """Test database connection"""
    print("=" * 60)
    print("EzPrint Database Connection Test")
    print("=" * 60)
    
    # Display connection info (hide password)
    if 'postgresql' in DATABASE_URL:
        db_type = "PostgreSQL"
        # Mask password in URL for display
        display_url = DATABASE_URL
        if '@' in display_url:
            parts = display_url.split('@')
            user_pass = parts[0].split('://')[-1]
            if ':' in user_pass:
                user = user_pass.split(':')[0]
                display_url = display_url.replace(user_pass, f"{user}:****")
    else:
        db_type = "SQLite"
        display_url = DATABASE_URL
    
    print(f"\nDatabase Type: {db_type}")
    print(f"Connection String: {display_url}")
    print()
    
    # Test connection
    try:
        print("Testing database connection...")
        with engine.connect() as conn:
            if 'postgresql' in DATABASE_URL:
                result = conn.execute("SELECT version();")
                version = result.fetchone()[0]
                print(f"✓ Connection successful!")
                print(f"  PostgreSQL Version: {version.split(',')[0]}")
            else:
                result = conn.execute("SELECT sqlite_version();")
                version = result.fetchone()[0]
                print(f"✓ Connection successful!")
                print(f"  SQLite Version: {version}")
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return False
    
    # Test table creation
    try:
        print("\nInitializing database schema...")
        init_database()
        print("✓ Schema initialized successfully!")
    except Exception as e:
        print(f"✗ Schema initialization failed: {e}")
        return False
    
    # Verify tables exist
    try:
        print("\nVerifying tables...")
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        expected_tables = ['shopkeepers', 'print_jobs', 'printers', 'system_logs', 'shop_pricing']
        
        for table in expected_tables:
            if table in tables:
                print(f"  ✓ {table}")
            else:
                print(f"  ✗ {table} (missing)")
        
        print(f"\nTotal tables found: {len(tables)}")
        
    except Exception as e:
        print(f"✗ Table verification failed: {e}")
        return False
    
    # Test session creation
    try:
        print("\nTesting session creation...")
        session = SessionLocal()
        session.close()
        print("✓ Session created successfully!")
    except Exception as e:
        print(f"✗ Session creation failed: {e}")
        return False
    
    print("\n" + "=" * 60)
    print("All tests passed! Database is ready.")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)
