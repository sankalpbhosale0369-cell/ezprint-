# EzPrint Client-Server Migration Roadmap
## Visual Summary & Quick Reference

**Document Version:** 1.0  
**Date:** 2026-02-09  
**Companion to:** CLIENT_SERVER_ARCHITECTURE_DESIGN.md

---

## Current vs. Target Architecture

### CURRENT ARCHITECTURE (Fat Client)

```
┌─────────────────────────────────────────────────────────────┐
│                    DESKTOP APP (shopkeeper_app/)            │
│  ┌────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ PyQt5 UI   │  │ AuthManager  │  │ PrinterManager     │  │
│  │ (dashboard)│  │ (auth.py)    │  │ (printer_manager)  │  │
│  └─────┬──────┘  └──────┬───────┘  └─────────┬──────────┘  │
│        │                │                     │              │
│        └────────────────┼─────────────────────┘              │
│                         │                                    │
│                         ▼                                    │
│              ┌──────────────────────┐                        │
│              │ DIRECT DB ACCESS     │ ◄── PROBLEM!          │
│              │ (SQLAlchemy ORM)     │                        │
│              └──────────────────────┘                        │
│                         │                                    │
└─────────────────────────┼────────────────────────────────────┘
                          │
                          ▼
                ┌─────────────────────┐
                │  PostgreSQL DB      │
                │  (shared.database)  │
                └─────────────────────┘
                          ▲
                          │
┌─────────────────────────┼────────────────────────────────────┐
│                         │                                    │
│              ┌──────────────────────┐                        │
│              │ DIRECT DB ACCESS     │ ◄── ALSO PROBLEM!     │
│              │ (SQLAlchemy ORM)     │                        │
│              └──────────────────────┘                        │
│                         ▲                                    │
│        ┌────────────────┼─────────────────────┐              │
│        │                │                     │              │
│  ┌─────┴──────┐  ┌──────┴───────┐  ┌─────────┴──────────┐  │
│  │ Flask      │  │ WebSocket    │  │ Cloudinary Helper  │  │
│  │ Routes     │  │ Server       │  │ (file upload)      │  │
│  └────────────┘  └──────────────┘  └────────────────────┘  │
│                    BACKEND (web_interface/)                 │
└─────────────────────────────────────────────────────────────┘
```

**Problems:**
- ❌ Desktop has direct database access (tight coupling)
- ❌ Business logic duplicated in desktop and backend
- ❌ Desktop assumes shared file system with backend
- ❌ Desktop can modify data without backend validation
- ❌ Difficult to deploy backend separately
- ❌ Cannot scale backend independently

---

### TARGET ARCHITECTURE (Thin Client)

```
┌─────────────────────────────────────────────────────────────┐
│                    DESKTOP APP (shopkeeper_app/)            │
│  ┌────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ PyQt5 UI   │  │ API Client   │  │ PrinterManager     │  │
│  │ (dashboard)│  │ (NEW!)       │  │ (local only)       │  │
│  └─────┬──────┘  └──────┬───────┘  └─────────┬──────────┘  │
│        │                │                     │              │
│        └────────────────┼─────────────────────┘              │
│                         │                                    │
│                         ▼                                    │
│              ┌──────────────────────┐                        │
│              │ HTTP REST APIs       │ ◄── SOLUTION!         │
│              │ + WebSocket Events   │                        │
│              └──────────────────────┘                        │
│                         │                                    │
└─────────────────────────┼────────────────────────────────────┘
                          │
                          │ HTTPS (JWT Auth)
                          │ + WebSocket (Authenticated)
                          │
┌─────────────────────────▼────────────────────────────────────┐
│                    BACKEND (web_interface/)                  │
│  ┌────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ Flask      │  │ WebSocket    │  │ Cloudinary Helper  │  │
│  │ REST APIs  │  │ Event Server │  │ (file upload)      │  │
│  └─────┬──────┘  └──────┬───────┘  └─────────┬──────────┘  │
│        │                │                     │              │
│        └────────────────┼─────────────────────┘              │
│                         │                                    │
│                         ▼                                    │
│              ┌──────────────────────┐                        │
│              │ Business Logic Layer │ ◄── SINGLE SOURCE     │
│              │ (validation, calc)   │     OF TRUTH!         │
│              └──────────────────────┘                        │
│                         │                                    │
│                         ▼                                    │
│              ┌──────────────────────┐                        │
│              │ Database Access      │                        │
│              │ (SQLAlchemy ORM)     │                        │
│              └──────────────────────┘                        │
│                         │                                    │
└─────────────────────────┼────────────────────────────────────┘
                          │
                          ▼
                ┌─────────────────────┐
                │  PostgreSQL DB      │
                │  (single access)    │
                └─────────────────────┘
```

