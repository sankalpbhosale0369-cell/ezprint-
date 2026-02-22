"""
Configuration settings for EzPrint MVP
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent

print("Cloudinary Cloud Name:", os.getenv("CLOUDINARY_CLOUD_NAME"))

# Load .env from project root explicitly
env_path = BASE_DIR / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

# Database settings
# Use PostgreSQL in production (via DATABASE_URL env var), SQLite for local dev
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///fallback.db")

# Environment / Mode
ENV = os.environ.get("ENV", "dev")  # dev | prod

# Web interface settings (env-overridable)
# Render requires binding to 0.0.0.0 and defaults to port 10000
WEB_HOST = os.environ.get("WEB_HOST", "0.0.0.0" if ENV == "prod" else "localhost")
WEB_PORT = int(os.environ.get("PORT", os.environ.get("WEB_PORT", 10000 if ENV == "prod" else 5000)))
WEB_DEBUG = os.environ.get("WEB_DEBUG", "false" if ENV == "prod" else "true").lower() == "true"

# Centralized base URLs
# EZPRINT_BASE_URL should include protocol and port if necessary (e.g., http://localhost:5000)
EZPRINT_BASE_URL = os.environ.get("EZPRINT_BASE_URL", f"http://{WEB_HOST}:{WEB_PORT}")

# File upload settings
UPLOAD_FOLDER = BASE_DIR / "uploads"
MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", str(50 * 1024 * 1024)))  # bytes
ALLOWED_EXTENSIONS = set((os.environ.get("ALLOWED_EXTENSIONS",
    'pdf,docx,doc,png,jpg,jpeg,gif,bmp,tiff').split(',')))

# Print settings
DEFAULT_PRINTER = None
PRINT_TIMEOUT = 30  # seconds

# QR Code settings
QR_CODE_SIZE = 10
QR_CODE_BORDER = 4

# Logging settings
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_FILE = BASE_DIR / "logs" / "ezprint.log"

# Security settings
# In production, SECRET_KEY MUST be provided via environment variable.
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY and ENV != "prod":
    SECRET_KEY = 'dev-only-secret-do-not-use-in-production'

# Redis Message Queue (for SocketIO horizontal scaling)
REDIS_URL = os.environ.get("REDIS_URL")

if ENV == "prod":
    if not REDIS_URL:
        raise RuntimeError("REDIS_URL is required in production")
else:
    REDIS_URL = REDIS_URL or "redis://localhost:6379/0"


# Password hashing strength
BCRYPT_ROUNDS = int(os.environ.get("BCRYPT_ROUNDS", "12"))


# CORS / SocketIO
ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', EZPRINT_BASE_URL).split(',')

# TLS enforcement for printing endpoints (future IPPS support)
TLS_REQUIRED = os.environ.get('TLS_REQUIRED', 'false').lower() == 'true'

# Ghostscript: allow absolute path from env; resolver may update this during startup
GHOSTSCRIPT_EXE = os.environ.get('GHOSTSCRIPT_EXE')


# Create necessary directories
UPLOAD_FOLDER.mkdir(exist_ok=True)
(BASE_DIR / "logs").mkdir(exist_ok=True)

# Printing reliability configuration (env-overridable)
PRINT_CONFIRMATION_TIMEOUT_SECS = int(os.environ.get('PRINT_CONFIRMATION_TIMEOUT_SECS', '180'))
SEND_RETRY_ATTEMPTS = int(os.environ.get('SEND_RETRY_ATTEMPTS', '3'))
SEND_RETRY_BASE_DELAY_SECS = float(os.environ.get('SEND_RETRY_BASE_DELAY_SECS', '1'))

# Discovery / scanning limits
NETWORK_SCAN_MAX_IP = int(os.environ.get('NETWORK_SCAN_MAX_IP', '50'))
NETWORK_SCAN_MAX_THREADS = int(os.environ.get('NETWORK_SCAN_MAX_THREADS', '20'))

# --- Startup Validation ---
def validate_production_config():
    """
    Ensures critical environment variables are set for production deployment.
    Crashes startup if missing to prevent insecure or misconfigured states.
    """
    if ENV == "prod":
        missing_vars = []
        if not SECRET_KEY:
            missing_vars.append("SECRET_KEY")
        if not REDIS_URL:
            missing_vars.append("REDIS_URL")
        if not os.environ.get("DATABASE_URL"):
            missing_vars.append("DATABASE_URL")
            
        if missing_vars:
            import sys
            print(f"CRITICAL ERROR: Missing required environment variables for PRODUCTION: {', '.join(missing_vars)}")
            print("Deployment halted. Please set these in the Render dashboard.")
            sys.exit(1)

# Execute validation
validate_production_config()

# Email/SMTP Configuration
SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 587
SMTP_EMAIL = os.getenv('SMTP_EMAIL', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
