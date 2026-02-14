# PostgreSQL Migration Guide for EzPrint

## Overview
This guide covers migrating the EzPrint backend from SQLite to PostgreSQL for production deployment.

## Prerequisites
- PostgreSQL 12 or higher installed (or access to a managed PostgreSQL service)
- Python 3.8+ with pip
- Access to the EzPrint codebase

## Migration Steps

### 1. Install PostgreSQL Dependencies

```bash
pip install psycopg2-binary==2.9.9
```

Or install all dependencies:

```bash
pip install -r requirements.txt
```

### 2. Create PostgreSQL Database

#### Option A: Local PostgreSQL Installation

```bash
# Connect to PostgreSQL as superuser
psql -U postgres

# Create database and user
CREATE DATABASE ezprint;
CREATE USER ezprint_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE ezprint TO ezprint_user;

# Exit psql
\q
```

#### Option B: Managed PostgreSQL Service (Render, AWS RDS, etc.)

1. Create a new PostgreSQL instance through your provider's dashboard
2. Note the connection string provided (format: `postgresql://user:password@host:port/database`)

### 3. Initialize Database Schema

#### Method 1: Using SQL Script (Recommended for fresh setup)

```bash
# Run the schema initialization script
psql -U ezprint_user -d ezprint -f database_schema_postgresql.sql
```

#### Method 2: Using SQLAlchemy (Automatic)

The application will automatically create tables on first run when using the `init_database()` function.

### 4. Configure Environment Variables

Set the `DATABASE_URL` environment variable to your PostgreSQL connection string:

#### Local Development:
```bash
export DATABASE_URL="postgresql://ezprint_user:your_secure_password@localhost:5432/ezprint"
```

#### Production (Render, Heroku, etc.):
```bash
# Set via platform dashboard or CLI
# Format: postgresql://user:password@host:port/database
DATABASE_URL="postgresql://user:password@host.region.provider.com:5432/dbname"
```

**Important:** Most PaaS providers automatically set `DATABASE_URL`. Verify in your platform's environment variables.

### 5. Test Database Connection

Create a test script `test_db_connection.py`:

```python
from shared.database import engine, init_database

# Test connection
try:
    with engine.connect() as conn:
        result = conn.execute("SELECT version();")
        print("PostgreSQL version:", result.fetchone()[0])
    
    # Initialize database
    init_database()
    print("Database initialized successfully!")
    
except Exception as e:
    print(f"Database connection failed: {e}")
```

Run the test:
```bash
python test_db_connection.py
```

### 6. Data Migration (If migrating from existing SQLite)

If you have existing data in SQLite that needs to be migrated:

```python
# migration_script.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from shared.database import Base, Shopkeeper, PrintJob, Printer, ShopPricing, SystemLog

# Source (SQLite)
sqlite_engine = create_engine('sqlite:///ezprint.db')
SQLiteSession = sessionmaker(bind=sqlite_engine)

# Destination (PostgreSQL)
postgres_engine = create_engine('postgresql://user:password@host:port/database')
PostgresSession = sessionmaker(bind=postgres_engine)

# Create tables in PostgreSQL
Base.metadata.create_all(postgres_engine)

# Migrate data
sqlite_session = SQLiteSession()
postgres_session = PostgresSession()

try:
    # Migrate shopkeepers
    shopkeepers = sqlite_session.query(Shopkeeper).all()
    for shopkeeper in shopkeepers:
        postgres_session.merge(shopkeeper)
    
    # Migrate print jobs
    jobs = sqlite_session.query(PrintJob).all()
    for job in jobs:
        postgres_session.merge(job)
    
    # Migrate printers
    printers = sqlite_session.query(Printer).all()
    for printer in printers:
        postgres_session.merge(printer)
    
    # Migrate pricing
    pricing = sqlite_session.query(ShopPricing).all()
    for price in pricing:
        postgres_session.merge(price)
    
    # Commit all changes
    postgres_session.commit()
    print("Migration completed successfully!")
    
except Exception as e:
    postgres_session.rollback()
    print(f"Migration failed: {e}")
    
finally:
    sqlite_session.close()
    postgres_session.close()
```

### 7. Update Application Startup

The application will automatically use PostgreSQL when `DATABASE_URL` is set. No code changes required.

### 8. Verify Production Deployment

After deploying to production:

1. Check application logs for database connection messages
2. Verify tables were created: `\dt` in psql
3. Test user registration and login
4. Test print job creation and retrieval

## Connection String Formats

### Standard Format
```
postgresql://username:password@host:port/database
```

### With SSL (Required for most cloud providers)
```
postgresql://username:password@host:port/database?sslmode=require
```

### Render.com Format (Example)
```
postgresql://user:password@dpg-xxxxx.oregon-postgres.render.com/dbname
```

## Troubleshooting

### Connection Refused
- Verify PostgreSQL is running: `sudo systemctl status postgresql`
- Check firewall rules allow port 5432
- Verify host and port in connection string

### Authentication Failed
- Verify username and password
- Check `pg_hba.conf` for authentication method
- Ensure user has proper permissions

### SSL Required Error
Add `?sslmode=require` to connection string:
```
postgresql://user:pass@host:port/db?sslmode=require
```

### Tables Not Created
Run manually:
```bash
psql -U ezprint_user -d ezprint -f database_schema_postgresql.sql
```

Or in Python:
```python
from shared.database import init_database
init_database()
```

## Performance Tuning (Production)

### Connection Pooling
The application uses SQLAlchemy's connection pooling with these settings:
- `pool_pre_ping=True`: Validates connections before use
- `pool_recycle=3600`: Recycles connections every hour

### Recommended PostgreSQL Settings
```sql
-- In postgresql.conf
max_connections = 100
shared_buffers = 256MB
effective_cache_size = 1GB
work_mem = 4MB
```

## Rollback to SQLite (Emergency)

If you need to rollback to SQLite:

```bash
# Remove DATABASE_URL environment variable
unset DATABASE_URL

# Application will automatically use SQLite
python start.py
```

## Security Best Practices

1. **Never commit DATABASE_URL to version control**
2. Use strong passwords (20+ characters, mixed case, numbers, symbols)
3. Enable SSL/TLS for database connections in production
4. Restrict database access to application servers only
5. Regular backups (automated via pg_dump or provider tools)

## Backup and Restore

### Backup
```bash
pg_dump -U ezprint_user ezprint > backup_$(date +%Y%m%d).sql
```

### Restore
```bash
psql -U ezprint_user ezprint < backup_20260208.sql
```

## Support

For issues specific to:
- **PostgreSQL**: https://www.postgresql.org/docs/
- **SQLAlchemy**: https://docs.sqlalchemy.org/
- **Render.com**: https://render.com/docs/databases
