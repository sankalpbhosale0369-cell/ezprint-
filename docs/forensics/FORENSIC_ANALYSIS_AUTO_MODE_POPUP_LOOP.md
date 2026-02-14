# 🔍 FORENSIC ANALYSIS: Auto Mode Job Popup Infinite Reopening

## 📋 Executive Summary

**Root Cause (Single Sentence):**  
When a shopkeeper closes a job popup using the cross (X) icon in Auto Mode, the popup's `closeEvent()` method calls `self.accept()`, which triggers the `accepted` signal instead of the `finished` signal alone, causing the dashboard to interpret the dismissal as a "PICKUP" action and immediately re-queue the same pending job for display, creating an infinite loop.

---

## 🧬 Complete Lifecycle Analysis

### 1️⃣ **Popup Dismissal Semantics**

#### **File:** `shopkeeper_app/dashboard.py`
#### **Class:** `JobPopupDialog`
#### **Lines:** 2150-2159

```python
def closeEvent(self, event):
    """Step 4: Cleanup timer on popup close to prevent orphan polling"""
    try:
        if hasattr(self, '_printer_status_timer'):
            self._printer_status_timer.stop()
            self._printer_status_timer.deleteLater()
        # Ensure finished(int) signal is emitted to reset dashboard state
        self.accept()  # ⚠️ ROOT CAUSE: Always calls accept()
    except Exception:
        self.accept()
```

**Critical Issue:**  
The `closeEvent()` method **unconditionally calls `self.accept()`** regardless of how the popup was closed.

#### **Signal Behavior in PyQt5 QDialog:**

| User Action | Method Called | Signals Emitted | Job State Changed? |
|-------------|---------------|-----------------|-------------------|
| Click "PICKUP" button | `self.accept()` | `accepted`, `finished(1)` | ✅ Yes (status → "Picked Up") |
| Click "PRINT" button (Manual) | `self.accept()` | `accepted`, `finished(1)` | ✅ Yes (status → "Printing") |
| Click X icon | `closeEvent()` → `self.accept()` | `accepted`, `finished(1)` | ❌ **NO** (status remains "Pending") |
| Press ESC key | `reject()` | `rejected`, `finished(0)` | ❌ NO |

**The Problem:**  
Closing via X icon triggers `closeEvent()`, which calls `accept()`, emitting the `accepted` signal. The dashboard interprets this as a legitimate "PICKUP" action, but **the job status in the database remains "Pending"** because no actual pickup logic was executed.

---

### 2️⃣ **Auto Mode Job Reprocessing Logic**

#### **File:** `shopkeeper_app/dashboard.py`
#### **Function:** `check_and_print_pending_jobs`
#### **Lines:** 7944-7969

```python
def check_and_print_pending_jobs(self):
    """Check for pending jobs and print them automatically if in auto mode"""
    if not self.auto_mode:
        return

    # REQUIREMENT: If a popup is active, do NOT start next printing in background.
    if self.is_popup_active:
        return
        
    try:
        # Get pending jobs
        pending_jobs = self.db.query(PrintJob).filter(
            PrintJob.shop_id == self.shopkeeper_data['shop_id'],
            PrintJob.status == 'Pending'  # ⚠️ Job still qualifies!
        ).all()
        
        for job in pending_jobs:
            # Funnel into popup system instead of printing directly.
            self.handle_new_job_popup(job)  # ⚠️ Re-queues the same job
            
    except Exception as e:
        logger.error(f"Error in auto-printing: {e}")
```

**Auto Mode Behavior:**
- Auto Mode continuously scans for jobs with `status == 'Pending'`
- When a job popup is closed (via X), the job status **remains "Pending"**
- Auto Mode immediately re-detects this job as eligible for processing
- The job is re-queued into `popup_job_queue`

---

### 3️⃣ **Job Eligibility Re-check**

#### **Why the Same Job Qualifies Again:**

**Database State After X Click:**
```python
job.status = "Pending"  # ❌ UNCHANGED
job.completed_at = None
```

**Auto Mode Query:**
```python
pending_jobs = db.query(PrintJob).filter(
    PrintJob.shop_id == shop_id,
    PrintJob.status == 'Pending'  # ✅ Still matches!
).all()
```

**Missing State Variables:**
- ❌ No `acknowledged` flag
- ❌ No `dismissed` flag  
- ❌ No `popup_shown` timestamp
- ❌ No `user_dismissed` boolean

**Result:** The job perpetually qualifies for popup display because closing via X does not mutate any persistent state.

---

### 4️⃣ **Guard & State Variables**

#### **File:** `shopkeeper_app/dashboard.py`
#### **Class:** `DashboardWindow.__init__`
#### **Lines:** 2398-2402

