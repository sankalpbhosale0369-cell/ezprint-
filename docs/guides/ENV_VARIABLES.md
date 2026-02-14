# Environment Variables for PostgreSQL Deployment

## Required for PostgreSQL Production

```bash
# Database Connection (REQUIRED)
DATABASE_URL=postgresql://username:password@host:port/database

# Example for Render.com
DATABASE_URL=postgresql://ezprint_user:securepass123@dpg-abc123.oregon-postgres.render.com/ezprint

# Example for local PostgreSQL
DATABASE_URL=postgresql://ezprint_user:password@localhost:5432/ezprint
```

## Optional Configuration

```bash
# Environment mode
ENV=prod

# Web server settings
WEB_HOST=0.0.0.0
WEB_PORT=5000
WEB_DEBUG=false

# WebSocket settings
WEBSOCKET_HOST=0.0.0.0
WEBSOCKET_PORT=8765

# Security
SECRET_KEY=your-super-secret-key-min-32-chars
BCRYPT_ROUNDS=12

# CORS
ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# File uploads
MAX_FILE_SIZE=52428800  # 50MB in bytes
ALLOWED_EXTENSIONS=pdf,docx,doc,png,jpg,jpeg

# Logging
LOG_LEVEL=INFO
```

## Setting Environment Variables

### Local Development (.env file)
Create a `.env` file in the project root:

```bash
DATABASE_URL=postgresql://ezprint_user:password@localhost:5432/ezprint
ENV=dev
SECRET_KEY=dev-secret-key-change-in-production
```

### Render.com
1. Go to your service dashboard
2. Navigate to "Environment" tab
3. Add environment variables:
   - Key: `DATABASE_URL`
   - Value: `postgresql://...` (auto-populated if using Render PostgreSQL)

### Heroku
```bash
heroku config:set DATABASE_URL="postgresql://..."
```

### Linux/Mac (Terminal)
```bash
export DATABASE_URL="postgresql://..."
```

### Windows (Command Prompt)
```cmd
set DATABASE_URL=postgresql://...
```

### Windows (PowerShell)
```powershell
$env:DATABASE_URL="postgresql://..."
```

## Verification

Test that environment variables are set correctly:

```python
import os
from shared.config import DATABASE_URL

print(f"Database URL: {DATABASE_URL}")
print(f"Using PostgreSQL: {'postgresql' in DATABASE_URL}")
```

## Security Notes

1. **NEVER** commit `.env` files to version control
2. Add `.env` to `.gitignore`
3. Use different credentials for dev/staging/prod
4. Rotate secrets regularly
5. Use managed secrets services in production (AWS Secrets Manager, etc.)
