"""
Database models and connection for EzPrint MVP
"""
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, Float, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from shared.config import DATABASE_URL
import uuid

Base = declarative_base()

class Shopkeeper(Base):
    """Shopkeeper account model"""
    __tablename__ = 'shopkeepers'
    
    id = Column(Integer, primary_key=True)
    shop_id = Column(String(36), unique=True, nullable=False)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    shop_name = Column(String(100), nullable=False)
    shop_address = Column(String(255), nullable=True)
    contact_number = Column(String(20), nullable=True)
    shopkeeper_name = Column(String(100), nullable=True)
    qr_code_path = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    otp_code = Column(String(6), nullable=True)
    otp_expires_at = Column(DateTime, nullable=True)
    
    def __init__(self, username, email, password_hash, shop_name):
        self.shop_id = str(uuid.uuid4())
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.shop_name = shop_name

class PrintJob(Base):
    """Print job model"""
    __tablename__ = 'print_jobs'
    
    id = Column(Integer, primary_key=True)
    job_id = Column(String(36), unique=True, nullable=False)
    shop_id = Column(String(36), nullable=False)
    customer_ip = Column(String(45), nullable=True)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=False)
    file_type = Column(String(10), nullable=False)
    
    # Print settings
    page_range = Column(String(50), nullable=True)
    copies = Column(Integer, default=1)
    page_size = Column(String(20), default='A4')
    orientation = Column(String(20), default='Portrait')
    print_side = Column(String(20), default='Single')
    color_mode = Column(String(20), default='Black & White')
    layout_pages = Column(Integer, default=1)  # Pages per sheet (1, 2, 4, etc.)
    layout_type = Column(String(20), default='normal')  # normal, 2up, 4up, etc.
    total_pages = Column(Integer, nullable=True)  # Numeric total pages calculated during upload
    
    # Job status
    status = Column(String(20), default='Pending')  # Pending, Processing, Printing, Completed, Failed
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Pricing
    amount = Column(Float, nullable=True)  # Total price for this print job
    
    # Asset Management
    cloudinary_public_id = Column(String(255), nullable=True)
    preview_paths = Column(Text, nullable=True)  # Serialized JSON list of preview paths
    assets_deleted = Column(Boolean, default=False)
    assets_delete_scheduled = Column(Boolean, default=False)
    assets_delete_attempted_at = Column(DateTime, nullable=True)
    
    def __init__(self, shop_id, filename, file_path, file_size, file_type, **kwargs):
        self.job_id = str(uuid.uuid4())
        self.shop_id = shop_id
        self.filename = filename
        self.file_path = file_path
        self.file_size = file_size
        self.file_type = file_type
        
        # Set print settings
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

class Printer(Base):
    """Printer configuration model"""
    __tablename__ = 'printers'
    
    id = Column(Integer, primary_key=True)
    shop_id = Column(String(36), nullable=False)
    printer_name = Column(String(100), nullable=False)
    printer_id = Column(String(100), nullable=False)
    is_default = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class SystemLog(Base):
    """System logging model"""
    __tablename__ = 'system_logs'
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    level = Column(String(20), nullable=False)  # INFO, WARNING, ERROR, DEBUG
    component = Column(String(50), nullable=False)  # shopkeeper_app, web_interface, etc.
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)

class ShopPricing(Base):
    """Shop pricing configuration model"""
    __tablename__ = 'shop_pricing'
    
    id = Column(Integer, primary_key=True)
    shop_id = Column(String(36), unique=True, nullable=False)
    bw_single = Column(Float, default=2.0)  # Black & White single-sided per page
    bw_double = Column(Float, default=1.5)  # Black & White double-sided per page
    color_single = Column(Float, default=10.0)  # Color single-sided per page
    color_double = Column(Float, default=8.0)  # Color double-sided per page
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __init__(self, shop_id, bw_single=2.0, bw_double=1.5, color_single=10.0, color_double=8.0):
        self.shop_id = shop_id
        self.bw_single = bw_single
        self.bw_double = bw_double
        self.color_single = color_single
        self.color_double = color_double

class License(Base):
    """Device licensing model for trial/activation tracking"""
    __tablename__ = 'licenses'
    
    device_id = Column(String(64), primary_key=True)
    shop_id = Column(String(36), nullable=True)
    email = Column(String(255), nullable=True)
    shop_name = Column(String(255), nullable=True)
    status = Column(String(20), default='trial')  # trial | active | expired | blocked
    trial_start = Column(DateTime(timezone=True), default=func.now())
    trial_end = Column(DateTime(timezone=True))
    activated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    notes = Column(Text, nullable=True)