**Benefits:**
- ✅ Desktop has NO database access (loose coupling)
- ✅ Business logic centralized in backend
- ✅ Desktop downloads files via API (no file system coupling)
- ✅ Backend validates all operations
- ✅ Backend can be deployed independently
- ✅ Backend can scale horizontally

---

## Migration Phases Overview

```
┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│ Phase 1  │ Phase 2  │ Phase 3  │ Phase 4  │ Phase 5  │ Phase 6  │ Phase 7  │ Phase 8  │ Phase 9  │
│ Week 1   │ Week 2   │ Week 3   │ Week 4   │ Week 5   │ Week 6   │ Week 7   │ Week 8   │ Week 9   │
├──────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┤
│Foundation│   Auth   │Dashboard │  File    │  Config  │ Printer  │WebSocket │ Database │ Deploy & │
│          │Migration │   Data   │ Access   │Migration │  Mgmt    │  Events  │ Removal  │ Monitor  │
│          │          │Migration │Migration │          │Migration │Migration │          │          │
├──────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┤
│ Backend  │ Desktop  │ Desktop  │ Desktop  │ Desktop  │ Desktop  │ Desktop  │ Desktop  │ Prod     │
│ APIs     │ API      │ Dashboard│ File     │ Settings │ Printer  │ Print    │ Clean    │ Deploy   │
│ Created  │ Client   │ API Calls│ Download │ API Calls│ API Calls│ Events   │ DB Code  │          │
│          │          │          │          │          │          │          │          │          │
│ No       │ Replace  │ Replace  │ Replace  │ Replace  │ Replace  │ Add      │ Remove   │ Monitor  │
│ Desktop  │ Auth     │ DB       │ File     │ Pricing  │ Printer  │ Print    │ All DB   │ & Fix    │
│ Changes  │ Logic    │ Queries  │ Access   │ Queries  │ Queries  │ Status   │ Imports  │ Issues   │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
```

---

## API Endpoints Summary

### Authentication APIs
| Endpoint | Method | Purpose | Desktop Replaces |
|----------|--------|---------|------------------|
| `/api/auth/login` | POST | Login shopkeeper | `AuthManager.login_shopkeeper()` |
| `/api/auth/logout` | POST | Logout shopkeeper | Local session cleanup |
| `/api/auth/refresh` | POST | Refresh session token | N/A (new feature) |

### Dashboard APIs
| Endpoint | Method | Purpose | Desktop Replaces |
|----------|--------|---------|------------------|
| `/api/dashboard/kpis` | GET | Fetch KPIs | `db_session.query(PrintJob).filter(...)` |
| `/api/dashboard/jobs` | GET | Fetch job list | `load_jobs()` DB queries |

### Job Management APIs
| Endpoint | Method | Purpose | Desktop Replaces |
|----------|--------|---------|------------------|
| `/api/jobs/{job_id}/status` | PATCH | Update job status | `job.status = "..."; db_session.commit()` |
| `/api/jobs/{job_id}/file` | GET | Download print file | Direct file path access |

### Shop Configuration APIs
| Endpoint | Method | Purpose | Desktop Replaces |
|----------|--------|---------|------------------|
| `/api/shop/pricing` | GET | Fetch pricing config | `db_session.query(ShopPricing)` |
| `/api/shop/pricing` | PUT | Update pricing config | Pricing save DB logic |
| `/api/shop/info` | GET | Fetch shop info | `AuthManager.get_shopkeeper_by_id()` |
| `/api/shop/info` | PUT | Update shop info | `AuthManager.update_shop_info()` |

### Printer Management APIs
| Endpoint | Method | Purpose | Desktop Replaces |
|----------|--------|---------|------------------|
| `/api/printers` | GET | Fetch connected printers | `db_session.query(Printer)` |
| `/api/printers` | POST | Register new printer | Printer DB insert |
| `/api/printers/{printer_id}` | DELETE | Disconnect printer | Printer DB delete |

---

## WebSocket Events Summary

### Job Events (Backend → Desktop)
| Event | Purpose | Desktop Action |
|-------|---------|----------------|
| `new_job` | New print job created | Add to pending jobs, show notification |
| `job_cancelled` | Customer cancelled job | Remove from pending jobs |

