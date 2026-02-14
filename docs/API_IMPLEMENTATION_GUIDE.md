# EzPrint API Implementation Quick Reference
## Backend Developer Guide

**Document Version:** 1.0  
**Date:** 2026-02-09  
**For:** Backend developers implementing Phase 1

---

## Backend File Structure (After Phase 1)

```
web_interface/
├── app.py                          # Main Flask app (MODIFY)
├── api/                            # NEW DIRECTORY
│   ├── __init__.py
│   ├── auth.py                     # Authentication endpoints
│   ├── dashboard.py                # Dashboard data endpoints
│   ├── jobs.py                     # Job management endpoints
│   ├── shop.py                     # Shop configuration endpoints
│   ├── printers.py                 # Printer management endpoints
│   └── middleware.py               # JWT auth middleware
├── websocket/                      # NEW DIRECTORY
│   ├── __init__.py
│   ├── events.py                   # WebSocket event handlers
│   └── connection.py               # WebSocket connection management
├── utils/                          # NEW DIRECTORY
│   ├── __init__.py
│   ├── jwt_helper.py               # JWT token generation/validation
│   ├── validators.py               # Request validation
│   └── response_builder.py         # Standardized API responses
└── admin/                          # Existing admin blueprint
    └── ...
```

---

## Step-by-Step Implementation Guide

### Step 1: Install Dependencies

**Add to `requirements.txt`:**
```txt
PyJWT==2.8.0
python-dotenv==1.0.0
marshmallow==3.20.1  # For request validation
```

**Install:**
```bash
pip install -r requirements.txt
```

---

### Step 2: Create JWT Helper

**File: `web_interface/utils/jwt_helper.py`**

```python
"""
JWT token generation and validation
"""
import jwt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from shared.config import SECRET_KEY

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 8  # 8-hour work shift

def generate_token(shop_id: str, username: str) -> str:
    """
    Generate JWT token for authenticated shopkeeper
    
    Args:
        shop_id: Unique shop identifier
        username: Shopkeeper username
    
    Returns:
        JWT token string
    """
    payload = {
        "shop_id": shop_id,
        "username": username,
        "iat": datetime.utcnow(),  # Issued at
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
    }
    
    token = jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token

def validate_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Validate JWT token and return payload
    
    Args:
        token: JWT token string
    
    Returns:
        Decoded payload if valid, None if invalid
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None  # Token expired
    except jwt.InvalidTokenError:
        return None  # Invalid token

def refresh_token(token: str) -> Optional[str]:
    """
    Refresh JWT token (extend expiration)
    
    Args:
        token: Current JWT token
    
    Returns:
        New JWT token if valid, None if invalid
    """
    payload = validate_token(token)
    if not payload:
        return None
    
    # Generate new token with same data but new expiration
    return generate_token(payload["shop_id"], payload["username"])
```

---

### Step 3: Create Auth Middleware

**File: `web_interface/api/middleware.py`**

```python
"""
Authentication middleware for API endpoints
"""
from functools import wraps
from flask import request, jsonify
from utils.jwt_helper import validate_token

def require_auth(f):
    """
    Decorator to require JWT authentication for API endpoints
    
    Usage:
        @app.route('/api/protected')
        @require_auth
        def protected_route():
            shop_id = request.shop_id  # Injected by middleware
            username = request.username  # Injected by middleware
            return {"message": "Authenticated"}
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get Authorization header
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            return jsonify({
                "success": False,
                "message": "Missing Authorization header"
            }), 401
        
        # Extract token from "Bearer <token>"
        parts = auth_header.split()
        if len(parts) != 2 or parts[0] != 'Bearer':
            return jsonify({
                "success": False,
                "message": "Invalid Authorization header format"
            }), 401
        
        token = parts[1]
        
        # Validate token
        payload = validate_token(token)
        if not payload:
            return jsonify({
                "success": False,
                "message": "Invalid or expired token"
            }), 401
        
        # Inject shop_id and username into request context
        request.shop_id = payload["shop_id"]
        request.username = payload["username"]
        
        return f(*args, **kwargs)
    
    return decorated_function
```

---

### Step 4: Create Response Builder

**File: `web_interface/utils/response_builder.py`**

