# Phase 2: Backend API Implementation - Test Checklist
## Manual Testing Guide

**Date:** 2026-02-09  
**Phase:** Phase 2 - Backend API Implementation  
**Status:** Ready for Testing

---

## Prerequisites

1. **Install Dependencies**
   ```bash
   pip install PyJWT==2.8.0
   ```

2. **Start Backend Server**
   ```bash
   python start.py
   ```
   - Verify backend starts on `http://localhost:5000`
   - Check logs for "Running on http://localhost:5000"

3. **Test Tool: Postman or curl**
   - Install Postman (recommended) or use curl commands below

---

## Test 1: Authentication API

### 1.1 Login (POST /api/auth/login)

**Request:**
```bash
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "YOUR_USERNAME",
    "password": "YOUR_PASSWORD"
  }'
```

**Expected Response (200):**
```json
{
  "success": true,
  "message": "Login successful",
  "data": {
    "shop_id": "uuid-string",
    "username": "YOUR_USERNAME",
    "shop_name": "Shop Name",
    "shop_address": null,
    "contact_number": null,
    "shopkeeper_name": null,
    "email": "email@example.com",
    "qr_code_path": "/path/to/qr.png",
    "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }
}
```

**Save the `session_token` for subsequent tests!**

**Test Cases:**
- [ ] Valid credentials return 200 with session_token
- [ ] Invalid username returns 401
- [ ] Invalid password returns 401
- [ ] Missing username returns 400
- [ ] Missing password returns 400
- [ ] Inactive account returns 401

---

### 1.2 Get Session (GET /api/auth/session)

**Request:**
```bash
curl -X GET http://localhost:5000/api/auth/session \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Expected Response (200):**
```json
{
  "success": true,
  "message": "Session retrieved successfully",
  "data": {
    "shop_id": "uuid-string",
    "username": "YOUR_USERNAME",
    "shop_name": "Shop Name",
    ...
  }
}
```

**Test Cases:**
- [ ] Valid token returns 200 with shop data
- [ ] Missing Authorization header returns 401
- [ ] Invalid token format returns 401
- [ ] Expired token returns 401

---

### 1.3 Refresh Token (POST /api/auth/refresh)

**Request:**
```bash
curl -X POST http://localhost:5000/api/auth/refresh \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Expected Response (200):**
```json
{
  "success": true,
  "message": "Token refreshed successfully",
  "data": {
    "session_token": "NEW_JWT_TOKEN",
    "expires_at": "2026-02-10T03:12:37Z"
  }
}
```

**Test Cases:**
- [ ] Valid token returns new token
- [ ] Invalid token returns 401

---

### 1.4 Logout (POST /api/auth/logout)

**Request:**
```bash
curl -X POST http://localhost:5000/api/auth/logout \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"shop_id": "YOUR_SHOP_ID"}'
```

**Expected Response (200):**
```json
{
  "success": true,
  "message": "Logged out successfully",
  "data": null
}
```

**Test Cases:**
- [ ] Valid token returns 200
- [ ] Invalid token returns 401

---

## Test 2: Dashboard API

### 2.1 Get Dashboard (GET /api/shop/<shop_id>/dashboard)