```python
# Sequential popup management
self.popup_job_queue = []           # Queue of jobs waiting for popup
self.is_popup_active = False        # Flag: is a popup currently shown?
self._active_job_popups = []        # List of active popup widget references
self._cancel_dialog_active = False  # Flag: is cancel dialog open?
```

#### **Popup Display Logic:**
**Function:** `display_next_popup`  
**Lines:** 7891-7942

```python
def display_next_popup(self):
    """Display the next job popup in the queue if none is currently active"""
    try:
        # SELF-CORRECTION: Reset flag if no popups are actually visible/alive
        actual_visible_popups = [p for p in self._active_job_popups if self._is_alive(p) and p.isVisible()]
        if self.is_popup_active and not actual_visible_popups and not self._cancel_dialog_active:
            logger.warning("STUCK POPUP GUARD DETECTED: is_popup_active was True but no visible popups found. Self-correcting.")
            self.is_popup_active = False

        # STRICT GUARD: Only one popup at a time. 
        if self.is_popup_active or self._cancel_dialog_active or actual_visible_popups:
            return  # ✅ Prevents simultaneous popups

        if not self.popup_job_queue:
            self.is_popup_active = False
            return
            
        job = self.popup_job_queue.pop(0)
        self.is_popup_active = True  # ⚠️ Set to True
        
        popup = JobPopupDialog(job, self)
        self._active_job_popups.append(popup)
        
        # REQUIREMENT: Next popup MUST open ONLY after PICKUP is clicked.
        def on_pickup_accepted():
            logger.info(f"PICKUP confirmed for job {job.job_id}. Triggering next queued job.")
            QTimer.singleShot(100, self.display_next_popup)  # ⚠️ Triggers next popup

        # Reset flag and cleanup on any finish (including X button or cancel)
        def on_popup_finished():
            if popup in self._active_job_popups:
                self._active_job_popups.remove(popup)
            self.is_popup_active = False  # ✅ Reset flag
            logger.debug(f"Popup for job {job.job_id} closed/finished. Guard reset.")
            # Resume queue for dismissed popups
            QTimer.singleShot(100, self.display_next_popup)  # ⚠️ Triggers next popup
            
        popup.accepted.connect(on_pickup_accepted)  # ⚠️ Fires when X is clicked (due to closeEvent)
        popup.finished.connect(on_popup_finished)   # ✅ Always fires
        
        popup.show()
        logger.info(f"Notification popup shown for job: {job.job_id}")
    except Exception as e:
        logger.error(f"Error displaying next popup: {e}")
        self.is_popup_active = False
        QTimer.singleShot(200, self.display_next_popup)
```

#### **State Variable Lifecycle:**

| Event | `is_popup_active` | `popup_job_queue` | Job Status |
|-------|-------------------|-------------------|------------|
| Job arrives | `False` → `True` | `[job1]` → `[]` | `Pending` |
| Popup shown | `True` | `[]` | `Pending` |
| **X clicked** | `True` → `False` (via `finished`) | `[]` | **`Pending`** ⚠️ |
| `on_popup_finished()` fires | `False` | `[]` | `Pending` |
| `display_next_popup()` called (100ms delay) | `False` | `[]` | `Pending` |
| Auto Mode re-scans | `False` | `[]` | `Pending` |
| `check_and_print_pending_jobs()` | `False` | `[]` → `[job1]` ⚠️ | `Pending` |
| `handle_new_job_popup()` | `False` | `[job1]` | `Pending` |
| `display_next_popup()` | `False` → `True` | `[job1]` → `[]` | `Pending` |
| **Popup reopens** | `True` | `[]` | `Pending` |

**The Loop:**  
1. `is_popup_active` is correctly reset to `False`
2. But the job status remains `Pending`
3. Auto Mode immediately re-detects the job
4. Job is re-queued
5. Popup reopens
6. Cycle repeats infinitely

---

### 5️⃣ **Event Loop & Timer Interaction**

#### **Timer Chain:**

**Sequence When X is Clicked:**

```
User clicks X
    ↓
closeEvent() fires
    ↓
self.accept() called
    ↓
accepted signal emitted  ⚠️ (Interpreted as PICKUP)
    ↓
finished signal emitted
    ↓
on_popup_finished() callback
    ↓
is_popup_active = False
    ↓
QTimer.singleShot(100, display_next_popup)
    ↓
[100ms delay]
    ↓
display_next_popup() executes
    ↓
popup_job_queue is empty → returns
    ↓
[Auto Mode timer/polling continues]
    ↓
check_and_print_pending_jobs() fires
    ↓
Queries DB for status='Pending'
    ↓
Finds the same job (status unchanged)
    ↓
handle_new_job_popup(job)
    ↓
Job added to popup_job_queue
    ↓
display_next_popup() called
    ↓
Popup reopens with same job
    ↓
[INFINITE LOOP]
```