```python
"""
Standardized API response builder
"""
from flask import jsonify
from typing import Any, Optional

def success_response(data: Any, message: str = "Success", status_code: int = 200):
    """
    Build success response
    
    Args:
        data: Response data
        message: Success message
        status_code: HTTP status code
    
    Returns:
        Flask JSON response
    """
    return jsonify({
        "success": True,
        "message": message,
        "data": data
    }), status_code

def error_response(message: str, status_code: int = 400, error_code: Optional[str] = None):
    """
    Build error response
    
    Args:
        message: Error message
        status_code: HTTP status code
        error_code: Optional error code for client handling
    
    Returns:
        Flask JSON response
    """
    response = {
        "success": False,
        "message": message
    }
    
    if error_code:
        response["error_code"] = error_code
    
    return jsonify(response), status_code
```

---

### Step 5: Implement Authentication API

**File: `web_interface/api/auth.py`**

```python
"""
Authentication API endpoints
"""
from flask import Blueprint, request
from shared.database import SessionLocal, Shopkeeper
from utils.jwt_helper import generate_token, refresh_token
from utils.response_builder import success_response, error_response
from api.middleware import require_auth
import bcrypt

auth_bp = Blueprint('auth_api', __name__, url_prefix='/api/auth')

@auth_bp.route('/login', methods=['POST'])
def login():
    """
    POST /api/auth/login
    
    Request:
        {
            "username": "string",
            "password": "string"
        }
    
    Response:
        {
            "success": true,
            "message": "Login successful",
            "data": {
                "shop_id": "uuid",
                "username": "string",
                "shop_name": "string",
                ...
                "session_token": "jwt-token"
            }
        }
    """
    data = request.get_json()
    
    # Validate request
    if not data or 'username' not in data or 'password' not in data:
        return error_response("Missing username or password", 400)
    
    username = data['username']
    password = data['password']
    
    # Database query
    db = SessionLocal()
    try:
        shopkeeper = db.query(Shopkeeper).filter(
            (Shopkeeper.username == username) | (Shopkeeper.email == username)
        ).first()
        
        if not shopkeeper:
            return error_response("Invalid credentials", 401)
        
        if not shopkeeper.is_active:
            return error_response("Account is deactivated", 401)
        
        # Verify password
        if not bcrypt.checkpw(password.encode('utf-8'), shopkeeper.password_hash.encode('utf-8')):
            return error_response("Invalid credentials", 401)
        
        # Generate JWT token
        session_token = generate_token(shopkeeper.shop_id, shopkeeper.username)
        
        # Build response
        response_data = {
            'shop_id': shopkeeper.shop_id,
            'username': shopkeeper.username,
            'shop_name': shopkeeper.shop_name,
            'shop_address': shopkeeper.shop_address,
            'contact_number': shopkeeper.contact_number,
            'shopkeeper_name': shopkeeper.shopkeeper_name,
            'email': shopkeeper.email,
            'qr_code_path': shopkeeper.qr_code_path,
            'session_token': session_token
        }
        
        return success_response(response_data, "Login successful", 200)
        
    except Exception as e:
        return error_response(f"Login failed: {str(e)}", 500)
    finally:
        db.close()

@auth_bp.route('/logout', methods=['POST'])
@require_auth
def logout():
    """
    POST /api/auth/logout
    
    Request Headers:
        Authorization: Bearer <token>
    
    Request Body:
        {
            "shop_id": "uuid"
        }
    
    Response:
        {
            "success": true,
            "message": "Logged out successfully"
        }
    """
    # In stateless JWT, logout is client-side (delete token)
    # Optionally implement token blacklist here
    
    return success_response(None, "Logged out successfully", 200)

@auth_bp.route('/refresh', methods=['POST'])
@require_auth
def refresh():
    """
    POST /api/auth/refresh
    
    Request Headers:
        Authorization: Bearer <token>
    
    Response:
        {
            "success": true,
            "data": {
                "session_token": "new-jwt-token",
                "expires_at": "ISO-8601-timestamp"
            }
        }
    """
    # Get current token from header
    auth_header = request.headers.get('Authorization')
    token = auth_header.split()[1]
    
    # Refresh token
    new_token = refresh_token(token)
    
    if not new_token:
        return error_response("Failed to refresh token", 401)
    
    from datetime import datetime, timedelta
    from utils.jwt_helper import JWT_EXPIRATION_HOURS
    
    expires_at = (datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)).isoformat()
    
    return success_response({
        "session_token": new_token,
        "expires_at": expires_at
    }, "Token refreshed successfully", 200)
```

