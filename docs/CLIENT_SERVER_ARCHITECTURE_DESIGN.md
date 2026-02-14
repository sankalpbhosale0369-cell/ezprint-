# EzPrint Client-Server Architecture Design
## Phase 1: Client Conversion Design (NO CODE CHANGES)

**Document Version:** 1.0  
**Date:** 2026-02-09  
**Status:** Design Only - No Implementation

---

## Executive Summary

This document defines the target architecture for converting the EzPrint desktop application from a **fat client with direct database access** to a **thin client** that communicates exclusively with the backend via HTTP APIs and WebSocket events.

### Current Architecture Problems

1. **Direct Database Coupling**: Desktop app (`shopkeeper_app/`) directly imports and queries the database via SQLAlchemy
2. **Duplicated Business Logic**: Pricing calculations, job validation, and file processing exist in both backend and desktop
3. **Shared File System Assumption**: Desktop app assumes access to backend's `uploads/` directory
4. **Authority Confusion**: Desktop app can modify database state without backend validation

### Target Architecture Principles

1. **Backend as Single Source of Truth**: All business logic, data persistence, and state management in backend
2. **Desktop as Thin Client**: UI rendering, local printing, and printer management only
3. **API-First Communication**: All data exchange via well-defined HTTP REST APIs
4. **Event-Driven Updates**: Real-time updates via WebSocket for job status and printer heartbeat
5. **Zero Breaking Changes**: Phased migration with backward compatibility at each step

---

## 1. API CONTRACT DESIGN

### 1.1 Authentication APIs

#### **POST /api/auth/login**
**Purpose:** Authenticate shopkeeper and establish session

**Request:**
```json
{
  "username": "string",
  "password": "string"
}
```

**Response (Success - 200):**
```json
{
  "success": true,
  "message": "Login successful",
  "data": {
    "shop_id": "uuid-string",
    "username": "string",
    "shop_name": "string",
    "shop_address": "string|null",
    "contact_number": "string|null",
    "shopkeeper_name": "string|null",
    "email": "string",
    "qr_code_path": "string",
    "session_token": "jwt-token-string"
  }
}
```

**Response (Failure - 401):**
```json
{
  "success": false,
  "message": "Invalid credentials"
}
```

**Desktop Implementation Notes:**
- Replace `AuthManager.login_shopkeeper()` direct DB call
- Store `session_token` in memory for subsequent API calls
- Include token in `Authorization: Bearer <token>` header

---

#### **POST /api/auth/logout**
**Purpose:** Invalidate session and cleanup server-side state

**Request Headers:**
```
Authorization: Bearer <session_token>
```

**Request Body:**
```json
{
  "shop_id": "uuid-string"
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Logged out successfully"
}
```

**Desktop Implementation Notes:**
- Replace local session cleanup
- Clear stored `session_token`
- Disconnect WebSocket connection

---

#### **POST /api/auth/refresh**
**Purpose:** Refresh session token without re-login

**Request Headers:**
```
Authorization: Bearer <session_token>
```

**Response (200):**
```json
{
  "success": true,
  "session_token": "new-jwt-token-string",
  "expires_at": "ISO-8601-timestamp"
}
```

**Desktop Implementation Notes:**
- Call periodically (e.g., every 30 minutes) to maintain session
- Replace token in memory and update Authorization header

---

### 1.2 Dashboard Data APIs

#### **GET /api/dashboard/kpis**
**Purpose:** Fetch dashboard KPIs (replaces direct DB queries in `dashboard.py`)

**Request Headers:**
```
Authorization: Bearer <session_token>
```

**Query Parameters:**
```
shop_id: uuid-string (required)
period: string (optional, default: "today", values: "today" | "week" | "month")
```

**Response (200):**
```json
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
```

**Desktop Implementation Notes:**
- Replace all `db_session.query(PrintJob).filter(...)` calls in dashboard
- Call on dashboard load and periodically (e.g., every 30 seconds)
- Update UI labels with response data

---

#### **GET /api/dashboard/jobs**
**Purpose:** Fetch paginated job list with filters

**Request Headers:**
```
Authorization: Bearer <session_token>
```