### Printer Events (Desktop → Backend)
| Event | Purpose | Backend Action |
|-------|---------|----------------|
| `printer_heartbeat` | Periodic printer status | Update printer online/offline status |
| `printer_capability_update` | Printer capabilities changed | Update printer capabilities in DB |

### Print Status Events (Desktop → Backend)
| Event | Purpose | Backend Action |
|-------|---------|----------------|
| `print_started` | Printing started | Update job status to "printing" |
| `print_progress` | Print progress update | Update job progress |
| `print_completed` | Printing completed | Update job status to "completed" |
| `print_failed` | Printing failed | Update job status to "failed" |

### System Events (Bidirectional)
| Event | Direction | Purpose |
|-------|-----------|---------|
| `ping` | Desktop → Backend | Keep connection alive |
| `pong` | Backend → Desktop | Acknowledge ping |
| `reconnect_required` | Backend → Desktop | Notify desktop to reconnect |

---

## Migration Checklist

### Phase 1: Foundation ✅
- [ ] Implement all HTTP APIs in backend
- [ ] Add JWT authentication middleware
- [ ] Add request validation
- [ ] Test APIs with Postman
- [ ] Document API endpoints
- [ ] **NO desktop changes yet**

### Phase 2: Authentication Migration ✅
- [ ] Create `shopkeeper_app/api_client.py`
- [ ] Implement HTTP request wrapper
- [ ] Replace `AuthManager.login_shopkeeper()` with API call
- [ ] Store session token in memory
- [ ] Update WebSocket handshake with token
- [ ] Test login/logout flow
- [ ] **Backward compatibility:** Can fall back to direct DB

### Phase 3: Dashboard Data Migration ✅
- [ ] Replace KPI queries with `GET /api/dashboard/kpis`
- [ ] Replace job list queries with `GET /api/dashboard/jobs`
- [ ] Implement pagination
- [ ] Replace job status updates with `PATCH /api/jobs/{job_id}/status`
- [ ] Test dashboard load and refresh
- [ ] **Backward compatibility:** Graceful degradation if API unavailable

### Phase 4: File Access Migration ✅
- [ ] Create temp directory: `%TEMP%/ezprint_jobs/`
- [ ] Implement `GET /api/jobs/{job_id}/file` client
- [ ] Download files before printing
- [ ] Update `win32api.ShellExecute()` to use temp file
- [ ] Implement temp file cleanup
- [ ] Test printing from Cloudinary URLs
- [ ] **Backward compatibility:** Support local files

### Phase 5: Configuration Migration ✅
- [ ] Replace pricing queries with `GET /api/shop/pricing`
- [ ] Replace pricing save with `PUT /api/shop/pricing`
- [ ] Replace shop info queries with `GET /api/shop/info`
- [ ] Replace shop info update with `PUT /api/shop/info`
- [ ] Test pricing and shop info display/update
- [ ] **Backward compatibility:** Cache config locally

### Phase 6: Printer Management Migration ✅
- [ ] Replace printer queries with `GET /api/printers`
- [ ] Merge API results with local printer discovery
- [ ] Replace printer registration with `POST /api/printers`
- [ ] Replace printer delete with `DELETE /api/printers/{printer_id}`
- [ ] Implement `printer_heartbeat` event (every 10 seconds)
- [ ] Test printer discovery and connection
- [ ] **Backward compatibility:** Local printer discovery still works

### Phase 7: WebSocket Events Migration ✅
- [ ] Send `print_started` when printing starts
- [ ] Send `print_progress` during printing
- [ ] Send `print_completed` when printing completes
- [ ] Send `print_failed` on errors
- [ ] Handle `new_job` event
- [ ] Handle `job_cancelled` event
- [ ] Test real-time updates
- [ ] **Backward compatibility:** Polling fallback if WebSocket fails

### Phase 8: Database Removal ✅
- [ ] Remove `from shared.database import ...`
- [ ] Remove `SessionLocal` usage
- [ ] Remove `db_session` references
- [ ] Delete or archive `shopkeeper_app/auth.py`
- [ ] Remove `DATABASE_URL` from desktop config
- [ ] Full regression testing
- [ ] **NO backward compatibility:** Desktop requires backend API

