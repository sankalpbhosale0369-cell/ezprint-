# FORENSIC ANALYSIS: Printer Routing & Capabilities Architecture

**Analysis Date:** 2026-01-24  
**Status:** ANALYSIS ONLY - NO CODE MODIFICATIONS

---

## 1. PRINT TRIGGER LOCATION

### Primary Print Function
**Function:** `PrinterManager.print_document_with_settings()`  
**File:** `shopkeeper_app/printer_manager.py`  
**Line:** 209  

**Signature:**
```python
def print_document_with_settings(self, file_path, file_type, settings, job_id=None)
```

**Parameters Passed to Printer:**
- `file_path` (str): Absolute path to the file
- `file_type` (str): File extension/type (pdf, png, jpg, etc.)
- `settings` (dict): Job customization settings
- `job_id` (str, optional): Unique job identifier for tracking

**Settings Dictionary Structure:**
```python
settings = {
    'copies': int,           # Number of copies
    'page_range': str,       # e.g., "1-3" or ""
    'page_size': str,        # e.g., "A4"
    'orientation': str,      # "Portrait" or "Landscape"
    'print_side': str,       # "Single" or "Double"
    'color_mode': str,       # "Color" or "Black & White"
    'layout_pages': int      # Pages per sheet (1, 2, 4, etc.)
}
```

### Call Chain to Print Trigger

**From Dashboard:**
1. `DashboardWindow.print_job(job)` - Line 8091
2. Creates `_SettingsPrintWorker` thread - Line 8133
3. Worker calls `printer_manager.print_document_with_settings()` - Line 8182

**From QR Code Print:**
1. `DashboardWindow.print_qr_code()` - Line 9103
2. Directly calls `printer_manager.print_document_with_settings()`

---

## 2. PRINTER REPRESENTATION IN CODE

### Printer Object Structure

**Primary Storage:** `PrinterManager.current_printer` (String)  
**File:** `shopkeeper_app/printer_manager.py`  
**Line:** 47  
**Type:** `str | None`

**Discovery Object:** `ThreadSafePrinterManager.cached_printers`  
**File:** `shared/thread_safe_printer_discovery.py`  
**Line:** 598  
**Type:** `List[PrinterInfo]`

### PrinterInfo Dataclass (Discovery Layer)
**File:** `shared/thread_safe_printer_discovery.py`  
**Lines:** 29-40

```python
@dataclass
class PrinterInfo:
    name: str                    # Printer name (e.g., "HP LaserJet")
    id: str                      # Printer ID (same as name)
    description: str             # User-friendly description
    connection_type: str         # "USB", "WiFi/Ethernet", "Network", etc.
    status: str                  # "Online" or "Offline"
    port_name: str               # Windows port (e.g., "USB001", "TCP_192.168.1.100")
    attributes: int              # Windows printer attributes bitmask
    ip_address: Optional[str]    # IP address for network printers
    discovery_method: Optional[str]  # How printer was discovered
```

**Attributes Available:**
- ✅ `name` - Printer name
- ✅ `connection_type` - USB, WiFi/Ethernet, Network, Virtual
- ✅ `status` - Online/Offline
- ✅ `port_name` - Windows port identifier
- ✅ `ip_address` - For network printers
- ❌ `is_color` - **NOT PRESENT**
- ❌ `is_duplex` - **NOT PRESENT**
- ❌ `busy` - **NOT PRESENT** (status polling happens during print)

### Printer Database Model
**File:** `shared/database.py`  
**Lines:** 84-94

```python
class Printer(Base):
    __tablename__ = 'printers'
    
    id = Column(Integer, primary_key=True)
    shop_id = Column(String(36), nullable=False)
    printer_name = Column(String(100), nullable=False)
    printer_id = Column(String(100), nullable=False)
    is_default = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
```