---

### Step 6: Implement Dashboard API

**File: `web_interface/api/dashboard.py`**

```python
"""
Dashboard data API endpoints
"""
from flask import Blueprint, request
from shared.database import SessionLocal, PrintJob
from utils.response_builder import success_response, error_response
from api.middleware import require_auth
from datetime import datetime, timedelta
from sqlalchemy import func

dashboard_bp = Blueprint('dashboard_api', __name__, url_prefix='/api/dashboard')

@dashboard_bp.route('/kpis', methods=['GET'])
@require_auth
def get_kpis():
    """
    GET /api/dashboard/kpis?shop_id=<uuid>&period=<today|week|month>
    
    Response:
        {
            "success": true,
            "data": {
                "total_jobs": 42,
                "pending_jobs": 5,
                "completed_jobs": 35,
                "failed_jobs": 2,
                "total_revenue": 1250.50,
                "total_pages_printed": 823,
                "avg_job_time_seconds": 45.2,
                "period": "today",
                "last_updated": "ISO-8601-timestamp"
            }
        }
    """
    shop_id = request.args.get('shop_id')
    period = request.args.get('period', 'today')
    
    # Validate shop_id matches authenticated user
    if shop_id != request.shop_id:
        return error_response("Unauthorized access to shop data", 403)
    
    # Calculate date range
    now = datetime.utcnow()
    if period == 'today':
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'week':
        start_date = now - timedelta(days=7)
    elif period == 'month':
        start_date = now - timedelta(days=30)
    else:
        return error_response("Invalid period", 400)
    
    # Database queries
    db = SessionLocal()
    try:
        # Base query
        base_query = db.query(PrintJob).filter(
            PrintJob.shop_id == shop_id,
            PrintJob.created_at >= start_date
        )
        
        # KPIs
        total_jobs = base_query.count()
        pending_jobs = base_query.filter(PrintJob.status == 'pending').count()
        completed_jobs = base_query.filter(PrintJob.status == 'completed').count()
        failed_jobs = base_query.filter(PrintJob.status == 'failed').count()
        
        # Revenue (sum of total_cost for completed jobs)
        total_revenue = db.query(func.sum(PrintJob.total_cost)).filter(
            PrintJob.shop_id == shop_id,
            PrintJob.status == 'completed',
            PrintJob.created_at >= start_date
        ).scalar() or 0.0
        
        # Total pages printed
        total_pages_printed = db.query(func.sum(PrintJob.total_pages)).filter(
            PrintJob.shop_id == shop_id,
            PrintJob.status == 'completed',
            PrintJob.created_at >= start_date
        ).scalar() or 0
        
        # Average job time (placeholder - implement if needed)
        avg_job_time_seconds = 45.2  # TODO: Calculate from print_started_at and print_completed_at
        
        response_data = {
            "total_jobs": total_jobs,
            "pending_jobs": pending_jobs,
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs,
            "total_revenue": float(total_revenue),
            "total_pages_printed": int(total_pages_printed),
            "avg_job_time_seconds": avg_job_time_seconds,
            "period": period,
            "last_updated": now.isoformat()
        }
        
        return success_response(response_data, "KPIs fetched successfully", 200)
        
    except Exception as e:
        return error_response(f"Failed to fetch KPIs: {str(e)}", 500)
    finally:
        db.close()

@dashboard_bp.route('/jobs', methods=['GET'])
@require_auth
def get_jobs():
    """
    GET /api/dashboard/jobs?shop_id=<uuid>&status=<pending|completed|failed>&limit=50&offset=0
    
    Response:
        {
            "success": true,
            "data": {
                "jobs": [...],
                "total_count": 42,
                "limit": 50,
                "offset": 0
            }
        }
    """
    shop_id = request.args.get('shop_id')
    status = request.args.get('status')
    limit = int(request.args.get('limit', 50))
    offset = int(request.args.get('offset', 0))
    sort_by = request.args.get('sort_by', 'created_at')
    sort_order = request.args.get('sort_order', 'desc')
    
    # Validate shop_id
    if shop_id != request.shop_id:
        return error_response("Unauthorized access to shop data", 403)
    
    # Validate limit
    if limit > 200:
        return error_response("Limit cannot exceed 200", 400)
    
    # Database query
    db = SessionLocal()
    try:
        # Base query
        query = db.query(PrintJob).filter(PrintJob.shop_id == shop_id)
        
        # Filter by status
        if status:
            query = query.filter(PrintJob.status == status)
        
        # Sort
        if sort_order == 'desc':
            query = query.order_by(getattr(PrintJob, sort_by).desc())
        else:
            query = query.order_by(getattr(PrintJob, sort_by).asc())
        
        # Total count
        total_count = query.count()
        
        # Pagination
        jobs = query.limit(limit).offset(offset).all()
        
        # Serialize jobs
        jobs_data = []
        for job in jobs:
            jobs_data.append({
                "job_id": job.job_id,
                "filename": job.filename,
                "file_path": job.file_path,
                "file_size": job.file_size,
                "file_type": job.file_type,
                "status": job.status,
                "total_pages": job.total_pages,
                "color_pages": job.color_pages,
                "copies": job.copies,
                "is_double_sided": job.is_double_sided,
                "total_cost": float(job.total_cost) if job.total_cost else 0.0,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
                "customer_name": job.customer_name,
                "customer_phone": job.customer_phone
            })
        
        response_data = {
            "jobs": jobs_data,
            "total_count": total_count,
            "limit": limit,
            "offset": offset
        }
        
        return success_response(response_data, "Jobs fetched successfully", 200)
        
    except Exception as e:
        return error_response(f"Failed to fetch jobs: {str(e)}", 500)
    finally:
        db.close()
```