#### **Auto Mode Trigger Points:**

**File:** `shopkeeper_app/dashboard.py`

1. **WebSocket Message Handler** (Lines 7817-7869):
```python
def handle_websocket_message(self, data):
    if message_type == 'new_print_job':
        # ...
        if self.auto_mode:
            self.check_and_print_pending_jobs()  # ⚠️ Trigger point 1
```

2. **Polling Fallback** (Lines 7454-7459):
```python
def setup_polling_timer(self):
    self.poll_timer = QTimer()
    self.poll_timer.timeout.connect(self.load_print_jobs)  # ⚠️ Trigger point 2
    self.poll_timer.setSingleShot(False)
```

3. **load_print_jobs** (Lines 8005-8014):
```python
def load_print_jobs(self, *args, **kwargs):
    # ...
    # Trigger popups for new jobs (skip on first load to prevent flooding)
    if not self.is_first_load:
        for j_id in new_job_ids:
            nj = next((j for j in jobs if j.job_id == j_id), None)
            if nj:
                self.handle_new_job_popup(nj)  # ⚠️ Trigger point 3
```

**Why Auto Mode Retries Endlessly:**
- Auto Mode assumes: **"If status == 'Pending', the job needs processing"**
- Closing via X does NOT change status
- Auto Mode has no memory of "already shown but dismissed" jobs
- No deduplication based on `job_id` in `known_job_ids` for dismissed popups

---

### 6️⃣ **Why This Happens ONLY in Auto Mode**

#### **Manual Mode Behavior:**

**File:** `shopkeeper_app/dashboard.py`  
**Function:** `set_manual_mode` (Lines 7366-7421)

```python
def set_manual_mode(self):
    """Set printing mode to manual"""
    self.auto_mode = False
    # ... UI updates only, NO check_and_print_pending_jobs() call
```

**Manual Mode Does NOT:**
- ❌ Automatically scan for pending jobs
- ❌ Call `check_and_print_pending_jobs()`
- ❌ Re-queue jobs after popup dismissal

**Manual Mode Popup Flow:**
1. Job arrives → Popup shown
2. User clicks X → Popup closes
3. Job remains `Pending`
4. **No automatic re-scan happens**
5. Job stays in list, waiting for manual "PRINT" button click

#### **Auto Mode Behavior:**

**File:** `shopkeeper_app/dashboard.py`  
**Function:** `set_auto_mode` (Lines 7306-7364)

```python
def set_auto_mode(self):
    """Set printing mode to automatic"""
    self.auto_mode = True
    # ... UI updates ...
    
    # Check for pending jobs and print them automatically
    self.check_and_print_pending_jobs()  # ⚠️ Immediately scans for pending jobs
```

**Auto Mode DOES:**
- ✅ Continuously scan for `status == 'Pending'` jobs
- ✅ Automatically re-queue jobs after popup dismissal
- ✅ Trigger `check_and_print_pending_jobs()` on:
  - Mode activation
  - WebSocket messages
  - Polling timer
  - Job list refresh

**Logical Contract Auto Mode Assumes:**
> "Any job with status='Pending' is unprocessed and should be displayed/printed immediately."

**What Auto Mode Does NOT Account For:**
- User dismissing a popup without taking action
- Popup closure via X icon vs. PICKUP button
- Temporary "do not show again" state

---

## 📊 State Machine Explanation

### **Before Closing Popup (Auto Mode Active):**

```
Job State in DB:
  job_id: "abc123"
  status: "Pending"
  
Dashboard State:
  is_popup_active: True
  popup_job_queue: []
  known_job_ids: {"abc123"}
  
Popup State:
  Visible: True
  Job: job_abc123
```

### **After Closing Popup via X Icon:**

```
Job State in DB:
  job_id: "abc123"
  status: "Pending"  ⚠️ UNCHANGED
  
Dashboard State:
  is_popup_active: False  ✅ Reset
  popup_job_queue: []
  known_job_ids: {"abc123"}  ⚠️ Still contains job
  
Popup State:
  Visible: False
  Destroyed: True
  
Signals Emitted:
  - accepted  ⚠️ (Due to closeEvent calling accept)
  - finished
```

### **100ms Later (Auto Mode Re-evaluation):**

```
Auto Mode Logic Executes:
  1. Query DB for status='Pending'
  2. Find job_abc123 (status still Pending)
  3. Check if job_id in popup_job_queue → NO
  4. Check if job_id in _active_job_popups → NO
  5. ⚠️ NO CHECK: "Was this job already dismissed by user?"
  6. Add job_abc123 to popup_job_queue
  7. Call display_next_popup()
  8. Popup reopens with same job
```

---

## 🔬 Exact Root Cause Breakdown

### **Primary Cause:**