**Request:**
```bash
curl -X GET "http://localhost:5000/api/shop/YOUR_SHOP_ID/dashboard?period=today&limit=10&offset=0" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Expected Response (200):**
```json
{
  "success": true,
  "message": "Dashboard data fetched successfully",
  "data": {
    "kpis": {
      "total_jobs": 42,
      "pending_jobs": 5,
      "completed_jobs": 35,
      "failed_jobs": 2,
      "total_revenue": 1250.50,
      "total_pages_printed": 823,
      "period": "today",
      "last_updated": "2026-02-09T19:12:37Z"
    },
    "jobs": [
      {
        "job_id": "uuid",
        "filename": "document.pdf",
        "file_path": "https://cloudinary.com/...",
        "status": "pending",
        "total_pages": 10,
        ...
      }
    ],
    "total_count": 42,
    "limit": 10,
    "offset": 0
  }
}
```

**Test Cases:**
- [ ] Valid shop_id returns dashboard data
- [ ] period=today returns today's KPIs
- [ ] period=week returns week's KPIs
- [ ] period=month returns month's KPIs
- [ ] Invalid period returns 400
- [ ] limit parameter works (test with limit=5)
- [ ] offset parameter works (test with offset=5)
- [ ] status filter works (test with status=pending)
- [ ] Unauthorized shop_id returns 403
- [ ] Invalid token returns 401

---

## Test 3: Config API

### 3.1 Get Full Config (GET /api/shop/<shop_id>/config)

**Request:**
```bash
curl -X GET http://localhost:5000/api/shop/YOUR_SHOP_ID/config \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Expected Response (200):**
```json
{
  "success": true,
  "message": "Configuration fetched successfully",
  "data": {
    "shop_info": {
      "shop_id": "uuid",
      "shop_name": "Shop Name",
      "shop_address": null,
      "contact_number": null,
      "shopkeeper_name": null,
      "email": "email@example.com",
      "qr_code_path": "/path/to/qr.png"
    },
    "pricing": {
      "bw_single": 2.0,
      "bw_double": 1.5,
      "color_single": 10.0,
      "color_double": 8.0
    },
    "printers": [
      {
        "printer_id": "printer-1",
        "printer_name": "HP LaserJet",
        "is_default": true,
        "is_active": true
      }
    ]
  }
}
```

**Test Cases:**
- [ ] Valid shop_id returns config
- [ ] Unauthorized shop_id returns 403
- [ ] Invalid token returns 401

---

### 3.2 Get Pricing (GET /api/shop/<shop_id>/pricing)

**Request:**
```bash
curl -X GET http://localhost:5000/api/shop/YOUR_SHOP_ID/pricing \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Expected Response (200):**
```json
{
  "success": true,
  "message": "Pricing fetched successfully",
  "data": {
    "shop_id": "uuid",
    "bw_single": 2.0,
    "bw_double": 1.5,
    "color_single": 10.0,
    "color_double": 8.0
  }
}
```

**Test Cases:**
- [ ] Valid shop_id returns pricing
- [ ] Shop without pricing returns defaults
- [ ] Unauthorized shop_id returns 403

---

### 3.3 Update Pricing (PUT /api/shop/<shop_id>/pricing)

**Request:**
```bash
curl -X PUT http://localhost:5000/api/shop/YOUR_SHOP_ID/pricing \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "bw_single": 2.5,
    "bw_double": 2.0,
    "color_single": 12.0,
    "color_double": 10.0
  }'
```

**Expected Response (200):**
```json
{
  "success": true,
  "message": "Pricing updated successfully",
  "data": {
    "shop_id": "uuid",
    "bw_single": 2.5,
    "bw_double": 2.0,
    "color_single": 12.0,
    "color_double": 10.0
  }
}
```

**Test Cases:**
- [ ] Valid pricing update returns 200
- [ ] Partial update works (only update bw_single)
- [ ] Unauthorized shop_id returns 403
- [ ] Missing request body returns 400

---

## Test 4: Backward Compatibility

### 4.1 Existing Customer Upload Flow

**Test that existing customer upload still works:**

1. Open browser to `http://localhost:5000/upload/YOUR_SHOP_ID`
2. Upload a PDF file
3. Verify job is created successfully
4. Check that desktop app (if running) receives notification

**Test Cases:**
- [ ] Customer upload page loads
- [ ] File upload works
- [ ] Job is created in database
- [ ] WebSocket notification sent (if desktop connected)

---

### 4.2 Existing Admin Routes

**Test that admin routes still work:**

1. Open browser to `http://localhost:5000/admin`
2. Verify admin panel loads