**Query Parameters:**
```
shop_id: uuid-string (required)
status: string (optional, values: "pending" | "printing" | "completed" | "failed")
limit: integer (optional, default: 50, max: 200)
offset: integer (optional, default: 0)
sort_by: string (optional, default: "created_at", values: "created_at" | "filename" | "status")
sort_order: string (optional, default: "desc", values: "asc" | "desc")
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "jobs": [
      {
        "job_id": "uuid-string",
        "filename": "document.pdf",
        "file_path": "https://cloudinary.com/...",
        "file_size": 1024000,
        "file_type": "pdf",
        "status": "pending",
        "total_pages": 10,
        "color_pages": 2,
        "copies": 1,
        "is_double_sided": true,
        "total_cost": 25.50,
        "created_at": "ISO-8601-timestamp",
        "updated_at": "ISO-8601-timestamp",
        "customer_name": "John Doe",
        "customer_phone": "+1234567890"
      }
    ],
    "total_count": 42,
    "limit": 50,
    "offset": 0
  }
}
```

**Desktop Implementation Notes:**
- Replace `load_jobs()` method in dashboard
- Implement pagination in job table
- Use `status` filter for tab switching (Pending/Completed/Failed)

---

### 1.3 Job Management APIs

#### **PATCH /api/jobs/{job_id}/status**
**Purpose:** Update job status (replaces direct DB updates)

**Request Headers:**
```
Authorization: Bearer <session_token>
```

**Request Body:**
```json
{
  "shop_id": "uuid-string",
  "status": "printing" | "completed" | "failed",
  "printer_name": "string (optional)",
  "error_message": "string (optional, required if status=failed)",
  "printed_pages": "integer (optional)",
  "print_started_at": "ISO-8601-timestamp (optional)",
  "print_completed_at": "ISO-8601-timestamp (optional)"
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Job status updated",
  "data": {
    "job_id": "uuid-string",
    "status": "completed",
    "updated_at": "ISO-8601-timestamp"
  }
}
```

**Response (404):**
```json
{
  "success": false,
  "message": "Job not found"
}
```

**Desktop Implementation Notes:**
- Replace all `job.status = "..."` and `db_session.commit()` calls
- Call when:
  - Print job starts: `status="printing"`
  - Print job completes: `status="completed"`
  - Print job fails: `status="failed"` with `error_message`

---

#### **GET /api/jobs/{job_id}/file**
**Purpose:** Download print file for local printing

**Request Headers:**
```
Authorization: Bearer <session_token>
```

**Query Parameters:**
```
shop_id: uuid-string (required)
```

**Response (200):**
- **Content-Type:** `application/pdf` or `image/jpeg` etc.
- **Body:** Binary file content
- **Headers:**
  - `Content-Disposition: attachment; filename="document.pdf"`
  - `X-File-Size: 1024000`
  - `X-Total-Pages: 10`

**Response (404):**
```json
{
  "success": false,
  "message": "File not found or access denied"
}
```

**Desktop Implementation Notes:**
- Replace direct file path access
- Download file to temp directory: `%TEMP%/ezprint_jobs/{job_id}/`
- Use downloaded file for `win32api.ShellExecute()` printing
- Clean up temp file after printing completes

---

### 1.4 Shop Configuration APIs

#### **GET /api/shop/pricing**
**Purpose:** Fetch shop pricing configuration

**Request Headers:**
```
Authorization: Bearer <session_token>
```

**Query Parameters:**
```
shop_id: uuid-string (required)
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "shop_id": "uuid-string",
    "bw_single": 2.0,
    "bw_double": 1.5,
    "color_single": 10.0,
    "color_double": 8.0,
    "updated_at": "ISO-8601-timestamp"
  }
}
```

**Desktop Implementation Notes:**
- Replace `db_session.query(ShopPricing)` in pricing dialog
- Cache pricing in memory, refresh on settings save

---

#### **PUT /api/shop/pricing**
**Purpose:** Update shop pricing configuration

**Request Headers:**
```
Authorization: Bearer <session_token>
```

**Request Body:**
```json
{
  "shop_id": "uuid-string",
  "bw_single": 2.0,
  "bw_double": 1.5,
  "color_single": 10.0,
  "color_double": 8.0
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Pricing updated successfully",
  "data": {
    "shop_id": "uuid-string",
    "bw_single": 2.0,
    "bw_double": 1.5,
    "color_single": 10.0,
    "color_double": 8.0,
    "updated_at": "ISO-8601-timestamp"
  }
}
```

**Desktop Implementation Notes:**
- Replace pricing save logic in settings dialog
- Validate input client-side before API call
- Show success/error message from API response

---

#### **GET /api/shop/info**
**Purpose:** Fetch shop information

**Request Headers:**
```
Authorization: Bearer <session_token>
```

**Query Parameters:**
```
shop_id: uuid-string (required)
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "shop_id": "uuid-string",
    "shop_name": "string",
    "shop_address": "string|null",
    "contact_number": "string|null",
    "shopkeeper_name": "string|null",
    "email": "string",
    "qr_code_path": "string",
    "is_active": true,
    "created_at": "ISO-8601-timestamp"
  }
}
```