# Database connection with PostgreSQL-optimized settings
engine = create_engine(
    DATABASE_URL, 
    echo=False,
    pool_pre_ping=True,  # Verify connections before using them
    pool_recycle=3600,   # Recycle connections after 1 hour
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_tables():
    """Create all database tables"""
    Base.metadata.create_all(bind=engine)

def migrate_schema():
    """
    Database-agnostic migration to ensure new columns exist.
    - Adds missing columns to existing tables safely with defaults.
    - Handles cases where tables might not exist yet.
    - Works with both SQLite and PostgreSQL.
    """
    try:
        from sqlalchemy import inspect, text
        
        inspector = inspect(engine)
        dialect_name = engine.dialect.name
        
        # Check if shopkeepers table exists
        if 'shopkeepers' in inspector.get_table_names():
            # Get existing columns
            existing_cols = {col['name'] for col in inspector.get_columns('shopkeepers')}
            
            # Define columns to add if missing
            columns_to_add = []
            if 'shop_address' not in existing_cols:
                columns_to_add.append(('shop_address', 'VARCHAR(255)'))
            if 'contact_number' not in existing_cols:
                columns_to_add.append(('contact_number', 'VARCHAR(20)'))
            if 'shopkeeper_name' not in existing_cols:
                columns_to_add.append(('shopkeeper_name', 'VARCHAR(100)'))
            if 'otp_code' not in existing_cols:
                columns_to_add.append(('otp_code', 'VARCHAR(6)'))
            if 'otp_expires_at' not in existing_cols:
                columns_to_add.append(('otp_expires_at', 'TIMESTAMP'))
            
            # Add missing columns
            with engine.connect() as conn:
                for col_name, col_type in columns_to_add:
                    try:
                        conn.execute(text(f"ALTER TABLE shopkeepers ADD COLUMN {col_name} {col_type}"))
                        conn.commit()
                        print(f"Added {col_name} column to shopkeepers table")
                    except Exception as e:
                        print(f"Warning adding {col_name} to shopkeepers: {e}")
        else:
            print("Shopkeepers table does not exist yet, will be created with new schema")
        
        # Check if print_jobs table exists
        if 'print_jobs' in inspector.get_table_names():
            existing_cols = {col['name'] for col in inspector.get_columns('print_jobs')}
            
            # Define columns to add if missing
            columns_to_add = []
            if 'layout_pages' not in existing_cols:
                columns_to_add.append(('layout_pages', 'INTEGER DEFAULT 1'))
            if 'layout_type' not in existing_cols:
                if dialect_name == 'postgresql':
                    columns_to_add.append(('layout_type', "VARCHAR(20) DEFAULT 'normal'"))
                else:
                    columns_to_add.append(('layout_type', "TEXT DEFAULT 'normal'"))
            if 'amount' not in existing_cols:
                if dialect_name == 'postgresql':
                    columns_to_add.append(('amount', 'REAL'))
                else:
                    columns_to_add.append(('amount', 'REAL'))
            if 'total_pages' not in existing_cols:
                columns_to_add.append(('total_pages', 'INTEGER'))
            if 'cloudinary_public_id' not in existing_cols:
                columns_to_add.append(('cloudinary_public_id', 'VARCHAR(255)'))
            if 'preview_paths' not in existing_cols:
                columns_to_add.append(('preview_paths', 'TEXT'))
                if dialect_name == 'postgresql':
                    columns_to_add.append(('assets_deleted', 'BOOLEAN DEFAULT FALSE'))
                else:
                    columns_to_add.append(('assets_deleted', 'BOOLEAN DEFAULT 0'))
            if 'assets_delete_scheduled' not in existing_cols:
                if dialect_name == 'postgresql':
                    columns_to_add.append(('assets_delete_scheduled', 'BOOLEAN DEFAULT FALSE'))
                else:
                    columns_to_add.append(('assets_delete_scheduled', 'BOOLEAN DEFAULT 0'))
            if 'assets_delete_attempted_at' not in existing_cols:
                columns_to_add.append(('assets_delete_attempted_at', 'TIMESTAMP'))
            
            # Add missing columns
            with engine.connect() as conn:
                for col_name, col_type in columns_to_add:
                    try:
                        conn.execute(text(f"ALTER TABLE print_jobs ADD COLUMN {col_name} {col_type}"))
                        conn.commit()
                        print(f"Added {col_name} column to print_jobs table")
                        
                        # Backfill defaults for specific columns
                        if col_name == 'layout_pages':
                            conn.execute(text("UPDATE print_jobs SET layout_pages = 1 WHERE layout_pages IS NULL"))
                            conn.commit()
                        elif col_name == 'layout_type':
                            conn.execute(text("UPDATE print_jobs SET layout_type = 'normal' WHERE layout_type IS NULL"))
                            conn.commit()
                    except Exception as e:
                        print(f"Warning adding {col_name} to print_jobs: {e}")
        else:
            print("Print_jobs table does not exist yet, will be created with new schema")
        
        # Check if shop_pricing table exists
        if 'shop_pricing' not in inspector.get_table_names():
            # Create shop_pricing table if it doesn't exist
            try:
                with engine.connect() as conn:
                    if dialect_name == 'postgresql':
                        conn.execute(text("""
                            CREATE TABLE shop_pricing (
                                id SERIAL PRIMARY KEY,
                                shop_id VARCHAR(36) UNIQUE NOT NULL,
                                bw_single REAL DEFAULT 2.0,
                                bw_double REAL DEFAULT 1.5,
                                color_single REAL DEFAULT 10.0,
                                color_double REAL DEFAULT 8.0,
                                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            )
                        """))
                    else:
                        conn.execute(text("""
                            CREATE TABLE shop_pricing (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                shop_id VARCHAR(36) UNIQUE NOT NULL,
                                bw_single REAL DEFAULT 2.0,
                                bw_double REAL DEFAULT 1.5,
                                color_single REAL DEFAULT 10.0,
                                color_double REAL DEFAULT 8.0,
                                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                            )
                        """))
                    conn.commit()
                    print("Created shop_pricing table")
            except Exception as e:
                print(f"Shop_pricing table creation warning: {e}")
        else:
            # Table exists, check for missing columns
            try:
                existing_cols = {col['name'] for col in inspector.get_columns('shop_pricing')}
                required_cols = {'id', 'shop_id', 'bw_single', 'bw_double', 'color_single', 'color_double', 'updated_at'}
                missing_cols = required_cols - existing_cols
                
                if missing_cols:
                    print(f"Shop_pricing table missing columns: {missing_cols}")
            except Exception as e:
                print(f"Shop_pricing table migration warning: {e}")
            
    except Exception as e:
        # Do not crash app on migration; log to stdout for MVP
        print(f"Database migration warning: {e}")


def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_schema():
    """
    Verify that all required columns exist in the database tables.
    Returns True if schema is correct, False otherwise.
    Works with both SQLite and PostgreSQL.
    """
    try:
        from sqlalchemy import inspect
        
        inspector = inspect(engine)
        
        # Check shopkeepers table schema
        if 'shopkeepers' in inspector.get_table_names():
            existing_cols = {col['name'] for col in inspector.get_columns('shopkeepers')}
            
            required_cols = {'id', 'shop_id', 'username', 'email', 'password_hash', 'shop_name', 
                           'shop_address', 'contact_number', 'shopkeeper_name', 'qr_code_path', 'created_at', 'is_active'}
            
            missing_cols = required_cols - existing_cols
            if missing_cols:
                print(f"Missing columns in shopkeepers table: {missing_cols}")
                return False
            else:
                print("Shopkeepers table schema is correct")
        
        return True
        
    except Exception as e:
        print(f"Schema verification error: {e}")
        return False

def force_schema_update():
    """
    Force update the database schema by recreating tables.
    WARNING: This will delete all existing data!
    Use only for development/testing.
    """
    try:
        print("WARNING: This will delete all existing data!")
        print("Dropping all tables...")
        Base.metadata.drop_all(bind=engine)
        
        print("Creating tables with new schema...")
        Base.metadata.create_all(bind=engine)
        
        print("Schema force update completed")
        return True
        
    except Exception as e:
        print(f"Schema force update failed: {e}")
        return False

def check_and_fix_schema():
    """
    Check schema and fix if needed.
    This is a safe operation that only adds missing columns.
    """
    try:
        print("🔍 Checking database schema...")
        
        # Run migration
        migrate_schema()
        
        # Verify schema
        if verify_schema():
            print("Database schema is correct")
            return True
        else:
            print("Schema verification failed, but migration was attempted")
            return False
            
    except Exception as e:
        print(f"Schema check/fix failed: {e}")
        return False

def init_database():
    """Initialize database with tables and run migrations"""
    try:
        print("Initializing database...")
        create_tables()
        
        # Check and fix schema
        if check_and_fix_schema():
            print("Database initialized successfully")
            return True
        else:
            print("Database initialized but schema verification failed")
            return False
            
    except Exception as e:
        print(f"Database initialization failed: {e}")
        return False