---

### Step 7: Register Blueprints in Main App

**File: `web_interface/app.py` (MODIFY)**

```python
# ... existing imports ...

# Import API blueprints
from api.auth import auth_bp
from api.dashboard import dashboard_bp
# from api.jobs import jobs_bp  # TODO: Implement
# from api.shop import shop_bp  # TODO: Implement
# from api.printers import printers_bp  # TODO: Implement

# ... existing code ...

# Register API blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
# app.register_blueprint(jobs_bp)  # TODO: Implement
# app.register_blueprint(shop_bp)  # TODO: Implement
# app.register_blueprint(printers_bp)  # TODO: Implement

# ... rest of existing code ...
```

---

### Step 8: Test APIs with Postman

**Test 1: Login**

```http
POST http://localhost:5000/api/auth/login
Content-Type: application/json

{
    "username": "test_user",
    "password": "test_password"
}
```

**Expected Response:**
```json
{
    "success": true,
    "message": "Login successful",
    "data": {
        "shop_id": "uuid-here",
        "username": "test_user",
        "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    }
}
```

---

**Test 2: Get Dashboard KPIs**

```http
GET http://localhost:5000/api/dashboard/kpis?shop_id=<uuid>&period=today
Authorization: Bearer <session_token>
```

**Expected Response:**
```json
{
    "success": true,
    "message": "KPIs fetched successfully",
    "data": {
        "total_jobs": 42,
        "pending_jobs": 5,
        "completed_jobs": 35,
        "failed_jobs": 2,
        "total_revenue": 1250.50,
        "total_pages_printed": 823,
        "avg_job_time_seconds": 45.2,
        "period": "today",
        "last_updated": "2026-02-09T18:58:15Z"
    }
}
```

---

## Remaining APIs to Implement

### Jobs API (`web_interface/api/jobs.py`)
- `PATCH /api/jobs/{job_id}/status` - Update job status
- `GET /api/jobs/{job_id}/file` - Download job file

### Shop API (`web_interface/api/shop.py`)
- `GET /api/shop/pricing` - Get pricing config
- `PUT /api/shop/pricing` - Update pricing config
- `GET /api/shop/info` - Get shop info
- `PUT /api/shop/info` - Update shop info

### Printers API (`web_interface/api/printers.py`)
- `GET /api/printers` - Get connected printers
- `POST /api/printers` - Register new printer
- `DELETE /api/printers/{printer_id}` - Disconnect printer

---

## WebSocket Event Handlers

### Enhance Existing WebSocket Handler

**File: `web_interface/app.py` (MODIFY `websocket_handler` function)**