**File:** `shopkeeper_app/dashboard.py`  
**Class:** `JobPopupDialog`  
**Method:** `closeEvent` (Lines 2150-2159)

**Issue:**  
The `closeEvent()` method unconditionally calls `self.accept()`, which emits the `accepted` signal. This signal is connected to `on_pickup_accepted()` in `display_next_popup()`, but more critically, it does NOT change the job's database status from "Pending" to any other state.

### **Secondary Causes:**

1. **No Dismissal State Tracking:**
   - No database column for `user_dismissed`
   - No in-memory set of dismissed job IDs
   - No timestamp for "last popup shown"

2. **Auto Mode Assumes Status is Truth:**
   - Auto Mode logic: `if status == 'Pending' → show popup`
   - No consideration for "user already saw and dismissed this"

3. **Signal Misuse:**
   - `closeEvent()` should call `reject()` for X icon dismissal
   - `accept()` should only be called for explicit user actions (PICKUP, PRINT)

4. **Duplicate Prevention Logic Insufficient:**
   - **File:** `dashboard.py`, Lines 7876-7880
   ```python
   def handle_new_job_popup(self, job):
       # Avoid queuing the same job ID multiple times if it's already in queue or active
       if any(q_job.job_id == job.job_id for q_job in self.popup_job_queue):
           return  # ✅ Prevents duplicate in queue
       if any(p.job.job_id == job.job_id for p in self._active_job_popups if self._is_alive(p)):
           return  # ✅ Prevents duplicate active popup
       
       self.popup_job_queue.append(job)  # ⚠️ But does NOT check if job was dismissed
   ```
   
   **Missing Check:**
   ```python
   if job.job_id in self.dismissed_job_ids:
       return  # Should prevent re-queuing dismissed jobs
   ```

---

## 🎯 Why Popup Does NOT Reopen When:

### **1. Job is Picked Up:**
- PICKUP button calls `self.accept()`
- But ALSO updates job status: `job.status = "Picked Up"`
- Auto Mode query: `status == 'Pending'` → NO MATCH
- Job no longer qualifies for re-queuing

### **2. Job is Printed:**
- Print logic updates: `job.status = "Printing"` or `"Completed"`
- Auto Mode query: `status == 'Pending'` → NO MATCH
- Job no longer qualifies for re-queuing

### **3. Auto Mode is Disabled:**
- `self.auto_mode = False`
- `check_and_print_pending_jobs()` returns early:
  ```python
  if not self.auto_mode:
      return  # ✅ No automatic re-scanning
  ```
- Job remains `Pending` but is never automatically re-queued

---

## 📝 Summary Table

| Scenario | Job Status After Action | Auto Mode Re-detects? | Popup Reopens? |
|----------|------------------------|----------------------|----------------|
| Click PICKUP | "Picked Up" | ❌ No | ❌ No |
| Click PRINT | "Printing" | ❌ No | ❌ No |
| Click X (Auto Mode) | **"Pending"** | ✅ **Yes** | ✅ **Yes** (Loop) |
| Click X (Manual Mode) | "Pending" | ❌ No (Auto Mode off) | ❌ No |
| Press ESC | "Pending" | ✅ Yes | ✅ Yes (Loop) |

---

## 🔚 Final Root Cause Summary

**Single-Sentence Root Cause:**  
In Auto Mode, closing a job popup via the X icon calls `closeEvent()` which invokes `self.accept()` without changing the job's database status from "Pending", causing Auto Mode's continuous pending job scan to immediately re-detect and re-queue the same job for popup display, creating an infinite loop because there is no persistent or in-memory tracking of user-dismissed jobs.

---

## 📂 Key Files and Functions Involved

| File | Function/Class | Lines | Role in Issue |
|------|---------------|-------|---------------|
| `dashboard.py` | `JobPopupDialog.closeEvent` | 2150-2159 | ⚠️ Calls `accept()` instead of `reject()` |
| `dashboard.py` | `DashboardWindow.check_and_print_pending_jobs` | 7944-7969 | Re-scans for `status='Pending'` jobs |
| `dashboard.py` | `DashboardWindow.handle_new_job_popup` | 7871-7889 | Queues jobs without checking dismissal state |
| `dashboard.py` | `DashboardWindow.display_next_popup` | 7891-7942 | Connects `accepted` signal to next popup trigger |
| `dashboard.py` | `DashboardWindow.set_auto_mode` | 7306-7364 | Enables continuous pending job scanning |
| `dashboard.py` | `DashboardWindow.load_print_jobs` | 7972-8348 | Triggers popups for new jobs (Lines 8009-8014) |
| `database.py` | `PrintJob` | 38-83 | No `dismissed` or `acknowledged` field |

---

**Analysis Complete. No code modifications performed as requested.**