### Phase 9: Deployment & Monitoring ✅
- [ ] Add API request logging
- [ ] Add error tracking
- [ ] Add performance metrics
- [ ] Implement retry logic in desktop
- [ ] Implement offline mode
- [ ] Load testing
- [ ] Deploy to staging
- [ ] Beta testing (2-3 shops)
- [ ] Production rollout
- [ ] Monitor for 1 week

---

## Database Coupling Removal Map

### Current Database Imports (TO BE REMOVED)

**File: `shopkeeper_app/auth.py`**
```python
from shared.database import Shopkeeper, SessionLocal  # ❌ REMOVE
```
**Replacement:**
```python
from shopkeeper_app.api_client import EzPrintAPIClient  # ✅ ADD
```

---

**File: `shopkeeper_app/dashboard.py`**
```python
from shared.database import PrintJob, Printer, ShopPricing, SessionLocal  # ❌ REMOVE
```
**Replacement:**
```python
from shopkeeper_app.api_client import EzPrintAPIClient  # ✅ ADD
```

---

**File: `shopkeeper_app/printer_manager.py`**
```python
from shared.database import Printer, SessionLocal  # ❌ REMOVE
```
**Replacement:**
```python
from shopkeeper_app.api_client import EzPrintAPIClient  # ✅ ADD
```

---

### Database Query Replacements

#### Authentication Queries

**BEFORE (Direct DB):**
```python
# shopkeeper_app/auth.py
def login_shopkeeper(self, username, password):
    shopkeeper = self.db.query(Shopkeeper).filter(
        (Shopkeeper.username == username) | (Shopkeeper.email == username)
    ).first()
    # ... password verification ...
```

**AFTER (API):**
```python
# shopkeeper_app/auth.py (or removed entirely)
def login_shopkeeper(self, username, password):
    api_client = EzPrintAPIClient(base_url=BACKEND_URL)
    response = api_client.login(username, password)
    return response["data"]
```

---

#### Dashboard KPI Queries

**BEFORE (Direct DB):**
```python
# shopkeeper_app/dashboard.py
def load_kpis(self):
    total_jobs = self.db_session.query(PrintJob).filter(
        PrintJob.shop_id == self.shop_id
    ).count()
    
    pending_jobs = self.db_session.query(PrintJob).filter(
        PrintJob.shop_id == self.shop_id,
        PrintJob.status == "pending"
    ).count()
    
    # ... more queries ...
```

**AFTER (API):**
```python
# shopkeeper_app/dashboard.py
def load_kpis(self):
    response = self.api_client.get_dashboard_kpis(
        shop_id=self.shop_id,
        period="today"
    )
    kpis = response["data"]
    
    self.total_jobs_label.setText(str(kpis["total_jobs"]))
    self.pending_jobs_label.setText(str(kpis["pending_jobs"]))
    # ... update UI ...
```

---

#### Job List Queries

**BEFORE (Direct DB):**
```python
# shopkeeper_app/dashboard.py
def load_jobs(self):
    jobs = self.db_session.query(PrintJob).filter(
        PrintJob.shop_id == self.shop_id,
        PrintJob.status == "pending"
    ).order_by(PrintJob.created_at.desc()).limit(50).all()
    
    for job in jobs:
        # ... populate table ...
```

**AFTER (API):**
```python
# shopkeeper_app/dashboard.py
def load_jobs(self):
    response = self.api_client.get_dashboard_jobs(
        shop_id=self.shop_id,
        status="pending",
        limit=50,
        offset=0,
        sort_by="created_at",
        sort_order="desc"
    )
    jobs = response["data"]["jobs"]
    
    for job in jobs:
        # ... populate table ...
```

---

#### Job Status Updates

**BEFORE (Direct DB):**
```python
# shopkeeper_app/dashboard.py
def update_job_status(self, job_id, status):
    job = self.db_session.query(PrintJob).filter(
        PrintJob.job_id == job_id
    ).first()
    
    if job:
        job.status = status
        job.updated_at = datetime.utcnow()
        self.db_session.commit()
```

**AFTER (API):**
```python
# shopkeeper_app/dashboard.py
def update_job_status(self, job_id, status):
    response = self.api_client.update_job_status(
        job_id=job_id,
        shop_id=self.shop_id,
        status=status
    )
    # UI updates automatically via WebSocket event
```

---

#### Pricing Queries

**BEFORE (Direct DB):**
```python
# shopkeeper_app/dashboard.py
def load_pricing(self):
    pricing = self.db_session.query(ShopPricing).filter(
        ShopPricing.shop_id == self.shop_id
    ).first()
    
    if pricing:
        self.bw_single_input.setText(str(pricing.bw_single))
        # ... more fields ...
```