**Desktop Implementation Notes:**
- Replace `AuthManager.get_shopkeeper_by_id()`
- Use for profile display and settings pre-fill

---

#### **PUT /api/shop/info**
**Purpose:** Update shop information

**Request Headers:**
```
Authorization: Bearer <session_token>
```

**Request Body:**
```json
{
  "shop_id": "uuid-string",
  "shop_name": "string (optional)",
  "shop_address": "string (optional)",
  "contact_number": "string (optional)",
  "shopkeeper_name": "string (optional)",
  "email": "string (optional)"
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Shop information updated",
  "data": {
    "shop_id": "uuid-string",
    "shop_name": "string",
    "shop_address": "string",
    "contact_number": "string",
    "shopkeeper_name": "string",
    "email": "string",
    "updated_at": "ISO-8601-timestamp"
  }
}
```

**Desktop Implementation Notes:**
- Replace `AuthManager.update_shop_info()`
- Update local session data after successful update

---

### 1.5 Printer Management APIs

#### **GET /api/printers**
**Purpose:** Fetch connected printers for shop

**Request Headers:**
```
Authorization: Bearer <session_token>
```

**Query Parameters:**
```
shop_id: uuid-string (required)
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "printers": [
      {
        "printer_id": "string",
        "printer_name": "HP LaserJet Pro",
        "is_default": true,
        "is_active": true,
        "is_online": true,
        "last_heartbeat": "ISO-8601-timestamp",
        "capabilities": {
          "supports_color": true,
          "supports_duplex": true,
          "max_paper_size": "A4"
        },
        "created_at": "ISO-8601-timestamp"
      }
    ]
  }
}
```

**Desktop Implementation Notes:**
- Replace `db_session.query(Printer)` calls
- Merge with local printer discovery results
- Show online/offline status from backend

---

#### **POST /api/printers**
**Purpose:** Register new printer

**Request Headers:**
```
Authorization: Bearer <session_token>
```

**Request Body:**
```json
{
  "shop_id": "uuid-string",
  "printer_name": "HP LaserJet Pro",
  "printer_id": "unique-printer-id",
  "is_default": false,
  "capabilities": {
    "supports_color": true,
    "supports_duplex": true,
    "max_paper_size": "A4"
  }
}
```

**Response (201):**
```json
{
  "success": true,
  "message": "Printer registered successfully",
  "data": {
    "printer_id": "unique-printer-id",
    "printer_name": "HP LaserJet Pro",
    "is_default": false,
    "is_active": true,
    "created_at": "ISO-8601-timestamp"
  }
}
```

**Desktop Implementation Notes:**
- Replace printer connection logic
- Call after user clicks "Connect" on discovered printer

---

#### **DELETE /api/printers/{printer_id}**
**Purpose:** Disconnect/remove printer

**Request Headers:**
```
Authorization: Bearer <session_token>
```

**Request Body:**
```json
{
  "shop_id": "uuid-string"
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Printer disconnected successfully"
}
```

**Desktop Implementation Notes:**
- Replace printer disconnection logic
- Call when user clicks "Disconnect" button

---

## 2. WEBSOCKET EVENT CONTRACT

### 2.1 Connection Protocol

**WebSocket URL:** `ws://localhost:8765` (current) → Keep unchanged for now

**Connection Handshake:**
```json
{
  "type": "register",
  "shop_id": "uuid-string",
  "session_token": "jwt-token-string"
}
```

**Server Acknowledgment:**
```json
{
  "type": "registered",
  "shop_id": "uuid-string",
  "message": "Desktop client registered successfully"
}
```

---

### 2.2 Job Events (Backend → Desktop)

#### **Event: `new_job`**
**Purpose:** Notify desktop of new print job

**Payload:**
```json
{
  "type": "new_job",
  "data": {
    "job_id": "uuid-string",
    "filename": "document.pdf",
    "file_path": "https://cloudinary.com/...",
    "file_size": 1024000,
    "total_pages": 10,
    "color_pages": 2,
    "copies": 1,
    "is_double_sided": true,
    "total_cost": 25.50,
    "customer_name": "John Doe",
    "customer_phone": "+1234567890",
    "created_at": "ISO-8601-timestamp"
  }
}
```

**Desktop Action:**
- Add job to pending jobs table
- Show desktop notification
- Play notification sound
- Refresh dashboard KPIs

---

#### **Event: `job_cancelled`**
**Purpose:** Notify desktop that customer cancelled job