**Database Attributes:**
- ✅ `printer_name` - Name of the printer
- ✅ `is_default` - Whether this is the default printer for the shop
- ✅ `is_active` - Whether printer is active
- ❌ `is_color` - **NOT PRESENT**
- ❌ `is_duplex` - **NOT PRESENT**
- ❌ `capabilities` - **NOT PRESENT**

---

## 3. JOB CUSTOMIZATION STORAGE

### PrintJob Database Model
**File:** `shared/database.py`  
**Lines:** 38-82

### Job Customization Fields

| Job Field | Attribute Name | Type | Default | Line |
|-----------|----------------|------|---------|------|
| **Page Range** | `page_range` | String(50) | NULL | 52 |
| **Copies** | `copies` | Integer | 1 | 53 |
| **Page Size** | `page_size` | String(20) | 'A4' | 54 |
| **Orientation** | `orientation` | String(20) | 'Portrait' | 55 |
| **Single/Double Side** | `print_side` | String(20) | 'Single' | 56 |
| **Color Mode** | `color_mode` | String(20) | 'Black & White' | 57 |
| **Layout Pages** | `layout_pages` | Integer | 1 | 58 |
| **Layout Type** | `layout_type` | String(20) | 'normal' | 59 |

### Field Value Mappings

**Print Side:**
- Database: `"Single"` or `"Double"` (also accepts `"Duplex"`)
- Display: `"Single"` or `"Double"`
- Line: 56

**Color Mode:**
- Database: `"Black & White"` or `"Color"`
- Display: `"Black & White"` or `"Color"`
- Line: 57

---

## 4. PRINTER SELECTION LOGIC

### Current Architecture: **FIXED GLOBAL ROUTING**

**Selection Mechanism:** Single global `current_printer` string  
**File:** `shopkeeper_app/printer_manager.py`  
**Line:** 47

### Printer Selection Flow

**On Dashboard Startup:**
1. `DashboardWindow.__init__()` - Line 2046
2. Checks if `printer_manager.current_printer` is None
3. Attempts to load default printer from database
4. Fallback: Selects first available active printer
5. **Result:** One printer selected globally

**Selection Code (Lines 2046-2054):**
```python
if not self.printer_manager.current_printer:
    default = self.printer_manager.get_default_printer(self.shopkeeper_data['shop_id'])
    if default:
        self.printer_manager.current_printer = default
    else:
        actives = self.printer_manager.get_active_printers(self.shopkeeper_data['shop_id'])
        if actives:
            self.printer_manager.current_printer = actives[0]
```

**Manual Printer Change:**
- **Function:** `DashboardWindow.on_job_printer_changed()` - Line 6775
- **Trigger:** User selects different printer from dropdown
- **Action:** Updates `printer_manager.current_printer` globally
- **File:** `shopkeeper_app/dashboard.py`
- **Lines:** 6775-6789

**Print Execution Check:**
- **Function:** `DashboardWindow.print_job()` - Line 8093
- **Check:** `if not self.printer_manager.current_printer:`
- **Action:** Shows warning or logs error
- **Result:** Print aborted if no printer selected

---

## 5. PRINTER ROUTING CONFIRMATION

### Is Routing Fixed or Dynamic?

**VERDICT: FIXED ROUTING**

**Evidence:**
1. ✅ Only ONE `current_printer` variable exists globally
2. ✅ NO per-job printer assignment in PrintJob model
3. ✅ NO printer selection logic based on job attributes
4. ✅ NO routing rules or decision engine
5. ✅ Manual printer changes affect ALL subsequent jobs

**Current Behavior:**
- All jobs print to `printer_manager.current_printer`
- Changing printer affects all future prints
- No automatic routing based on:
  - Color mode (color vs B&W)
  - Print side (single vs duplex)
  - Job type
  - Printer capabilities

**Printer Selection Points:**
1. **Startup:** Auto-select default or first available
2. **Manual:** User changes via dropdown (affects all jobs)
3. **Print Time:** Uses whatever `current_printer` is set to