```python
async def websocket_handler(websocket):
    """
    Handle WebSocket connections from desktop app
    """
    shop_id = None
    session_token = None
    
    try:
        # Receive handshake
        handshake = await websocket.recv()
        handshake_data = json.loads(handshake)
        
        # Validate handshake
        if handshake_data.get('type') != 'register':
            await websocket.send(json.dumps({
                "type": "error",
                "message": "Invalid handshake"
            }))
            return
        
        shop_id = handshake_data.get('shop_id')
        session_token = handshake_data.get('session_token')
        
        # Validate session token
        from utils.jwt_helper import validate_token
        payload = validate_token(session_token)
        
        if not payload or payload.get('shop_id') != shop_id:
            await websocket.send(json.dumps({
                "type": "error",
                "message": "Invalid or expired session token"
            }))
            return
        
        # Register connection
        connected_shops[shop_id] = websocket
        logger.info(f"Desktop client registered for shop {shop_id}")
        
        # Send acknowledgment
        await websocket.send(json.dumps({
            "type": "registered",
            "shop_id": shop_id,
            "message": "Desktop client registered successfully"
        }))
        
        # Send pending jobs
        await _send_pending_jobs_to_shopkeeper(websocket, shop_id)
        
        # Listen for events from desktop
        async for message in websocket:
            event = json.loads(message)
            event_type = event.get('type')
            event_data = event.get('data', {})
            
            # Handle different event types
            if event_type == 'print_started':
                await handle_print_started(shop_id, event_data)
            elif event_type == 'print_progress':
                await handle_print_progress(shop_id, event_data)
            elif event_type == 'print_completed':
                await handle_print_completed(shop_id, event_data)
            elif event_type == 'print_failed':
                await handle_print_failed(shop_id, event_data)
            elif event_type == 'printer_heartbeat':
                await handle_printer_heartbeat(shop_id, event_data)
            elif event_type == 'printer_capability_update':
                await handle_printer_capability_update(shop_id, event_data)
            elif event_type == 'ping':
                await websocket.send(json.dumps({
                    "type": "pong",
                    "timestamp": datetime.utcnow().isoformat()
                }))
            else:
                logger.warning(f"Unknown event type: {event_type}")
        
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"Desktop client disconnected for shop {shop_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if shop_id and shop_id in connected_shops:
            del connected_shops[shop_id]

# Event handlers (implement these)
async def handle_print_started(shop_id, data):
    """Handle print_started event"""
    # TODO: Update job status to "printing" in database
    pass

async def handle_print_completed(shop_id, data):
    """Handle print_completed event"""
    # TODO: Update job status to "completed" in database
    pass

async def handle_print_failed(shop_id, data):
    """Handle print_failed event"""
    # TODO: Update job status to "failed" in database
    pass

async def handle_printer_heartbeat(shop_id, data):
    """Handle printer_heartbeat event"""
    # TODO: Update printer online/offline status in database
    pass
```

---

## Testing Checklist

### Phase 1 Testing (Backend Only)

- [ ] **Auth API**
  - [ ] Login with valid credentials returns token
  - [ ] Login with invalid credentials returns 401
  - [ ] Login with inactive account returns 401
  - [ ] Logout works
  - [ ] Refresh token works
  - [ ] Expired token returns 401

- [ ] **Dashboard API**
  - [ ] Get KPIs returns correct data
  - [ ] Get KPIs with invalid shop_id returns 403
  - [ ] Get jobs returns correct data
  - [ ] Get jobs with status filter works
  - [ ] Get jobs with pagination works
  - [ ] Get jobs with invalid shop_id returns 403

- [ ] **WebSocket**
  - [ ] Desktop can connect with valid token
  - [ ] Desktop cannot connect with invalid token
  - [ ] Ping/pong works
  - [ ] Event handlers receive events correctly

---

## Common Issues & Solutions

### Issue 1: CORS Errors

**Symptom:** Desktop app gets CORS errors when calling API

**Solution:** Add CORS headers to Flask app

```python
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})
```

---

### Issue 2: JWT Token Not Validated

**Symptom:** `@require_auth` always returns 401

**Solution:** Check SECRET_KEY is consistent

```python
# In shared/config.py
SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
```

---

### Issue 3: Database Session Leaks

**Symptom:** "Too many connections" error

**Solution:** Always close database sessions in `finally` block

```python
db = SessionLocal()
try:
    # ... database operations ...
except Exception as e:
    # ... error handling ...
finally:
    db.close()  # ALWAYS close!
```

---

## Next Steps After Phase 1

1. **Test all APIs** with Postman
2. **Document API endpoints** (use Swagger/OpenAPI if desired)
3. **Proceed to Phase 2** (Desktop API client implementation)

---

**END OF QUICK REFERENCE**