**Test Cases:**
- [ ] Admin panel loads
- [ ] Admin routes not affected by new APIs

---

### 4.3 Desktop App (Direct DB Access)

**IMPORTANT: Desktop app should still work with direct DB access**

1. Start desktop app: `python start_shopkeeper.py`
2. Login with credentials
3. Verify dashboard loads
4. Verify jobs list loads
5. Verify pricing settings load

**Test Cases:**
- [ ] Desktop app starts successfully
- [ ] Desktop login works (direct DB)
- [ ] Desktop dashboard loads (direct DB)
- [ ] Desktop can view jobs (direct DB)
- [ ] Desktop can view pricing (direct DB)
- [ ] **NO API calls made by desktop yet**

---

## Test 5: Security & Validation

### 5.1 Authorization Checks

**Test that shop_id validation works:**

1. Login as Shop A (get token_A)
2. Try to access Shop B's dashboard with token_A
3. Should return 403 Forbidden

**Request:**
```bash
curl -X GET http://localhost:5000/api/shop/SHOP_B_ID/dashboard \
  -H "Authorization: Bearer TOKEN_A"
```

**Expected Response (403):**
```json
{
  "success": false,
  "message": "Unauthorized access to shop data"
}
```

**Test Cases:**
- [ ] Cannot access other shop's dashboard
- [ ] Cannot access other shop's config
- [ ] Cannot update other shop's pricing

---

### 5.2 Token Expiration

**Test that expired tokens are rejected:**

1. Generate a token with very short expiration (modify JWT_EXPIRATION_HOURS temporarily)
2. Wait for token to expire
3. Try to access protected endpoint
4. Should return 401 Unauthorized

**Test Cases:**
- [ ] Expired token returns 401
- [ ] Error message indicates token expired

---

## Test 6: Logging & Monitoring

### 6.1 API Call Logging

**Check that API calls are logged:**

1. Make several API calls
2. Check backend logs
3. Verify each API call is logged with:
   - Endpoint
   - Shop ID
   - Success/failure
   - Timestamp

**Test Cases:**
- [ ] Login attempts logged
- [ ] Dashboard fetches logged
- [ ] Config updates logged
- [ ] Unauthorized access attempts logged

---

### 6.2 Error Logging

**Check that errors are logged:**

1. Make invalid API calls (bad data, missing fields, etc.)
2. Check backend logs
3. Verify errors are logged with stack traces

**Test Cases:**
- [ ] 400 errors logged
- [ ] 401 errors logged
- [ ] 403 errors logged
- [ ] 500 errors logged with stack trace

---

## Test 7: Performance

### 7.1 Response Times

**Measure API response times:**

1. Use Postman or curl with timing
2. Measure response time for each endpoint
3. Verify response times are acceptable

**Target Response Times:**
- Login: < 500ms
- Dashboard: < 1000ms
- Config: < 500ms
- Pricing: < 300ms

**Test Cases:**
- [ ] Login response time < 500ms
- [ ] Dashboard response time < 1000ms
- [ ] Config response time < 500ms
- [ ] Pricing response time < 300ms

---

## Test 8: Data Accuracy

### 8.1 Dashboard KPIs Match Desktop

**Compare API KPIs with desktop dashboard:**

1. Open desktop app
2. Note KPI values (total jobs, pending jobs, revenue, etc.)
3. Call dashboard API
4. Compare values

**Test Cases:**
- [ ] Total jobs match
- [ ] Pending jobs match
- [ ] Completed jobs match
- [ ] Failed jobs match
- [ ] Total revenue matches
- [ ] Total pages printed match

---

### 8.2 Job List Matches Desktop

**Compare API job list with desktop job list:**

1. Open desktop app job list
2. Call dashboard API with same filters
3. Compare job data

**Test Cases:**
- [ ] Job count matches
- [ ] Job IDs match
- [ ] Job statuses match
- [ ] Job filenames match
- [ ] Job timestamps match

---