**Payload:**
```json
{
  "type": "job_cancelled",
  "data": {
    "job_id": "uuid-string",
    "cancelled_at": "ISO-8601-timestamp",
    "reason": "Customer cancelled via web interface"
  }
}
```

**Desktop Action:**
- Remove job from pending jobs table
- Stop printing if job is currently printing
- Refresh dashboard KPIs

---

### 2.3 Printer Events (Desktop → Backend)

#### **Event: `printer_heartbeat`**
**Purpose:** Send periodic printer status updates

**Payload:**
```json
{
  "type": "printer_heartbeat",
  "data": {
    "shop_id": "uuid-string",
    "printers": [
      {
        "printer_id": "string",
        "printer_name": "HP LaserJet Pro",
        "is_online": true,
        "status": "idle" | "printing" | "error",
        "current_job_id": "uuid-string|null",
        "error_message": "string|null"
      }
    ],
    "timestamp": "ISO-8601-timestamp"
  }
}
```

**Backend Action:**
- Update printer online/offline status in database
- Update `last_heartbeat` timestamp
- Broadcast printer status to web clients (for future customer UI)

**Desktop Implementation:**
- Send every 10 seconds
- Include all connected printers
- Detect printer status changes (online/offline/error)

---

#### **Event: `printer_capability_update`**
**Purpose:** Notify backend of printer capability changes

**Payload:**
```json
{
  "type": "printer_capability_update",
  "data": {
    "shop_id": "uuid-string",
    "printer_id": "string",
    "capabilities": {
      "supports_color": true,
      "supports_duplex": true,
      "max_paper_size": "A4",
      "paper_sizes": ["A4", "Letter", "Legal"],
      "resolutions": ["300dpi", "600dpi", "1200dpi"]
    },
    "timestamp": "ISO-8601-timestamp"
  }
}
```

