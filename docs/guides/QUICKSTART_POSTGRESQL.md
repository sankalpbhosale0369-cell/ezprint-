# Quick Start: PostgreSQL Setup

## For Local Development

### 1. Install PostgreSQL
```bash
# Ubuntu/Debian
sudo apt-get install postgresql postgresql-contrib

# macOS
brew install postgresql

# Windows
# Download from https://www.postgresql.org/download/windows/
```

### 2. Create Database
```bash
# Start PostgreSQL service
sudo service postgresql start  # Linux
brew services start postgresql  # macOS

# Create database and user
sudo -u postgres psql
```

In PostgreSQL shell:
```sql
CREATE DATABASE ezprint;
CREATE USER ezprint_user WITH PASSWORD 'dev_password_123';
GRANT ALL PRIVILEGES ON DATABASE ezprint TO ezprint_user;
\q
```

### 3. Install Python Dependencies
```bash
pip install psycopg2-binary==2.9.9
# Or install all dependencies
pip install -r requirements.txt
```

### 4. Set Environment Variable
```bash
# Linux/Mac
export DATABASE_URL="postgresql://ezprint_user:dev_password_123@localhost:5432/ezprint"

# Windows PowerShell
$env:DATABASE_URL="postgresql://ezprint_user:dev_password_123@localhost:5432/ezprint"
```

### 5. Test Connection
```bash
python test_db_connection.py
```

### 6. Run Application
```bash
python start.py
```

## For Production (Render.com)

### 1. Create PostgreSQL Database
- Go to Render Dashboard
- Click "New +" → "PostgreSQL"
- Name: `ezprint-db`
- Database: `ezprint`
- User: `ezprint_user`
- Click "Create Database"

### 2. Get Connection String
- Copy the "Internal Database URL" from database dashboard
- Example: `postgresql://ezprint_user:xxx@dpg-xxx.oregon-postgres.render.com/ezprint`

### 3. Configure Web Service
- Go to your Web Service in Render
- Navigate to "Environment" tab
- Add environment variable:
  - Key: `DATABASE_URL`
  - Value: (paste internal database URL)

### 4. Deploy
- Push code to GitHub
- Render will auto-deploy
- Database tables created automatically on first run

## Verify Setup

### Check Database Connection
```bash
python test_db_connection.py
```

Expected output:
```
============================================================
EzPrint Database Connection Test
============================================================

Database Type: PostgreSQL
Connection String: postgresql://ezprint_user:****@localhost:5432/ezprint

Testing database connection...
✓ Connection successful!
  PostgreSQL Version: PostgreSQL 14.x

Initializing database schema...
✓ Schema initialized successfully!

Verifying tables...
  ✓ shopkeepers
  ✓ print_jobs
  ✓ printers
  ✓ system_logs
  ✓ shop_pricing

Total tables found: 5

Testing session creation...
✓ Session created successfully!

============================================================
All tests passed! Database is ready.
============================================================
```

## Troubleshooting

### "Connection refused"
```bash
# Check if PostgreSQL is running
sudo service postgresql status  # Linux
brew services list  # macOS

# Start if not running
sudo service postgresql start  # Linux
brew services start postgresql  # macOS
```

### "Authentication failed"
- Verify username and password in connection string
- Check `pg_hba.conf` authentication method
- Try resetting password:
  ```sql
  ALTER USER ezprint_user WITH PASSWORD 'new_password';
  ```

### "Database does not exist"
```sql
CREATE DATABASE ezprint;
```

### "psycopg2 not found"
```bash
pip install psycopg2-binary==2.9.9
```

## Switch Back to SQLite

To use SQLite instead of PostgreSQL:

```bash
# Remove DATABASE_URL environment variable
unset DATABASE_URL  # Linux/Mac
Remove-Item Env:DATABASE_URL  # Windows PowerShell

# Application will automatically use SQLite
python start.py
```

## Next Steps

- Read `POSTGRESQL_MIGRATION.md` for detailed migration guide
- Check `ENV_VARIABLES.md` for all configuration options
- Review `MIGRATION_SUMMARY.md` for technical details