### 8.3 Pricing Matches Desktop

**Compare API pricing with desktop pricing:**

1. Open desktop pricing settings
2. Call pricing API
3. Compare values

**Test Cases:**
- [ ] BW single price matches
- [ ] BW double price matches
- [ ] Color single price matches
- [ ] Color double price matches

---

## Test Summary Checklist

### ✅ Phase 2 Complete When:

- [ ] **All Auth API tests pass** (login, logout, session, refresh)
- [ ] **All Dashboard API tests pass** (KPIs, job list, filters, pagination)
- [ ] **All Config API tests pass** (get config, get pricing, update pricing)
- [ ] **Backward compatibility confirmed** (customer upload, admin, desktop still work)
- [ ] **Security tests pass** (authorization, token expiration)
- [ ] **Logging works** (API calls logged, errors logged)
- [ ] **Performance acceptable** (response times within targets)
- [ ] **Data accuracy confirmed** (API data matches desktop data)
- [ ] **No breaking changes** (existing flows unaffected)

---

## Files Modified

### New Files Created:
1. `web_interface/utils/__init__.py`
2. `web_interface/utils/jwt_helper.py`
3. `web_interface/utils/response_builder.py`
4. `web_interface/api/__init__.py`
5. `web_interface/api/middleware.py`
6. `web_interface/api/auth.py`
7. `web_interface/api/dashboard.py`
8. `web_interface/api/config.py`

### Files Modified:
1. `web_interface/app.py` - Added API blueprint registrations
2. `requirements.txt` - Added PyJWT==2.8.0

### Files NOT Modified:
- `shopkeeper_app/*` - Desktop app unchanged
- `shared/database.py` - Database models unchanged
- `shared/config.py` - Config unchanged
- All existing routes in `app.py` - Unchanged

---

## New API Endpoints Added

### Authentication (4 endpoints):
- `POST /api/auth/login` - Login shopkeeper
- `POST /api/auth/logout` - Logout shopkeeper
- `GET /api/auth/session` - Get current session
- `POST /api/auth/refresh` - Refresh session token

### Dashboard (1 endpoint):
- `GET /api/shop/<shop_id>/dashboard` - Get dashboard KPIs and job list

### Config (3 endpoints):
- `GET /api/shop/<shop_id>/config` - Get full shop config
- `GET /api/shop/<shop_id>/pricing` - Get pricing config
- `PUT /api/shop/<shop_id>/pricing` - Update pricing config

**Total: 8 new endpoints**

---

## Backward Compatibility Confirmation

### ✅ Existing Behavior Preserved:

1. **Customer Upload Flow**
   - Customer can still upload files via web interface
   - Jobs are created in database
   - WebSocket notifications sent to desktop

2. **Desktop App**
   - Desktop app still uses direct database access
   - Desktop login works (AuthManager)
   - Desktop dashboard works (direct DB queries)
   - Desktop can view/update jobs (direct DB)
   - Desktop can view/update pricing (direct DB)

3. **Admin Panel**
   - Admin routes still work
   - Admin can manage shops

4. **WebSocket Server**
   - WebSocket server still runs
   - Desktop can connect via WebSocket
   - Notifications still sent

### ✅ No Breaking Changes:

- All existing routes still work
- All existing database queries still work
- All existing WebSocket events still work
- Desktop app does NOT use APIs yet (Phase 3)

---

## Next Steps (Phase 3)

After Phase 2 testing is complete:

1. **Desktop API Client Implementation**
   - Create `shopkeeper_app/api_client.py`
   - Implement HTTP request wrapper
   - Implement session token management

2. **Desktop Auth Migration**
   - Replace `AuthManager.login_shopkeeper()` with API call
   - Store session token in memory
   - Update WebSocket connection with token

3. **Desktop Dashboard Migration**
   - Replace dashboard DB queries with API calls
   - Implement periodic refresh
   - Update UI with API data

---

**END OF TEST CHECKLIST**