**Backend Action:**
- Update printer capabilities in database
- Use for job validation (e.g., reject color jobs if printer doesn't support color)

**Desktop Implementation:**
- Send when printer is first connected
- Send when capabilities change (e.g., after driver update)

---

### 2.4 Print Status Events (Desktop → Backend)

#### **Event: `print_started`**
**Purpose:** Notify backend that printing has started

**Payload:**
```json
{
  "type": "print_started",
  "data": {
    "shop_id": "uuid-string",
    "job_id": "uuid-string",
    "printer_id": "string",
    "printer_name": "HP LaserJet Pro",
    "started_at": "ISO-8601-timestamp"
  }
}
```

**Backend Action:**
- Update job status to `"printing"`
- Set `print_started_at` timestamp
- Broadcast to web client (for customer tracking)

**Desktop Implementation:**
- Send immediately after `win32api.ShellExecute()` call
- Include actual printer used (may differ from default)

---

#### **Event: `print_progress`**
**Purpose:** Send real-time print progress updates

**Payload:**
```json
{
  "type": "print_progress",
  "data": {
    "shop_id": "uuid-string",
    "job_id": "uuid-string",
    "printed_pages": 5,
    "total_pages": 10,
    "progress_percent": 50,
    "timestamp": "ISO-8601-timestamp"
  }
}
```

**Backend Action:**
- Update job progress in database
- Broadcast to web client for live progress bar

**Desktop Implementation:**
- Send every 2-3 seconds during printing
- Calculate progress from printer spooler status

---

#### **Event: `print_completed`**
**Purpose:** Notify backend that printing completed successfully

**Payload:**
```json
{
  "type": "print_completed",
  "data": {
    "shop_id": "uuid-string",
    "job_id": "uuid-string",
    "printer_id": "string",
    "printed_pages": 10,
    "completed_at": "ISO-8601-timestamp",
    "print_duration_seconds": 45
  }
}
```

**Backend Action:**
- Update job status to `"completed"`
- Set `print_completed_at` timestamp
- Update revenue statistics
- Broadcast to web client

**Desktop Implementation:**
- Send after print spooler confirms job completion
- Calculate duration from `print_started_at`

---

#### **Event: `print_failed`**
**Purpose:** Notify backend that printing failed

**Payload:**
```json
{
  "type": "print_failed",
  "data": {
    "shop_id": "uuid-string",
    "job_id": "uuid-string",
    "printer_id": "string",
    "error_code": "PRINTER_OFFLINE" | "OUT_OF_PAPER" | "SPOOLER_ERROR" | "UNKNOWN",
    "error_message": "Printer is offline",
    "failed_at": "ISO-8601-timestamp",
    "printed_pages": 3
  }
}
```

**Backend Action:**
- Update job status to `"failed"`
- Store error message
- Broadcast to web client
- Optionally send notification to customer

**Desktop Implementation:**
- Send when print spooler reports error
- Include partial page count if available
- Map Windows error codes to standardized error codes

---

### 2.5 System Events (Bidirectional)

#### **Event: `ping`** (Desktop → Backend)
**Purpose:** Keep connection alive

**Payload:**
```json
{
  "type": "ping",
  "timestamp": "ISO-8601-timestamp"
}
```

**Backend Response:**
```json
{
  "type": "pong",
  "timestamp": "ISO-8601-timestamp"
}
```

**Desktop Implementation:**
- Send every 30 seconds
- Reconnect if no `pong` received within 5 seconds

---

#### **Event: `reconnect_required`** (Backend → Desktop)
**Purpose:** Notify desktop to reconnect (e.g., after server restart)

**Payload:**
```json
{
  "type": "reconnect_required",
  "reason": "Server restarted",
  "reconnect_after_seconds": 5
}
```

**Desktop Action:**
- Close current connection
- Wait specified duration
- Re-establish connection with fresh handshake

---

## 3. MIGRATION ORDER

### Phase 1: Foundation (Week 1)

**Goal:** Implement APIs without breaking existing functionality

**Steps:**
1. **Backend: Create API routes** (NO desktop changes yet)
   - Implement all HTTP APIs in `web_interface/app.py`
   - Add JWT authentication middleware
   - Add request validation
   - Keep existing WebSocket server unchanged

2. **Backend: Add WebSocket event handlers**
   - Implement new event types in `websocket_handler()`
   - Keep backward compatibility with existing events

3. **Testing:**
   - Test APIs with Postman/curl
   - Verify database operations work correctly
   - Ensure existing desktop app still works (using direct DB access)

**Deliverables:**
- All APIs implemented and tested
- API documentation with examples
- No desktop changes yet

---

### Phase 2: Authentication Migration (Week 2)

**Goal:** Replace desktop auth with API calls

**Steps:**
1. **Desktop: Create API client module**
   - Create `shopkeeper_app/api_client.py`
   - Implement HTTP request wrapper with auth headers
   - Implement session token management

2. **Desktop: Replace auth logic**
   - Replace `AuthManager.login_shopkeeper()` with `POST /api/auth/login`
   - Replace `AuthManager.register_shopkeeper()` with backend call (if needed)
   - Store session token in memory

3. **Desktop: Update WebSocket connection**
   - Send `session_token` in WebSocket handshake
   - Implement auto-reconnect with token refresh

4. **Testing:**
   - Test login/logout flow
   - Verify session persistence
   - Test token expiration and refresh

**Deliverables:**
- Desktop app authenticates via API
- Session management working
- WebSocket connection authenticated
- **Backward compatibility:** Can still fall back to direct DB if API unavailable

---

### Phase 3: Dashboard Data Migration (Week 3)

**Goal:** Replace dashboard DB queries with API calls

**Steps:**
1. **Desktop: Replace KPI queries**
   - Replace `db_session.query(PrintJob).filter(...)` with `GET /api/dashboard/kpis`
   - Implement periodic refresh (every 30 seconds)

2. **Desktop: Replace job list queries**
   - Replace `load_jobs()` with `GET /api/dashboard/jobs`
   - Implement pagination
   - Implement status filtering

3. **Desktop: Update job status updates**
   - Replace `job.status = "..."` with `PATCH /api/jobs/{job_id}/status`
   - Remove direct DB commits

4. **Testing:**
   - Verify dashboard loads correctly
   - Test job list pagination
   - Test status updates reflect in backend

**Deliverables:**
- Dashboard fully API-driven
- No direct DB queries for job data
- **Backward compatibility:** Graceful degradation if API unavailable

---

### Phase 4: File Access Migration (Week 4)

**Goal:** Replace direct file access with API downloads

**Steps:**
1. **Desktop: Implement file download**
   - Create temp directory: `%TEMP%/ezprint_jobs/`
   - Implement `GET /api/jobs/{job_id}/file` client
   - Download files before printing

2. **Desktop: Update print logic**
   - Replace direct file path with downloaded temp file
   - Update `win32api.ShellExecute()` to use temp file
   - Implement temp file cleanup after printing

3. **Testing:**
   - Test printing from Cloudinary URLs
   - Test printing from local files (backward compatibility)
   - Verify temp file cleanup

**Deliverables:**
- Desktop prints from API-downloaded files
- No direct file system coupling
- Temp file management working

---

### Phase 5: Configuration Migration (Week 5)

**Goal:** Replace config DB queries with API calls

**Steps:**
1. **Desktop: Replace pricing queries**
   - Replace `db_session.query(ShopPricing)` with `GET /api/shop/pricing`
   - Replace pricing save with `PUT /api/shop/pricing`

2. **Desktop: Replace shop info queries**
   - Replace `AuthManager.get_shopkeeper_by_id()` with `GET /api/shop/info`
   - Replace shop info update with `PUT /api/shop/info`

3. **Testing:**
   - Test pricing display and update
   - Test shop info display and update

**Deliverables:**
- All configuration via API
- No direct DB queries for config

---

### Phase 6: Printer Management Migration (Week 6)

**Goal:** Replace printer DB queries with API calls

**Steps:**
1. **Desktop: Replace printer queries**
   - Replace `db_session.query(Printer)` with `GET /api/printers`
   - Merge API results with local printer discovery

2. **Desktop: Replace printer registration**
   - Replace printer DB insert with `POST /api/printers`
   - Replace printer delete with `DELETE /api/printers/{printer_id}`

3. **Desktop: Implement heartbeat**
   - Send `printer_heartbeat` event every 10 seconds
   - Include all connected printers

4. **Testing:**
   - Test printer discovery
   - Test printer connection/disconnection
   - Verify heartbeat updates backend

**Deliverables:**
- Printer management fully API-driven
- Heartbeat working
- No direct DB queries for printers

---

### Phase 7: WebSocket Events Migration (Week 7)

**Goal:** Implement all WebSocket events

**Steps:**
1. **Desktop: Implement print status events**
   - Send `print_started` when printing starts
   - Send `print_progress` during printing
   - Send `print_completed` when printing completes
   - Send `print_failed` on errors

2. **Desktop: Handle job events**
   - Handle `new_job` event
   - Handle `job_cancelled` event
   - Update UI in real-time

3. **Testing:**
   - Test new job notifications
   - Test print status updates
   - Verify backend receives events

**Deliverables:**
- All WebSocket events implemented
- Real-time updates working
- Desktop fully event-driven

---

### Phase 8: Database Removal (Week 8)

**Goal:** Remove all direct DB access from desktop

**Steps:**
1. **Desktop: Remove database imports**
   - Remove `from shared.database import ...`
   - Remove `SessionLocal` usage
   - Remove `db_session` references

2. **Desktop: Remove AuthManager**
   - Delete `shopkeeper_app/auth.py` (or keep as legacy)
   - Remove all `AuthManager` usage

3. **Desktop: Update config**
   - Remove `DATABASE_URL` from desktop config
   - Keep only API endpoint config

4. **Testing:**
   - Full regression testing
   - Verify all features work without DB access
   - Test offline behavior (graceful degradation)

**Deliverables:**
- Desktop app has ZERO database dependencies
- All data via API
- Clean codebase

---

### Phase 9: Deployment & Monitoring (Week 9)

**Goal:** Deploy and monitor production

**Steps:**
1. **Backend: Add API monitoring**
   - Add request logging
   - Add error tracking
   - Add performance metrics

2. **Desktop: Add API error handling**
   - Implement retry logic
   - Implement offline mode
   - Show user-friendly error messages

3. **Testing:**
   - Load testing
   - Failover testing
   - Network interruption testing

**Deliverables:**
- Production deployment
- Monitoring dashboard
- Error handling working

---

## 4. SAFETY GUARANTEES

### 4.1 Printing Remains Local

**Guarantee:** Printing logic NEVER moves to backend

**Implementation:**
- Desktop app downloads file via `GET /api/jobs/{job_id}/file`
- Desktop app calls `win32api.ShellExecute()` locally
- Desktop app manages printer spooler locally
- Desktop app sends status updates to backend via WebSocket

**Why:** Printing requires direct access to Windows printer drivers and spooler, which cannot be done remotely.

---

### 4.2 UI Remains Local

**Guarantee:** All UI rendering happens in desktop app

**Implementation:**
- PyQt5 UI code remains in `shopkeeper_app/dashboard.py`
- No web-based UI for shopkeeper (only customer web interface)
- Desktop app fetches data via API and renders locally

**Why:** Desktop app provides better performance, offline capability, and native OS integration.

---

### 4.3 No Breaking Changes During Migration

**Guarantee:** Each phase maintains backward compatibility

**Implementation:**
- **Dual-mode operation:** Desktop can use API OR direct DB during migration
- **Feature flags:** Enable/disable API usage per feature
- **Graceful degradation:** If API unavailable, fall back to direct DB (with warning)
- **Rollback capability:** Can revert to previous phase at any time

**Example (Dual-mode auth):**
```python
# In shopkeeper_app/auth.py
def login(username, password):
    if USE_API:  # Feature flag
        try:
            return api_client.login(username, password)
        except APIError:
            logger.warning("API unavailable, falling back to direct DB")
            return AuthManager().login_shopkeeper(username, password)
    else:
        return AuthManager().login_shopkeeper(username, password)
```

---

### 4.4 Data Consistency

**Guarantee:** No data loss or corruption during migration

**Implementation:**
- **Database migrations:** Use Alembic for schema changes
- **API versioning:** Support multiple API versions during transition
- **Transaction safety:** All API endpoints use database transactions
- **Audit logging:** Log all API operations for debugging

---

### 4.5 Performance

**Guarantee:** No performance degradation

**Implementation:**
- **API caching:** Cache frequently accessed data (pricing, shop info)
- **Batch operations:** Fetch multiple jobs in single API call
- **WebSocket for real-time:** Avoid polling for job updates
- **Local file caching:** Cache downloaded files for re-prints

**Benchmarks:**
- Dashboard load time: < 2 seconds (same as current)
- Job status update: < 500ms (same as current)
- File download: Depends on network, but show progress bar

---

## 5. RISK MITIGATION

### 5.1 API Unavailability

**Risk:** Backend API down, desktop app cannot function

**Mitigation:**
- **Offline mode:** Desktop can queue operations and sync when API available
- **Local cache:** Cache critical data (pricing, shop info) for offline use
- **Graceful degradation:** Show warning but allow limited functionality
- **Health checks:** Desktop pings API every 30 seconds, shows connection status

---

### 5.2 Network Latency

**Risk:** Slow network causes poor UX

**Mitigation:**
- **Optimistic UI updates:** Update UI immediately, sync with backend asynchronously
- **Request timeouts:** Fail fast (5 second timeout) and show error
- **Retry logic:** Auto-retry failed requests (max 3 attempts)
- **Loading indicators:** Show spinners during API calls

---

### 5.3 Session Expiration

**Risk:** User gets logged out unexpectedly

**Mitigation:**
- **Long session duration:** 8 hours (typical work shift)
- **Auto-refresh:** Refresh token every 30 minutes in background
- **Session persistence:** Store encrypted token on disk (optional)
- **Graceful re-login:** If session expires, show login dialog without losing state

---

### 5.4 WebSocket Disconnection

**Risk:** Real-time updates stop working

**Mitigation:**
- **Auto-reconnect:** Reconnect immediately on disconnection
- **Exponential backoff:** If reconnect fails, retry with increasing delays
- **Missed events:** On reconnect, fetch missed jobs via `GET /api/dashboard/jobs`
- **Connection status:** Show WebSocket status in UI (connected/disconnected)

---

### 5.5 File Download Failures

**Risk:** Cannot download file for printing

**Mitigation:**
- **Retry logic:** Retry download up to 3 times
- **Resume support:** Use HTTP Range headers for partial downloads
- **Fallback:** If Cloudinary URL fails, try direct file path (if available)
- **Error messages:** Show clear error to user with retry option

---

## 6. TESTING STRATEGY

### 6.1 API Testing

**Tools:** Postman, pytest

**Test Cases:**
- All endpoints return correct status codes
- Request validation works (reject invalid data)
- Authentication works (reject invalid tokens)
- Database operations work correctly
- Error handling works (500 errors logged)

---

### 6.2 Integration Testing

**Tools:** pytest, pytest-asyncio

**Test Cases:**
- Desktop can authenticate via API
- Desktop can fetch dashboard data
- Desktop can update job status
- Desktop can download files
- WebSocket events work end-to-end

---

### 6.3 UI Testing

**Tools:** Manual testing, PyQt5 test framework

**Test Cases:**
- Dashboard loads correctly
- Job list updates in real-time
- Print button works
- Settings save correctly
- Error messages display correctly

---

### 6.4 Performance Testing

**Tools:** Locust, Apache Bench

**Test Cases:**
- API can handle 100 concurrent requests
- Dashboard loads in < 2 seconds
- File download speed acceptable
- WebSocket can handle 50 concurrent connections

---

### 6.5 Regression Testing

**Tools:** pytest, manual testing

**Test Cases:**
- All existing features still work
- No new bugs introduced
- Performance not degraded
- UI behavior unchanged

---

## 7. ROLLOUT PLAN

### 7.1 Development Environment

**Timeline:** Weeks 1-8

**Actions:**
- Implement all APIs
- Migrate desktop app feature-by-feature
- Test thoroughly

---

### 7.2 Staging Environment

**Timeline:** Week 9

**Actions:**
- Deploy to staging server
- Test with real data (anonymized)
- Load testing
- Security testing

---

### 7.3 Beta Testing

**Timeline:** Week 10

**Actions:**
- Deploy to 2-3 beta shops
- Monitor for issues
- Gather feedback
- Fix bugs

---

### 7.4 Production Rollout

**Timeline:** Week 11

**Actions:**
- Deploy to all shops
- Monitor closely for 1 week
- Provide support
- Document issues

---

### 7.5 Post-Deployment

**Timeline:** Week 12+

**Actions:**
- Remove direct DB access code
- Clean up legacy code
- Update documentation
- Plan next features

---

## 8. SUCCESS METRICS

### 8.1 Technical Metrics

- **API uptime:** > 99.9%
- **API response time:** < 500ms (p95)
- **WebSocket uptime:** > 99.5%
- **File download success rate:** > 99%
- **Desktop crash rate:** < 0.1%

---

### 8.2 Business Metrics

- **User satisfaction:** > 4.5/5 (survey)
- **Support tickets:** < 5 per week
- **Downtime incidents:** 0 per month
- **Data loss incidents:** 0

---

## 9. NEXT STEPS

### Immediate Actions (This Week)

1. **Review this design document** with stakeholders
2. **Get approval** for architecture and migration plan
3. **Set up project tracking** (Jira, Trello, etc.)
4. **Assign tasks** to developers

### Week 1 Actions

1. **Backend:** Start implementing APIs
2. **Backend:** Set up API testing framework
3. **Desktop:** Create API client module (stub)
4. **DevOps:** Set up staging environment

---

## 10. APPENDIX

### A. API Client Example (Python)

```python
# shopkeeper_app/api_client.py
import requests
from typing import Optional, Dict, Any

class EzPrintAPIClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session_token: Optional[str] = None
    
    def login(self, username: str, password: str) -> Dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/api/auth/login",
            json={"username": username, "password": password},
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        self.session_token = data["data"]["session_token"]
        return data
    
    def get_dashboard_kpis(self, shop_id: str, period: str = "today") -> Dict[str, Any]:
        response = requests.get(
            f"{self.base_url}/api/dashboard/kpis",
            params={"shop_id": shop_id, "period": period},
            headers={"Authorization": f"Bearer {self.session_token}"},
            timeout=5
        )
        response.raise_for_status()
        return response.json()
    
    def update_job_status(self, job_id: str, shop_id: str, status: str, **kwargs) -> Dict[str, Any]:
        response = requests.patch(
            f"{self.base_url}/api/jobs/{job_id}/status",
            json={"shop_id": shop_id, "status": status, **kwargs},
            headers={"Authorization": f"Bearer {self.session_token}"},
            timeout=5
        )
        response.raise_for_status()
        return response.json()
    
    def download_job_file(self, job_id: str, shop_id: str, output_path: str) -> None:
        response = requests.get(
            f"{self.base_url}/api/jobs/{job_id}/file",
            params={"shop_id": shop_id},
            headers={"Authorization": f"Bearer {self.session_token}"},
            stream=True,
            timeout=30
        )
        response.raise_for_status()
        
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
```

### B. WebSocket Event Handler Example (Python)

```python
# shopkeeper_app/websocket_client.py (enhanced)
import asyncio
import websockets
import json
from typing import Callable, Dict, Any

class EzPrintWebSocketClient:
    def __init__(self, ws_url: str, shop_id: str, session_token: str):
        self.ws_url = ws_url
        self.shop_id = shop_id
        self.session_token = session_token
        self.event_handlers: Dict[str, Callable] = {}
    
    def on(self, event_type: str, handler: Callable):
        """Register event handler"""
        self.event_handlers[event_type] = handler
    
    async def connect(self):
        """Connect to WebSocket and handle events"""
        async with websockets.connect(self.ws_url) as websocket:
            # Send handshake
            await websocket.send(json.dumps({
                "type": "register",
                "shop_id": self.shop_id,
                "session_token": self.session_token
            }))
            
            # Receive events
            async for message in websocket:
                event = json.loads(message)
                event_type = event.get("type")
                
                if event_type in self.event_handlers:
                    self.event_handlers[event_type](event.get("data"))
    
    async def send_event(self, event_type: str, data: Dict[str, Any]):
        """Send event to backend"""
        # Implementation depends on connection management
        pass
```

---

## DOCUMENT APPROVAL

**Prepared by:** Senior SaaS Architect  
**Date:** 2026-02-09  
**Status:** DESIGN ONLY - NO CODE CHANGES

**Next Step:** Proceed to Phase 2 - Implementation Planning

---

**END OF DOCUMENT**