---

## 6. CAPABILITY MATCHING

### Current State: **NO CAPABILITY MATCHING**

**Missing Features:**
- ❌ No printer capability detection (color, duplex, paper size)
- ❌ No job-to-printer matching algorithm
- ❌ No validation that printer supports job requirements
- ❌ No automatic routing based on capabilities

**What Happens Today:**
1. Job requests "Color" + "Double-sided"
2. System sends to `current_printer` regardless of capabilities
3. If printer doesn't support duplex → prints single-sided
4. If printer doesn't support color → prints B&W
5. **No warnings or errors shown to user**

---

## 7. SUMMARY TABLE

### Job Field → Attribute Name

| Job Requirement | PrintJob Attribute | Type | Default |
|----------------|-------------------|------|---------|
| Single/Double Side | `print_side` | String | "Single" |
| Color/B&W | `color_mode` | String | "Black & White" |
| Copies | `copies` | Integer | 1 |
| Page Range | `page_range` | String | NULL |
| Page Size | `page_size` | String | "A4" |
| Orientation | `orientation` | String | "Portrait" |
| Layout Pages | `layout_pages` | Integer | 1 |

### Printer Capability → Attribute Name

| Printer Capability | Attribute Name | Status |
|-------------------|----------------|--------|
| Color Support | `is_color` | ❌ **NOT TRACKED** |
| Duplex Support | `is_duplex` | ❌ **NOT TRACKED** |
| Printer Name | `name` | ✅ Available |
| Connection Type | `connection_type` | ✅ Available |
| Online Status | `status` | ✅ Available |
| Port Name | `port_name` | ✅ Available |
| IP Address | `ip_address` | ✅ Available (network only) |
| Busy Status | `busy` | ❌ **NOT TRACKED** |

---

## 8. EXACT FUNCTION REFERENCES

### Where Printer is Selected Today

**Function:** `PrinterManager.set_default_printer()`  
**File:** `shopkeeper_app/printer_manager.py`  
**Lines:** 119-163  
**Purpose:** Set default printer for a shop (stored in DB)

**Function:** `DashboardWindow.on_job_printer_changed()`  
**File:** `shopkeeper_app/dashboard.py`  
**Lines:** 6775-6789  
**Purpose:** Handle manual printer selection from dropdown

**Function:** `DashboardWindow.__init__()` (startup auto-select)  
**File:** `shopkeeper_app/dashboard.py`  
**Lines:** 2046-2054  
**Purpose:** Auto-select printer on dashboard startup

### Where Print is Actually Triggered

**Function:** `PrinterManager.print_document_with_settings()`  
**File:** `shopkeeper_app/printer_manager.py`  
**Line:** 209  
**Called From:** 
- `dashboard.py:8182` (print job worker)
- `dashboard.py:9103` (QR code print)

**Printer Used:** `self.current_printer` (Line 216, 228, 344, etc.)

---

## 9. ROUTING ARCHITECTURE VERDICT

### Current State
- **Type:** Fixed Global Routing
- **Printer Selection:** Manual or auto-select on startup
- **Per-Job Routing:** ❌ Not supported
- **Capability Matching:** ❌ Not implemented
- **Dynamic Routing:** ❌ Not implemented

### Routing Flow
```
Job Created → Dashboard.print_job() → Uses printer_manager.current_printer → Print
                                              ↑
                                              |
                                    Set once, used for all jobs
```

### To Enable Dynamic Routing (Future)
Would require:
1. Add `is_color`, `is_duplex` to Printer model
2. Add `assigned_printer` to PrintJob model
3. Create routing algorithm in `print_job()` function
4. Match job requirements to printer capabilities
5. Update `print_document_with_settings()` to accept printer parameter

---

## END OF ANALYSIS

**Confirmation:** This is ANALYSIS ONLY. No code has been modified.