**AFTER (API):**
```python
# shopkeeper_app/dashboard.py
def load_pricing(self):
    response = self.api_client.get_shop_pricing(shop_id=self.shop_id)
    pricing = response["data"]
    
    self.bw_single_input.setText(str(pricing["bw_single"]))
    # ... more fields ...
```

---

#### Printer Queries

**BEFORE (Direct DB):**
```python
# shopkeeper_app/printer_manager.py
def load_connected_printers(self):
    printers = self.db_session.query(Printer).filter(
        Printer.shop_id == self.shop_id,
        Printer.is_active == True
    ).all()
    
    return [p.printer_name for p in printers]
```

**AFTER (API):**
```python
# shopkeeper_app/printer_manager.py
def load_connected_printers(self):
    response = self.api_client.get_printers(shop_id=self.shop_id)
    printers = response["data"]["printers"]
    
    return [p["printer_name"] for p in printers if p["is_active"]]
```

---

## File Access Migration

### Current File Access (TO BE REPLACED)

**BEFORE (Direct File Path):**
```python
# shopkeeper_app/dashboard.py
def print_job(self, job_id):
    job = self.db_session.query(PrintJob).filter(
        PrintJob.job_id == job_id
    ).first()
    
    file_path = job.file_path  # Assumes local file system access
    
    win32api.ShellExecute(
        0,
        "print",
        file_path,  # ❌ Direct file path
        None,
        ".",
        0
    )
```

**AFTER (API Download):**
```python
# shopkeeper_app/dashboard.py
def print_job(self, job_id):
    # Download file to temp directory
    temp_dir = os.path.join(os.environ["TEMP"], "ezprint_jobs", job_id)
    os.makedirs(temp_dir, exist_ok=True)
    temp_file = os.path.join(temp_dir, "document.pdf")
    
    self.api_client.download_job_file(
        job_id=job_id,
        shop_id=self.shop_id,
        output_path=temp_file  # ✅ Download to temp
    )
    
    win32api.ShellExecute(
        0,
        "print",
        temp_file,  # ✅ Use temp file
        None,
        ".",
        0
    )
    
    # Clean up after printing
    # (Implement cleanup logic)
```

---

## Safety Guarantees Summary

### ✅ Printing Remains Local
- Desktop downloads file via API
- Desktop calls `win32api.ShellExecute()` locally
- Desktop manages printer spooler locally
- Desktop sends status updates to backend

### ✅ UI Remains Local
- PyQt5 UI code stays in desktop app
- No web-based UI for shopkeeper
- Desktop fetches data via API and renders locally

### ✅ No Breaking Changes
- Each phase maintains backward compatibility
- Dual-mode operation during migration
- Feature flags enable/disable API usage
- Graceful degradation if API unavailable

### ✅ Data Consistency
- Database migrations with Alembic
- API versioning during transition
- Transaction safety in all API endpoints
- Audit logging for debugging

### ✅ Performance
- API caching for frequently accessed data
- Batch operations for efficiency
- WebSocket for real-time updates (no polling)
- Local file caching for re-prints

---

## Risk Mitigation Summary

| Risk | Mitigation |
|------|------------|
| **API Unavailability** | Offline mode, local cache, graceful degradation, health checks |
| **Network Latency** | Optimistic UI updates, request timeouts, retry logic, loading indicators |
| **Session Expiration** | Long session duration (8 hours), auto-refresh, session persistence, graceful re-login |
| **WebSocket Disconnection** | Auto-reconnect, exponential backoff, missed events fetch, connection status UI |
| **File Download Failures** | Retry logic, resume support, fallback to direct path, clear error messages |

---

## Success Metrics

### Technical Metrics
- ✅ API uptime: > 99.9%
- ✅ API response time: < 500ms (p95)
- ✅ WebSocket uptime: > 99.5%
- ✅ File download success rate: > 99%
- ✅ Desktop crash rate: < 0.1%

### Business Metrics
- ✅ User satisfaction: > 4.5/5
- ✅ Support tickets: < 5 per week
- ✅ Downtime incidents: 0 per month
- ✅ Data loss incidents: 0

---

## Next Steps

1. **Review this roadmap** with development team
2. **Get approval** for migration plan
3. **Set up project tracking** (assign tasks)
4. **Start Phase 1** (Backend API implementation)

---

**END OF ROADMAP**
