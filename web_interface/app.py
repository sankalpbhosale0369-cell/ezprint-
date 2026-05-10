
"""
Flask web application for customer interface
"""

import os
import json
import uuid
import io  
from PIL import Image, ImageOps
from datetime import datetime, timedelta, timezone
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory, url_for
from flask_socketio import SocketIO, emit, join_room, disconnect
from flask_cors import CORS
from werkzeug.utils import secure_filename
from shared.cloudinary_helper import upload_file_to_cloudinary
import logging
import sys
import time
import shutil
import threading

# Add parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import Shopkeeper, PrintJob, ShopPricing, License, SessionLocal, init_database
from shared.file_processor import save_uploaded_file, get_page_count, create_preview_image, create_preview_image_with_layout, allowed_file, generate_multi_page_previews, parse_page_range, combine_pages_into_layout_sheets, combine_images_to_pdf, classify_color_pages, calculate_billing, build_color_page_dict
from shared import config as cfg  # use centralized config (env-driven)
from shared.config import UPLOAD_FOLDER, MAX_FILE_SIZE, WEB_HOST, WEB_PORT
from shared.global_error_handler import (
    global_error_handler, safe_execute, safe_database_action, 
    initialize_error_handling
)
# Admin blueprint
from web_interface.admin import admin_bp

# Import new API blueprints
from web_interface.api.auth import auth_bp
from web_interface.api.dashboard import dashboard_bp
from web_interface.api.config import config_bp
from web_interface.api.internal import internal_bp
from web_interface.utils.jwt_helper import validate_token

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
# Use env-driven SECRET_KEY; in prod must be provided
app.config['SECRET_KEY'] = cfg.SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# Initialize SocketIO with Redis message queue for horizontal scaling
# Decide async mode dynamically
async_mode = "threading"

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode=async_mode,
    message_queue=cfg.REDIS_URL if cfg.ENV == "prod" else None,
    logger=False,
    engineio_logger=False
)

CORS(app, resources={r"/api/*": {"origins": cfg.ALLOWED_ORIGINS}})


# Register admin blueprint (isolated from customer flows)
app.register_blueprint(admin_bp)

# Register new API blueprints (Phase 2: Backend API Implementation)
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(config_bp)
app.register_blueprint(internal_bp)

# Database session (request-scoped)
from sqlalchemy.orm import scoped_session
db_session = scoped_session(SessionLocal)

@app.teardown_appcontext
def _shutdown_session(exception=None):  # ensure session is removed per-request
    try:
        db_session.remove()
    except Exception:
        pass

# Shop occupancy tracking is now handled by SocketIO/Redis rooms

# ── Upload dedup locks ────────────────────────────────────────────────────────
# Per-dedup-key locks prevent the check-then-insert race condition when two
# identical upload requests arrive simultaneously (e.g. double-click).
# _upload_locks_mutex guards mutations to the dict itself.
_upload_locks: dict = {}
_upload_locks_mutex = threading.Lock()


# ── Preview Session Infrastructure (Phase 2A — skeleton only) ────────────────
# Upload-once, preview-by-reference architecture.
# This section is ADDITIVE ONLY — no existing request path uses it yet.
# All code below is inert until the frontend is wired to the new endpoints.

# Session TTL and limits
_PREVIEW_SESSION_TTL_SECONDS = 1800   # 30 minutes sliding window
_PREVIEW_SESSION_MAX_COUNT = 100      # Max concurrent sessions (memory ceiling)
_PREVIEW_SESSION_CLEANUP_INTERVAL = 60  # Cleanup scan every 60 seconds
_PREVIEW_SESSIONS_DIR = UPLOAD_FOLDER / "preview_sessions"

# Bootstrap preview_sessions directory (startup-safe)
_PREVIEW_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


class PreviewSession:
    """In-memory state for a single preview session.

    Each session represents ONE uploaded file and caches expensive
    processing results (page_count, color_classification) so that
    subsequent preview-render requests can skip re-computation.

    Dual-storage model (Background Upload Architecture):
      - preview_file_path: compressed preview file → used ONLY for rendering
      - original_file_path: full-resolution original → used ONLY for printing
      These are NEVER mixed. Preview rendering reads preview_file_path.
      Print submission reads original_cloudinary_url.

    Thread safety: each session has its own `lock` that serialises
    render operations.  The global `_preview_sessions_mutex` guards
    mutations to the session registry dict itself.
    """

    # NOTE: __slots__ removed in favour of __dict__ to support the
    # backward-compatible `file_path` property alongside new fields.
    # Memory impact is negligible at _PREVIEW_SESSION_MAX_COUNT=100.

    def __init__(self, session_id, file_path, original_filename,
                 file_size, file_type):
        self.session_id = session_id
        self.created_at = time.time()
        self.last_accessed = time.time()
        self.ttl_seconds = _PREVIEW_SESSION_TTL_SECONDS

        # ── Preview file (compressed) — used ONLY for rendering ──────
        self.preview_file_path = file_path
        self.preview_file_type = file_type

        # ── Original file — used ONLY for printing ───────────────────
        self.original_file_path = None
        self.original_cloudinary_url = None
        self.original_cloudinary_public_id = None
        self.original_upload_status = 'pending'  # pending|uploading|ready|failed
        self.original_upload_started_at = None
        self.original_upload_completed_at = None
        self.print_job_created = False  # Set True after PrintJob is created

        # ── Shared metadata ──────────────────────────────────────────
        self.original_filename = original_filename
        self.file_size = file_size
        self.file_type = file_type
        self.page_count = None               # Populated at session creation
        self.color_classification = None     # Populated at session creation
        self.current_preview_paths = []      # Paths to latest preview JPEGs
        self.lock = threading.Lock()         # Per-session render serialisation

    @property
    def file_path(self):
        """Backward-compatible alias for preview_file_path.

        The render endpoint reads `session.file_path` — this ensures
        it always gets the preview (compressed) file, never the original.
        """
        return self.preview_file_path

    @file_path.setter
    def file_path(self, value):
        """Setter for backward compat (session creation sets file_path)."""
        self.preview_file_path = value

    @property
    def is_expired(self):
        return (time.time() - self.last_accessed) > self.ttl_seconds

    def touch(self):
        """Extend session lifetime (sliding window)."""
        self.last_accessed = time.time()

    def __repr__(self):
        age = int(time.time() - self.created_at)
        return (f"<PreviewSession {self.session_id[:8]}... "
                f"type={self.file_type} age={age}s "
                f"original={self.original_upload_status}>")


# Global session registry — mirrors _upload_locks pattern
_preview_sessions: dict = {}                  # session_id → PreviewSession
_preview_sessions_mutex = threading.Lock()     # Guards dict mutations


def _cleanup_preview_session(session):
    """Delete all disk assets for a preview session.

    Called by the cleanup daemon and by explicit session destroy.
    Safe to call multiple times (idempotent).

    Phase 6 (Background Upload Architecture):
    Also deletes orphan Cloudinary assets if the original was uploaded
    but no PrintJob was ever created from it.
    """
    try:
        # ── Disk cleanup (preview + original local files) ────────────
        session_dir = _PREVIEW_SESSIONS_DIR / session.session_id
        if session_dir.exists():
            shutil.rmtree(str(session_dir), ignore_errors=True)
            logger.debug(f"PREVIEW SESSION: Cleaned up directory for {session.session_id[:8]}")

        # ── Cloudinary orphan cleanup ────────────────────────────────
        # If original was uploaded to Cloudinary but never used for a
        # PrintJob, delete the Cloudinary asset to prevent storage leaks.
        if (getattr(session, 'original_cloudinary_url', None)
                and getattr(session, 'original_upload_status', None) == 'ready'
                and not getattr(session, 'print_job_created', False)):
            try:
                from shared.cloudinary_helper import delete_file_from_cloudinary
                deleted = delete_file_from_cloudinary(session.original_cloudinary_url)
                if deleted:
                    logger.info(f"PREVIEW SESSION: Deleted orphan Cloudinary asset "
                                f"for {session.session_id[:8]}")
                else:
                    logger.warning(f"PREVIEW SESSION: Orphan Cloudinary delete "
                                   f"returned false for {session.session_id[:8]}")
            except Exception as cloud_err:
                logger.warning(f"PREVIEW SESSION: Orphan Cloudinary cleanup "
                               f"error for {session.session_id[:8]}: {cloud_err}")
    except Exception as e:
        logger.warning(f"PREVIEW SESSION: Cleanup error for {session.session_id[:8]}: {e}")


def _preview_session_cleanup_daemon():
    """Background daemon that evicts expired preview sessions.

    Runs every _PREVIEW_SESSION_CLEANUP_INTERVAL seconds.
    Acquires _preview_sessions_mutex only briefly to snapshot + mutate the dict.
    Disk cleanup runs OUTSIDE the lock to avoid blocking session creation.
    """
    logger.info("PREVIEW SESSION: Cleanup daemon started "
                f"(interval={_PREVIEW_SESSION_CLEANUP_INTERVAL}s, "
                f"ttl={_PREVIEW_SESSION_TTL_SECONDS}s)")
    while True:
        try:
            time.sleep(_PREVIEW_SESSION_CLEANUP_INTERVAL)

            # Phase 1: Identify expired sessions under lock
            expired_sessions = []
            with _preview_sessions_mutex:
                expired_ids = [
                    sid for sid, s in _preview_sessions.items()
                    if s.is_expired
                ]
                for sid in expired_ids:
                    expired_sessions.append(_preview_sessions.pop(sid))

            # Phase 2: Delete disk assets OUTSIDE lock (may be slow)
            for session in expired_sessions:
                logger.info(f"PREVIEW SESSION: Evicting expired session "
                            f"{session.session_id[:8]} "
                            f"(age={int(time.time() - session.created_at)}s)")
                _cleanup_preview_session(session)

            if expired_sessions:
                logger.info(f"PREVIEW SESSION: Evicted {len(expired_sessions)} "
                            f"expired session(s). Active: {len(_preview_sessions)}")

        except Exception as e:
            # CRITICAL: Never crash the daemon — log and continue
            logger.error(f"PREVIEW SESSION: Cleanup daemon error: {e}")


def _preview_session_startup_sweep():
    """Remove orphaned preview session directories from previous runs.

    Called once at startup. Handles unclean shutdowns where in-memory
    sessions were lost but files remain on disk.
    Uses directory mtime to determine age (Windows-safe).
    """
    try:
        if not _PREVIEW_SESSIONS_DIR.exists():
            return

        now = time.time()
        swept = 0
        for entry in _PREVIEW_SESSIONS_DIR.iterdir():
            if not entry.is_dir():
                continue
            try:
                dir_age = now - entry.stat().st_mtime
                if dir_age > _PREVIEW_SESSION_TTL_SECONDS:
                    shutil.rmtree(str(entry), ignore_errors=True)
                    swept += 1
            except Exception as e:
                logger.warning(f"PREVIEW SESSION: Startup sweep error "
                               f"for {entry.name}: {e}")

        if swept:
            logger.info(f"PREVIEW SESSION: Startup sweep removed "
                        f"{swept} orphaned session dir(s)")
        else:
            logger.info("PREVIEW SESSION: Startup sweep — no orphans found")

    except Exception as e:
        logger.error(f"PREVIEW SESSION: Startup sweep failed: {e}")


# ── Start cleanup daemon + run startup sweep ─────────────────────────────────
_preview_session_startup_sweep()

_preview_cleanup_thread = threading.Thread(
    target=_preview_session_cleanup_daemon,
    daemon=True,
    name="preview-session-cleanup"
)
_preview_cleanup_thread.start()


# ── Phase 1B: Background proxy generation (fire-and-forget) ──────────────────
# Spawns a daemon thread to generate a lightweight proxy JPEG after upload.
# The upload request NEVER waits for this. Failures are logged and swallowed.
def _trigger_background_proxy_generation(file_path, file_type,
                                         original_filename=None,
                                         file_size=None):
    """Spawn a daemon thread to generate a lightweight proxy asset.

    Called once at the end of a successful upload.  The proxy is written to
    ``uploads/proxies/`` and is used ONLY for future preview optimisation —
    it is never sent to the printer.

    A deterministic proxy_id is computed from (original_filename, file_size)
    so that the preview resolver can locate the cached proxy without any
    shared state or DB lookup.

    Safety guarantees:
    - Upload latency: unaffected (thread.start() returns in <1ms)
    - Upload response: unaffected (proxy result is not included)
    - Upload success/failure: unaffected (all errors swallowed)
    - Print pipeline: unaffected (proxy is never referenced by print code)
    - Rollback: remove this function + its single call site
    """
    # Only proxy-generate for supported file types
    PROXY_SUPPORTED_TYPES = {
        'jpg', 'jpeg', 'png', 'webp', 'bmp', 'tiff',
        'pdf', 'docx', 'doc', 'pptx', 'ppt', 'xlsx', 'xls',
    }

    file_type_lower = (file_type or '').lower().strip()
    if file_type_lower not in PROXY_SUPPORTED_TYPES:
        logger.debug(f"PROXY: Skipping unsupported type '{file_type}'")
        return

    if not file_path:
        logger.debug("PROXY: Skipping — no file path provided")
        return

    def _proxy_worker():
        """Background worker — fully isolated, daemon thread."""
        local_path = None
        is_temp = False
        try:
            from shared.file_processor import (
                generate_proxy_asset, ensure_local_path,
                _compute_proxy_lookup_key,
            )

            # Resolve to a local file (downloads from Cloudinary if URL)
            local_path, is_temp = ensure_local_path(file_path)

            if not local_path or not os.path.exists(local_path):
                logger.warning(
                    f"PROXY: Could not resolve local path for '{file_path}'"
                )
                return

            logger.debug(f"PROXY: Thread started for {file_type_lower} file")

            # Compute deterministic proxy_id so the preview resolver can
            # find this proxy via the same (filename, size) key.
            proxy_id = None
            if original_filename and file_size:
                proxy_id = _compute_proxy_lookup_key(
                    original_filename, file_size
                )

            result = generate_proxy_asset(
                local_path, file_type_lower, proxy_id=proxy_id
            )

            if result.get('success'):
                logger.debug(
                    f"PROXY: Generated — "
                    f"id={result['proxy_id']}, "
                    f"size={result['proxy_size_bytes'] / 1024:.0f}KB, "
                    f"type={result['source_type']}"
                )
            else:
                logger.warning(
                    f"PROXY: Generation failed — {result.get('error', 'unknown')}"
                )

        except Exception as e:
            # CRITICAL: Never propagate — completely silent to upload flow
            logger.warning(f"PROXY: Background generation error — {e}")

        finally:
            # Cleanup temp download if we fetched from Cloudinary
            if is_temp and local_path and os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except Exception:
                    pass

    # Spawn daemon thread — upload request never waits/joins
    proxy_thread = threading.Thread(target=_proxy_worker, daemon=True)
    proxy_thread.start()


@app.route('/')
def index():
    """Home page"""
    return render_template('index.html')

@app.route('/upload/<shop_id>')
def upload_page(shop_id):
    """Upload page for specific shop"""
    def _load_upload_page():
        # Verify shop exists
        shopkeeper = db_session().query(Shopkeeper).filter(Shopkeeper.shop_id == shop_id).first()
        if not shopkeeper:
            return render_template('error.html', message="Shop not found"), 404
        
        return render_template('upload.html', 
                             shop_id=shop_id, 
                             shop_name=shopkeeper.shop_name)
    
    return safe_execute(_load_upload_page, error_context="UPLOAD_PAGE_LOAD", 
                       default_return=(render_template('error.html', message="Error loading page"), 500))

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Handle file upload (supports both single file and XEROX file[] array)"""
    def _handle_upload():
        shop_id = request.form.get('shop_id')
        if not shop_id:
            return jsonify({'error': 'Shop ID required'}), 400
            
        cloudinary_public_id = None
        
        # Verify shop exists
        shopkeeper = db_session().query(Shopkeeper).filter(Shopkeeper.shop_id == shop_id).first()
        if not shopkeeper:
            return jsonify({'error': 'Shop not found'}), 404
        
        source = request.form.get('source', 'print')  # 'xerox' or 'print'
        
        # Handle XEROX flow (multiple images)
        if source == 'xerox':
            if 'file[]' not in request.files:
                return jsonify({'error': 'No images uploaded'}), 400
            
            files = request.files.getlist('file[]')
            if not files or len(files) == 0:
                return jsonify({'error': 'No images selected'}), 400
            
            # Validate images
            for idx, file in enumerate(files):
                if file.filename == '':
                    return jsonify({'error': f'Image {idx + 1} is empty'}), 400
                
                # Validate MIME type (only images)
                if not file.content_type or not file.content_type.startswith('image/'):
                    return jsonify({'error': f'Image {idx + 1} is not a valid image file'}), 400
                
                # Validate file size (5MB per image)
                file.seek(0, 2)  # Seek to end
                file_size_bytes = file.tell()
                file.seek(0)  # Reset to beginning
                if file_size_bytes > MAX_FILE_SIZE:
                    return jsonify({'error': f'Image {idx + 1} exceeds maximum size of {MAX_FILE_SIZE / 1024 / 1024}MB'}), 400
            
            logger.info(f"XEROX upload: shop {shop_id}, images={len(files)}")
            
            # Save images temporarily and combine into PDF
            import re
            safe_shop_id = re.sub(r'[^A-Za-z0-9_-]', '_', (shop_id or 'unknown'))[:64]
            temp_dir = UPLOAD_FOLDER / safe_shop_id / f"temp_{uuid.uuid4()}"
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            try:
                # Save all images
                image_paths = []
                for idx, file in enumerate(files):
                    filename = f"scan_{idx + 1}.png"
                    image_path = temp_dir / filename
                    file.save(str(image_path))
                    image_paths.append(str(image_path))
                
                # Combine images into PDF
                pdf_path = temp_dir / "scanned_document.pdf"
                combine_images_to_pdf(image_paths, str(pdf_path))
                
                # Move PDF to final location (use same shop directory structure as regular uploads)
                final_dir = UPLOAD_FOLDER / safe_shop_id
                final_dir.mkdir(parents=True, exist_ok=True)
                unique_filename = f"{uuid.uuid4()}.pdf"
                final_pdf_path = final_dir / unique_filename
                
                import shutil
                shutil.move(str(pdf_path), str(final_pdf_path))
                
                # Clean up temp directory
                shutil.rmtree(str(temp_dir), ignore_errors=True)
                
                # Calculate file size
                file_size = final_pdf_path.stat().st_size
                original_filename = f"scanned_document_{int(datetime.now().timestamp() * 1000)}.pdf"
                file_type = 'pdf'
                
                # 🔥 Upload combined PDF to Cloudinary (PRODUCTION SAFE)
                cloudinary_url, public_id = upload_file_to_cloudinary(
                    str(final_pdf_path),
                    safe_shop_id,
                    original_filename
                )

                file_path = cloudinary_url
                cloudinary_public_id = public_id

                # Optional: delete local file after upload (recommended for Render)
                try:
                    os.remove(final_pdf_path)
                except Exception:
                    pass

            except Exception as e:
                logger.error(f"XEROX upload error: {e}")
                # Clean up on error
                if temp_dir.exists():
                    shutil.rmtree(str(temp_dir), ignore_errors=True)
                return jsonify({'error': f'Failed to process scanned images: {str(e)}'}), 500
        
        else:
            # Handle PRINT flow (single file)
            # Check if file is present
            if 'file' not in request.files:
                return jsonify({'error': 'No file uploaded'}), 400
            
            file = request.files['file']
            if file.filename == '':
                return jsonify({'success': False, 'error': 'No file received.'}), 400
            
            # CHECK 2 — Empty file (0 bytes)
            file.seek(0, 2)  # seek to end
            size = file.tell()
            file.seek(0)     # reset
            if size == 0:
                return jsonify({'success': False, 'error': 'Uploaded file is empty.'}), 400
            
            # CHECK 3 — Unsupported file type
            if not allowed_file(file.filename):
                return jsonify({'success': False, 'error': 'File type not supported.'}), 400
            
            # Save file (EXTENDED: capture cloudinary_public_id)
            file_path, original_filename, file_size, file_type, cloudinary_public_id = save_uploaded_file(file, shop_id)
            if not file_path:
                return jsonify({'error': 'Invalid file type'}), 400
        
        # Get print settings
        print_settings = {
            'page_range': request.form.get('page_range', ''),
            'copies': int(request.form.get('copies', 1)),
            'page_size': request.form.get('page_size', 'A4'),
            'orientation': request.form.get('orientation', 'Portrait'),
            'print_side': request.form.get('print_side', 'Single'),
            'color_mode': request.form.get('color_mode', 'Black & White'),
            'layout_pages': int(request.form.get('layout_pages', 1)),
            'layout_type': request.form.get('layout_type', 'normal')
        }
        
        # Get total page count
        total_page_count = get_page_count(file_path, file_type)
        
        # Calculate actual pages to print (handle page range if specified)
        page_range_str = print_settings.get('page_range', '').strip()
        selected_pages = None
        if page_range_str:
            try:
                # Parse page range to get selected pages
                selected_pages = parse_page_range(page_range_str, total_page_count)
                if selected_pages:
                    actual_page_count = len(selected_pages)
                else:
                    # Invalid range, use all pages
                    actual_page_count = total_page_count
                    selected_pages = list(range(1, total_page_count + 1))
            except (ValueError, Exception) as e:
                logger.warning(f"Error parsing page range '{page_range_str}': {e}, using all pages")
                actual_page_count = total_page_count
                selected_pages = list(range(1, total_page_count + 1))
        else:
            # No page range, use all pages
            actual_page_count = total_page_count
            selected_pages = list(range(1, total_page_count + 1))
        
        # Calculate total amount based on pricing
        # Get shop pricing (or use defaults)
        pricing = db_session().query(ShopPricing).filter(ShopPricing.shop_id == shop_id).first()
        if pricing:
            bw_single, bw_double = pricing.bw_single, pricing.bw_double
            color_single, color_double = pricing.color_single, pricing.color_double
        else:
            # Use default pricing
            bw_single, bw_double, color_single, color_double = 2.0, 1.5, 10.0, 8.0
        
        # Calculate amount with SMART PER-PAGE COLOR BILLING
        color_mode = print_settings.get('color_mode', 'Black & White')
        
        # ── Phase 3A: Build color_page_dict from user-selected color pages ──
        # If user specified which pages are color, use that for billing.
        # If absent → color_page_dict=None → all pages billed as color (existing behavior).
        color_page_dict = None
        _raw_cp_upload = request.form.get('color_pages', None)
        if _raw_cp_upload and color_mode.lower() != 'black & white':
            try:
                import json as _json_upload
                _parsed_cp_upload = _json_upload.loads(_raw_cp_upload)
                if isinstance(_parsed_cp_upload, list):
                    color_page_dict = build_color_page_dict(_parsed_cp_upload, total_page_count)
                    if color_page_dict:
                        logger.info(f"UPLOAD BILLING: Using user-selected color pages, "
                                    f"color_count={sum(1 for v in color_page_dict.values() if v == 'color')}")
            except (ValueError, TypeError, json.JSONDecodeError):
                color_page_dict = None  # Fallback: ignore malformed input
        _color_pages_json = None
        if color_page_dict:
            _color_pages_json = json.dumps(sorted(pg for pg, m in color_page_dict.items() if m == 'color'))
        
        pricing_dict = {
            'bw_single': bw_single, 'bw_double': bw_double,
            'color_single': color_single, 'color_double': color_double
        }
        
        billing = calculate_billing(
            color_mode=color_mode,
            print_side=print_settings.get('print_side', 'Single'),
            copies=print_settings.get('copies', 1),
            layout_pages=print_settings.get('layout_pages', 1),
            selected_pages=selected_pages,
            color_page_dict=color_page_dict,
            pricing=pricing_dict
        )
        
        total_amount = billing['total_amount']
        color_sheets = billing['color_sheets']
        bw_sheets = billing['bw_sheets']
        page_count = billing['page_count']
        
        logger.info(f"Smart Billing calculation: color_sheets={color_sheets}, bw_sheets={bw_sheets}, total={total_amount:.2f}")
        
        # TRACE A: About to create PrintJob for shop
        logger.info(f"TRACE A: About to create PrintJob for shop {shop_id}, amount={total_amount:.2f}")
        
        # CAPTURE PREVIEWS (multi-page) for lifecycle management
        preview_paths_json = None
        try:
            _, preview_paths = generate_multi_page_previews(
                file_path, 
                file_type, 
                print_settings.get('page_size', 'A4'),
                print_settings.get('orientation', 'Portrait'),
                print_settings.get('color_mode', 'Black & White'),
                print_settings.get('layout_pages', 1)
            )
            if preview_paths:
                preview_paths_json = json.dumps(preview_paths)
        except Exception as e:
            logger.warning(f"Preview generation failed during upload: {e}")
        
        # ── Duplicate upload guard (10-second window, race-condition safe) ──
        # LAYER 1 — per-key in-process lock: serialises concurrent requests
        # that share the same (shop_id, filename, file_size) signature so
        # only one thread can execute the DB check+insert at a time.
        # LAYER 2 — 10-second DB window: still checked inside the lock so
        # browser retries and network replays are also rejected.
        dedup_key = f"{shop_id}:{original_filename}:{file_size}"

        with _upload_locks_mutex:
            if dedup_key not in _upload_locks:
                _upload_locks[dedup_key] = threading.Lock()
            _dedup_lock = _upload_locks[dedup_key]

        print_job = None
        try:
            with _dedup_lock:
                # --- critical section: check then insert are now atomic ---
                dedup_cutoff = datetime.utcnow() - timedelta(seconds=10)
                existing_dup = db_session().query(PrintJob).filter(
                    PrintJob.shop_id == shop_id,
                    PrintJob.filename == original_filename,
                    PrintJob.file_size == file_size,
                    PrintJob.created_at >= dedup_cutoff
                ).first()
                if existing_dup:
                    logger.warning(
                        f"Duplicate upload blocked: shop={shop_id}, "
                        f"file={original_filename}, size={file_size}, "
                        f"existing_job={existing_dup.job_id}"
                    )
                    return jsonify({
                        'success': True,
                        'job_id': existing_dup.job_id,
                        'file_type': existing_dup.file_type,
                        'message': 'File already uploaded',
                        'duplicate': True
                    })

                # No duplicate found — create the print job inside the lock
                print_job = PrintJob(
                    shop_id=shop_id,
                    filename=original_filename,
                    file_path=file_path,
                    file_size=file_size,
                    file_type=file_type,
                    amount=total_amount,
                    total_pages=page_count,
                    cloudinary_public_id=cloudinary_public_id,
                    preview_paths=preview_paths_json,
                    **print_settings
                )
                # Phase 3A: Persist user-selected color pages for audit/reprint
                if _color_pages_json:
                    print_job.color_pages = _color_pages_json

                dbi = db_session()
                dbi.add(print_job)
                dbi.commit()
                # --- end critical section ---
        finally:
            # Clean up the per-key lock once this request is done to prevent
            # unbounded memory growth (safe: any other waiter already acquired
            # it before we try to remove it, so removal only affects new comers).
            with _upload_locks_mutex:
                _upload_locks.pop(dedup_key, None)
        
        # TRACE B: PrintJob committed with status
        logger.info(f"TRACE B: PrintJob committed with status={print_job.status}, job_id={print_job.job_id}")
        
        # TRACE C: About to notify shopkeeper
        logger.info(f"TRACE C: About to notify shop {shop_id} for job {print_job.job_id}")
        
        # Notify shopkeeper via parallel channels (Step 3 Migration)
        try:
            logger.info(f"Sending parallel new_print_job notification for job {print_job.job_id} to shop {shop_id}")
            notify_shop_v2(shop_id, {
                'type': 'new_print_job',
                'job': {
                    'job_id': print_job.job_id,
                    'shop_id': shop_id,
                    'filename': original_filename,
                    'file_size': file_size,
                    'file_type': file_type,
                    'page_count': page_count,
                    'status': print_job.status,  # Explicitly include status (should be "Pending")
                    'print_settings': print_settings,
                    'created_at': print_job.created_at.isoformat()
                }
            })
            logger.info(f"✓ Parallel notification sent for job {print_job.job_id}")
        except Exception as e:
            logger.error(f"Failed to notify shopkeeper: {e}")
        
        # ── Phase 1B: Background proxy generation (fire-and-forget) ──
        # Runs AFTER: DB commit, Cloudinary upload, shopkeeper notification
        # Runs BEFORE: response returned to customer
        # Impact on upload latency: ZERO (thread.start() returns in <1ms)
        _trigger_background_proxy_generation(
            file_path, file_type,
            original_filename=original_filename,
            file_size=file_size
        )
        
        # Do not return absolute server paths
        return jsonify({
            'success': True,
            'job_id': print_job.job_id,
            'file_type': file_type,
            'message': 'File uploaded successfully'
        })
    
    return safe_execute(_handle_upload, error_context="FILE_UPLOAD", 
                       default_return=(jsonify({'error': 'Upload failed due to internal error'}), 500))

@app.route('/api/preview', methods=['POST'])
def create_preview():
    """
    Create multi-page document preview from uploaded file.
    
    BUG FIX: Previously only generated first page preview.
    Now generates separate preview images for ALL pages, enabling
    proper multi-page navigation in the frontend.
    """
    try:
        # Get file from request
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        # Enforce allowlist before saving
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type'}), 400
        
        # Get customization settings
        shop_id = request.form.get('shop_id')
        page_size = request.form.get('page_size', 'A4')
        orientation = request.form.get('orientation', 'Portrait')
        color_mode = request.form.get('color_mode', 'Color')
        page_range = request.form.get('page_range', '').strip()  # PAGE RANGE FIX: Get page range from request
        layout_pages = int(request.form.get('layout_pages', 1))  # LAYOUT FIX: Get pages per sheet setting
        
        # Debug logging
        logger.info(f"Multi-page preview request - orientation: {orientation}, color_mode: {color_mode}, page_range: {page_range}, layout_pages: {layout_pages}")
        
        # Save file temporarily
        temp_filename = f"temp_{uuid.uuid4()}.{file.filename.rsplit('.', 1)[1].lower()}"
        temp_path = UPLOAD_FOLDER / temp_filename
        file.save(str(temp_path))
        
        # Get file type
        file_type = file.filename.rsplit('.', 1)[1].lower()

        # Get total pages BEFORE deleting temp file
        total_document_pages = get_page_count(str(temp_path), file_type)
        
        # Parse page range
        selected_pages = list(range(1, total_document_pages + 1))
        page_range_error = None
        if page_range:
            try:
                selected_pages = parse_page_range(page_range, total_document_pages) or selected_pages
            except Exception as e:
                page_range_error = str(e)

        # Color detection for billing
        color_page_dict = None
        if color_mode.lower() != 'black & white':
            color_page_dict = classify_color_pages(str(temp_path), file_type)

        # Generate final print PDF (SAME pipeline as actual print)
        from shared.file_processor import generate_final_print_pdf, resolve_preview_source
        import fitz as _fitz

        # ── Phase 1C: Use cached proxy for preview if available ──
        # Pure cache lookup — no processing.  Falls back to original on miss.
        # Page count, color detection, and billing above ALWAYS use the
        # original temp_path so those results remain at full fidelity.
        preview_source, _used_proxy = resolve_preview_source(
            str(temp_path), file_type, original_filename=file.filename
        )

        final_pdf = generate_final_print_pdf(
            file_path=preview_source,
            file_type='jpg' if _used_proxy else file_type,
            page_size=page_size,
            orientation=orientation,
            layout_pages=layout_pages,
            color_mode=color_mode,
            page_range=page_range,
            preview_mode=True
        )

        # Cleanup temp file
        if os.path.exists(str(temp_path)):
            os.remove(str(temp_path))

        # Convert PDF pages to preview images
        preview_urls = []
        preview_dir = UPLOAD_FOLDER / "previews"
        preview_dir.mkdir(exist_ok=True)

        doc = _fitz.open(final_pdf)
        MAX_PREVIEW_PAGES = 50  # Safety ceiling for very large documents
        total_preview_pages = min(len(doc), MAX_PREVIEW_PAGES)

        # ── Phase 2: Read optional color_pages for mixed color/BW preview (legacy path) ──
        raw_color_pages_legacy = request.form.get('color_pages', None)
        color_pages_set_legacy = None
        if raw_color_pages_legacy and color_mode == 'Color':
            try:
                import json as _json_legacy
                _parsed_cp = _json_legacy.loads(raw_color_pages_legacy)
                if isinstance(_parsed_cp, list):
                    color_pages_set_legacy = set(int(p) for p in _parsed_cp if isinstance(p, (int, float)) and p > 0)
            except (ValueError, TypeError, json.JSONDecodeError):
                color_pages_set_legacy = None

        for page_num in range(total_preview_pages):
            page = doc[page_num]
            # Phase 1D-B: 0.8x is sufficient — output is downscaled to 800px max width.
            # This code ONLY runs in the preview route, never in the print path.
            scale = 0.8
            mat = _fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes("png")))

            if img.width > 800:
                ratio = 800 / img.width
                img = img.resize((800, int(img.height * ratio)), Image.Resampling.LANCZOS)

            # ── Phase 2: Apply grayscale for non-color sheets (legacy path) ──
            if color_pages_set_legacy is not None:
                try:
                    _lp = max(1, layout_pages)
                    _start_idx = page_num * _lp
                    _doc_pages_on_sheet = selected_pages[_start_idx:_start_idx + _lp]
                    _has_color = any(dp in color_pages_set_legacy for dp in _doc_pages_on_sheet)
                    if not _has_color:
                        img = ImageOps.grayscale(img).convert('RGB')
                except Exception as _gs_err:
                    logger.warning(f"PREVIEW: Grayscale transform failed on sheet {page_num+1}: {_gs_err}")

            preview_filename = f"preview_{uuid.uuid4().hex[:8]}_sheet_{page_num+1}.jpg"
            preview_path = preview_dir / preview_filename

            img.save(str(preview_path), "JPEG", quality=60, optimize=True)
            preview_urls.append(f'/api/preview/{preview_filename}')

        doc.close()

        # Cleanup final PDF
        try:
            os.remove(final_pdf)
        except Exception:
            pass

        # Calculate billing
        total_amount = 0
        color_sheets = 0
        bw_sheets = 0

        if shop_id:
            pricing = db_session().query(ShopPricing).filter(ShopPricing.shop_id == shop_id).first()
            pricing_dict = {
                'bw_single': pricing.bw_single if pricing else 2.0,
                'bw_double': pricing.bw_double if pricing else 1.5,
                'color_single': pricing.color_single if pricing else 10.0,
                'color_double': pricing.color_double if pricing else 8.0
            }
            billing = calculate_billing(
                color_mode=color_mode,
                print_side=request.form.get('print_side', 'Single'),
                copies=int(request.form.get('copies', 1)),
                layout_pages=layout_pages,
                selected_pages=selected_pages,
                color_page_dict=color_page_dict,
                pricing=pricing_dict
            )
            total_amount = billing['total_amount']
            color_sheets = billing['color_sheets']
            bw_sheets = billing['bw_sheets']

        response_data = {
            'success': True,
            'total_pages': len(preview_urls),
            'total_document_pages': total_document_pages,
            'selected_document_pages': len(selected_pages),
            'layout_pages': layout_pages,
            'previews': preview_urls,
            'total_amount': total_amount,
            'color_sheets': color_sheets,
            'bw_sheets': bw_sheets,
            'selected_pages': selected_pages,
            'preview_url': preview_urls[0] if preview_urls else None
        }

        if page_range_error:
            response_data['page_range_warning'] = page_range_error

        return jsonify(response_data)
            
    except Exception as e:
        logger.error(f"Preview error: {e}")
        return jsonify({'error': f'Preview failed: {str(e)}'}), 500

@app.route('/api/preview-from-path', methods=['POST'])
def create_preview_from_path():
    """Create document preview from existing file path"""
    try:
        data = request.get_json()
        file_path = data.get('file_path')
        file_type = data.get('file_type')
        page_range = data.get('page_range', '1')
        page_size = data.get('page_size', 'A4')
        orientation = data.get('orientation', 'Portrait')
        
        if not file_path or not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        
        # Create preview image
        preview_path = create_preview_image(file_path, file_type, page_range, page_size, orientation)
        
        if preview_path:
            # Create a URL that can be served by Flask
            preview_filename = os.path.basename(preview_path)
            return jsonify({
                'success': True,
                'preview_url': f'/api/preview/{preview_filename}'
            })
        else:
            return jsonify({'error': 'Failed to create preview'}), 500
            
    except Exception as e:
        logger.error(f"Preview error: {e}")
        return jsonify({'error': f'Preview failed: {str(e)}'}), 500

@app.route('/api/preview/<filename>')
def serve_preview(filename):
    """Serve preview images"""
    try:
        # Find the preview file in uploads directory
        uploads_dir = UPLOAD_FOLDER
        for root, dirs, files in os.walk(uploads_dir):
            if filename in files:
                preview_path = os.path.join(root, filename)
                return send_from_directory(os.path.dirname(preview_path), filename)
        
        return jsonify({'error': 'Preview not found'}), 404
    except Exception as e:
        logger.error(f"Error serving preview: {e}")
        return jsonify({'error': 'Failed to serve preview'}), 500


# ── Preview Session Endpoints (Phase 2B — session creation) ──────────────────
# Upload-once, preview-by-reference architecture.
# These endpoints are ADDITIVE — the old /api/preview route is untouched.
# Frontend is NOT wired to these yet (Phase 2C).

@app.route('/api/preview/session', methods=['POST'])
def create_preview_session():
    """Upload file ONCE and create a preview session.

    The file is saved into an isolated session directory and expensive
    metadata (page_count, color_classification) is computed once and
    cached in the in-memory PreviewSession object.

    Subsequent /api/preview/render requests can reference the session_id
    to re-render with different settings WITHOUT re-uploading the file.

    Thread safety:
      - _preview_sessions_mutex guards registry dict mutations ONLY
      - File I/O and metadata computation run OUTSIDE the lock
      - Lock hold time is microseconds (dict insert only)
    """
    try:
        # ── 1. Session capacity guard ────────────────────────────────────
        with _preview_sessions_mutex:
            if len(_preview_sessions) >= _PREVIEW_SESSION_MAX_COUNT:
                logger.warning(f"PREVIEW SESSION: Max session limit reached "
                               f"({_PREVIEW_SESSION_MAX_COUNT})")
                return jsonify({
                    'success': False,
                    'error': 'Server busy — too many active preview sessions. '
                             'Please try again shortly.'
                }), 503

        # ── 2. File validation ───────────────────────────────────────────
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        if not allowed_file(file.filename):
            return jsonify({'success': False, 'error': 'File type not supported'}), 400

        # Check file is not empty
        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)
        if file_size == 0:
            return jsonify({'success': False, 'error': 'Uploaded file is empty'}), 400

        # ── 3. Generate session ID and create session directory ──────────
        session_id = uuid.uuid4().hex  # 32-char hex, URL-safe
        session_dir = _PREVIEW_SESSIONS_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        previews_dir = session_dir / "previews"
        previews_dir.mkdir(exist_ok=True)

        # ── 4. Save file to session directory ────────────────────────────
        original_filename = secure_filename(file.filename) or f"upload_{session_id[:8]}"
        file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'pdf'
        saved_filename = f"source.{file_ext}"
        saved_path = session_dir / saved_filename
        file.save(str(saved_path))

        actual_size = saved_path.stat().st_size
        logger.info(f"PREVIEW SESSION: File saved — session={session_id[:8]}, "
                     f"name={original_filename}, size={actual_size}, type={file_ext}")

        # ── 5. Compute page count (outside lock) ────────────────────────
        # PERF: classify_color_pages() REMOVED from critical path.
        # It was the dominant bottleneck (10–25s).  Color classification
        # is NOT needed for preview rendering — it only affects billing.
        # The render endpoint handles color_classification=None safely
        # (calculate_billing treats None as "all color" — pessimistic).
        # classify_color_pages() remains available in file_processor.py
        # for future use (manual color-page selection, analytics, etc.).
        try:
            page_count = get_page_count(str(saved_path), file_ext)
        except Exception as e:
            logger.warning(f"PREVIEW SESSION: page_count failed: {e}")
            page_count = 1  # Safe fallback

        # ── 6. Create PreviewSession and register in memory ──────────────
        session = PreviewSession(
            session_id=session_id,
            file_path=str(saved_path),
            original_filename=original_filename,
            file_size=actual_size,
            file_type=file_ext,
        )
        session.page_count = page_count
        session.color_classification = None  # Not computed at session creation

        # Acquire lock ONLY for the dict insert (microseconds)
        with _preview_sessions_mutex:
            # Double-check capacity (another request may have filled it)
            if len(_preview_sessions) >= _PREVIEW_SESSION_MAX_COUNT:
                # Cleanup the directory we just created
                shutil.rmtree(str(session_dir), ignore_errors=True)
                return jsonify({
                    'success': False,
                    'error': 'Server busy — too many active preview sessions.'
                }), 503
            _preview_sessions[session_id] = session

        logger.info(f"PREVIEW SESSION: Created — id={session_id[:8]}, "
                     f"pages={page_count}, "
                     f"active_sessions={len(_preview_sessions)}")

        # ── 7. Return session metadata ───────────────────────────────────
        return jsonify({
            'success': True,
            'preview_session_id': session_id,
            'page_count': page_count,
            'file_type': file_ext,
            'file_size': actual_size,
            'original_filename': original_filename,
        })

    except Exception as e:
        logger.error(f"PREVIEW SESSION: Creation failed — {e}")
        # Cleanup session directory if it was created
        try:
            cleanup_dir = _PREVIEW_SESSIONS_DIR / session_id
            if cleanup_dir.exists():
                shutil.rmtree(str(cleanup_dir), ignore_errors=True)
        except Exception:
            pass
        return jsonify({'success': False, 'error': f'Session creation failed: {str(e)}'}), 500


@app.route('/api/preview/render', methods=['POST'])
def render_preview_by_session():
    """Generate preview using an existing session (settings only, no file upload).

    Reuses the SAME rendering pipeline as /api/preview but:
      - Reads file from session directory (NO re-upload)
      - Uses cached page_count (NO re-computation)
      - Uses cached color_classification (NO re-computation)
      - Stores previews in session-scoped directory

    Thread safety:
      - Registry lookup under _preview_sessions_mutex (microseconds)
      - Rendering under session.lock (prevents concurrent renders per session)
      - Different sessions render concurrently (no global render lock)
    """
    try:
        # ── 1. Parse JSON payload ────────────────────────────────────────
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'success': False, 'error': 'JSON payload required'}), 400

        session_id = data.get('preview_session_id')
        if not session_id:
            return jsonify({'success': False, 'error': 'preview_session_id is required'}), 400

        # ── 2. Session lookup (under mutex — microseconds) ───────────────
        with _preview_sessions_mutex:
            session = _preview_sessions.get(session_id)

        if session is None:
            return jsonify({
                'success': False,
                'error': 'Preview session not found or expired. Please re-upload.'
            }), 404

        if session.is_expired:
            # Evict expired session
            with _preview_sessions_mutex:
                _preview_sessions.pop(session_id, None)
            _cleanup_preview_session(session)
            return jsonify({
                'success': False,
                'error': 'Preview session expired. Please re-upload.'
            }), 410

        # Touch to extend TTL (sliding window)
        session.touch()

        # ── 3. Validate source file still exists ─────────────────────────
        if not os.path.exists(session.file_path):
            logger.error(f"PREVIEW RENDER: Source file missing for session "
                         f"{session_id[:8]}: {session.file_path}")
            with _preview_sessions_mutex:
                _preview_sessions.pop(session_id, None)
            return jsonify({
                'success': False,
                'error': 'Session source file missing. Please re-upload.'
            }), 410

        # ── 4. Extract settings from payload ─────────────────────────────
        page_size = data.get('page_size', 'A4')
        orientation = data.get('orientation', 'Portrait')
        color_mode = data.get('color_mode', 'Color')
        page_range = data.get('page_range', '').strip()
        layout_pages = int(data.get('layout_pages', 1))
        print_side = data.get('print_side', 'Single')
        copies = int(data.get('copies', 1))
        shop_id = data.get('shop_id')

        # ── Phase 2: Read optional color_pages for mixed color/BW preview ─
        # color_pages is an array of 1-indexed document page numbers that
        # should render in color.  All other pages render in grayscale.
        # If omitted or empty → existing behavior (all color or all BW).
        # This is PREVIEW-ONLY — does NOT affect printing or billing.
        raw_color_pages = data.get('color_pages', None)
        color_pages_set = None
        if raw_color_pages and isinstance(raw_color_pages, list) and color_mode == 'Color':
            try:
                color_pages_set = set(int(p) for p in raw_color_pages if isinstance(p, (int, float)) and p > 0)
                if color_pages_set:
                    logger.info(f"PREVIEW RENDER: Mixed color/BW — "
                                f"color_pages={sorted(color_pages_set)}, "
                                f"count={len(color_pages_set)}")
            except (ValueError, TypeError):
                color_pages_set = None  # Fallback: ignore malformed input

        logger.info(f"PREVIEW RENDER: session={session_id[:8]}, "
                     f"orientation={orientation}, layout={layout_pages}, "
                     f"color={color_mode}, range='{page_range}'")

        # ── 5. Acquire per-session render lock ───────────────────────────
        # This serialises renders for the SAME session (same user).
        # Different sessions render concurrently — no global bottleneck.
        with session.lock:
            # ── 6. Use cached metadata (NO recomputation) ────────────────
            total_document_pages = session.page_count or 1
            color_page_dict = session.color_classification  # May be None

            # ── Phase 3A Hotfix: Bridge user-selected color pages to billing ──
            # color_pages_set (parsed above for preview rendering) must also
            # feed into calculate_billing() via color_page_dict.
            # Without this, color_page_dict stays None → all-color fallback.
            # Pattern mirrors /api/print/submit (lines 1849-1852).
            if color_pages_set is not None and len(color_pages_set) > 0:
                _billing_dict = build_color_page_dict(list(color_pages_set), total_document_pages)
                if _billing_dict:
                    color_page_dict = _billing_dict
                    logger.info(f"PREVIEW RENDER: Phase 3A Hotfix — built color_page_dict "
                                f"from color_pages_set={sorted(color_pages_set)}, "
                                f"color={sum(1 for v in _billing_dict.values() if v == 'color')}, "
                                f"bw={sum(1 for v in _billing_dict.values() if v == 'bw')}")

            # Parse page range using cached page count
            selected_pages = list(range(1, total_document_pages + 1))
            page_range_error = None
            if page_range:
                try:
                    selected_pages = parse_page_range(page_range, total_document_pages) or selected_pages
                except Exception as e:
                    page_range_error = str(e)

            # ── 7. Clean old previews for this session ───────────────────
            session_previews_dir = _PREVIEW_SESSIONS_DIR / session_id / "previews"
            session_previews_dir.mkdir(parents=True, exist_ok=True)

            for old_preview in session.current_preview_paths:
                try:
                    if os.path.exists(old_preview):
                        os.remove(old_preview)
                except Exception:
                    pass
            session.current_preview_paths = []

            # ── 8. Generate preview ────────────────────────────────────────
            # Phase 3A: Dual path — image files use direct PIL rendering,
            # all other types use the existing PDF pipeline.
            from shared.file_processor import (
                generate_final_print_pdf, resolve_preview_source,
                generate_image_preview_direct, _IMAGE_PREVIEW_TYPES
            )

            effective_file_type = session.file_type
            preview_urls = []

            if effective_file_type in _IMAGE_PREVIEW_TYPES:
                # ── FAST PATH: Direct PIL rendering (no PDF intermediary) ──
                # Skips: ReportLab, intermediate PDF, fitz.open(), get_pixmap()
                # Only runs for image files in preview context.
                logger.info(f"PREVIEW RENDER: Using direct PIL path for {effective_file_type}")

                preview_paths = generate_image_preview_direct(
                    file_path=session.file_path,
                    file_type=effective_file_type,
                    output_dir=str(session_previews_dir),
                    page_size=page_size,
                    orientation=orientation,
                    layout_pages=layout_pages,
                    color_mode=color_mode
                )

                for p in preview_paths:
                    fname = os.path.basename(p)
                    preview_urls.append(f'/api/preview/{fname}')
                    session.current_preview_paths.append(p)

            else:
                # ── STANDARD PATH: PDF pipeline (PDFs, DOCX, etc.) ────────
                # Unchanged — uses generate_final_print_pdf + fitz rasterize.
                import fitz as _fitz

                preview_source, _used_proxy = resolve_preview_source(
                    session.file_path, session.file_type,
                    original_filename=session.original_filename
                )

                final_pdf = generate_final_print_pdf(
                    file_path=preview_source,
                    file_type='jpg' if _used_proxy else session.file_type,
                    page_size=page_size,
                    orientation=orientation,
                    layout_pages=layout_pages,
                    color_mode=color_mode,
                    page_range=page_range,
                    preview_mode=True
                )

                # Rasterize final PDF to preview JPEGs
                doc = _fitz.open(final_pdf)
                MAX_PREVIEW_PAGES = 50
                total_preview_pages = min(len(doc), MAX_PREVIEW_PAGES)

                for page_num in range(total_preview_pages):
                    page = doc[page_num]
                    scale = 0.8
                    mat = _fitz.Matrix(scale, scale)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    img = Image.open(io.BytesIO(pix.tobytes("png")))

                    if img.width > 800:
                        ratio = 800 / img.width
                        img = img.resize((800, int(img.height * ratio)), Image.Resampling.LANCZOS)

                    # ── Phase 2: Apply grayscale for non-color sheets ─────
                    # Determines which document pages are on this sheet,
                    # then grayscales if NONE of them are in color_pages_set.
                    # When color_pages_set is None → no transform (unchanged).
                    if color_pages_set is not None:
                        try:
                            _lp = max(1, layout_pages)
                            _start_idx = page_num * _lp
                            _doc_pages_on_sheet = selected_pages[_start_idx:_start_idx + _lp]
                            _has_color = any(dp in color_pages_set for dp in _doc_pages_on_sheet)
                            if not _has_color:
                                img = ImageOps.grayscale(img).convert('RGB')
                        except Exception as _gs_err:
                            logger.warning(f"PREVIEW RENDER: Grayscale transform failed "
                                           f"on sheet {page_num+1}: {_gs_err}")
                            # Fallback: render in color (never block preview)

                    preview_filename = f"preview_{uuid.uuid4().hex[:8]}_sheet_{page_num+1}.jpg"
                    preview_path = session_previews_dir / preview_filename

                    img.save(str(preview_path), "JPEG", quality=60, optimize=True)
                    preview_urls.append(f'/api/preview/{preview_filename}')
                    session.current_preview_paths.append(str(preview_path))

                doc.close()

                # Cleanup intermediate PDF
                try:
                    os.remove(final_pdf)
                except Exception:
                    pass

        # ── 10. Calculate billing (using cached color_classification) ────
        total_amount = 0
        color_sheets = 0
        bw_sheets = 0

        if shop_id:
            try:
                pricing = db_session().query(ShopPricing).filter(
                    ShopPricing.shop_id == shop_id
                ).first()
                pricing_dict = {
                    'bw_single': pricing.bw_single if pricing else 2.0,
                    'bw_double': pricing.bw_double if pricing else 1.5,
                    'color_single': pricing.color_single if pricing else 10.0,
                    'color_double': pricing.color_double if pricing else 8.0
                }
                billing = calculate_billing(
                    color_mode=color_mode,
                    print_side=print_side,
                    copies=copies,
                    layout_pages=layout_pages,
                    selected_pages=selected_pages,
                    color_page_dict=color_page_dict,
                    pricing=pricing_dict
                )
                total_amount = billing['total_amount']
                color_sheets = billing['color_sheets']
                bw_sheets = billing['bw_sheets']
            except Exception as e:
                logger.warning(f"PREVIEW RENDER: Billing calc failed: {e}")

        # Count color vs B&W from cached classification
        color_page_count = 0
        bw_page_count = 0
        if color_page_dict:
            for pg, mode in color_page_dict.items():
                if mode == 'color':
                    color_page_count += 1
                else:
                    bw_page_count += 1
        else:
            color_page_count = total_document_pages
            bw_page_count = 0

        # ── 11. Build response ───────────────────────────────────────────
        response_data = {
            'success': True,
            'total_pages': len(preview_urls),
            'total_document_pages': total_document_pages,
            'selected_document_pages': len(selected_pages),
            'layout_pages': layout_pages,
            'previews': preview_urls,
            'preview_url': preview_urls[0] if preview_urls else None,
            'total_amount': total_amount,
            'color_sheets': color_sheets,
            'bw_sheets': bw_sheets,
            'selected_pages': selected_pages,
            'color_pages': color_page_count,
            'black_white_pages': bw_page_count,
        }

        if page_range_error:
            response_data['page_range_warning'] = page_range_error

        logger.info(f"PREVIEW RENDER: Done — session={session_id[:8]}, "
                     f"sheets={len(preview_urls)}")

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"PREVIEW RENDER: Failed — {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Preview render failed: {str(e)}'}), 500


@app.route('/api/preview/session/destroy', methods=['POST'])
def destroy_preview_session():
    """Explicitly destroy a preview session and clean up disk assets.

    Removes the session from the in-memory registry and deletes the
    session directory (source file + all preview images).
    Safe to call multiple times (idempotent).
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'success': False, 'error': 'JSON payload required'}), 400

        session_id = data.get('preview_session_id')
        if not session_id:
            return jsonify({'success': False, 'error': 'preview_session_id is required'}), 400

        # Remove from registry under lock
        with _preview_sessions_mutex:
            session = _preview_sessions.pop(session_id, None)

        if session:
            _cleanup_preview_session(session)
            logger.info(f"PREVIEW SESSION: Destroyed — id={session_id[:8]}")
            return jsonify({'success': True, 'message': 'Session destroyed'})
        else:
            # Already gone (expired or never existed) — still success (idempotent)
            return jsonify({'success': True, 'message': 'Session already expired or not found'})

    except Exception as e:
        logger.error(f"PREVIEW SESSION: Destroy failed — {e}")
        return jsonify({'success': False, 'error': f'Session destroy failed: {str(e)}'}), 500


# ── Background Original Upload Endpoint (Phase 2) ────────────────────────────
# Accepts the ORIGINAL full-resolution file and persists it to Cloudinary,
# associated with an existing preview session.  Called by the frontend in the
# background AFTER the preview session is created.
#
# This endpoint is ADDITIVE — no existing code calls it.
# Frontend wiring happens in Phase 4.
# Rollback: delete this function.  Zero impact.

@app.route('/api/original/upload', methods=['POST'])
def upload_original_to_session():
    """Upload original full-resolution file and persist to Cloudinary.

    Called by the frontend in the background after preview session creation.
    The original file is stored in the session directory and uploaded to
    Cloudinary.  The Cloudinary URL is cached on the session for instant
    PrintJob creation via /api/print/submit.

    Thread safety:
      - Session lookup under _preview_sessions_mutex (microseconds)
      - Status transitions under session.lock (prevents concurrent uploads)
      - Cloudinary upload runs OUTSIDE the lock (may be slow)
      - Final status update under session.lock again

    This endpoint NEVER affects preview rendering.
    The uploaded file is stored as original_source.{ext}, completely
    separate from the preview_source.{ext} used for rendering.
    """
    try:
        # ── 1. Validate inputs ───────────────────────────────────────────
        session_id = request.form.get('preview_session_id')
        if not session_id:
            return jsonify({'success': False, 'error': 'preview_session_id is required'}), 400

        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        # Check file is not empty
        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)
        if file_size == 0:
            return jsonify({'success': False, 'error': 'Uploaded file is empty'}), 400

        # ── 2. Session lookup (under mutex — microseconds) ───────────────
        with _preview_sessions_mutex:
            session = _preview_sessions.get(session_id)

        if session is None:
            return jsonify({
                'success': False,
                'error': 'Preview session not found or expired.'
            }), 404

        if session.is_expired:
            with _preview_sessions_mutex:
                _preview_sessions.pop(session_id, None)
            _cleanup_preview_session(session)
            return jsonify({
                'success': False,
                'error': 'Preview session expired.'
            }), 410

        # Touch to extend TTL
        session.touch()

        # ── 3. Guard: prevent duplicate/concurrent uploads ───────────────
        with session.lock:
            if session.original_upload_status == 'uploading':
                return jsonify({
                    'success': False,
                    'error': 'Original upload already in progress.'
                }), 409

            if session.original_upload_status == 'ready':
                # Already uploaded — idempotent success
                logger.info(f"ORIGINAL UPLOAD: Already ready for session "
                            f"{session_id[:8]}, skipping")
                return jsonify({
                    'success': True,
                    'original_ready': True,
                    'message': 'Original already uploaded'
                })

            # Transition: pending → uploading
            session.original_upload_status = 'uploading'
            session.original_upload_started_at = time.time()

        logger.info(f"ORIGINAL UPLOAD: Starting for session {session_id[:8]}, "
                     f"size={file_size}")

        # ── 4. Save original file to session directory ───────────────────
        session_dir = _PREVIEW_SESSIONS_DIR / session_id
        if not session_dir.exists():
            # Session directory gone (race with cleanup) — fail gracefully
            with session.lock:
                session.original_upload_status = 'failed'
            return jsonify({
                'success': False,
                'error': 'Session directory missing.'
            }), 410

        file_ext = (file.filename.rsplit('.', 1)[1].lower()
                    if '.' in file.filename else 'bin')
        original_filename = f"original_source.{file_ext}"
        original_path = session_dir / original_filename
        file.save(str(original_path))

        actual_size = original_path.stat().st_size
        logger.info(f"ORIGINAL UPLOAD: File saved — session={session_id[:8]}, "
                     f"size={actual_size}")

        # ── 5. Upload to Cloudinary ──────────────────────────────────────
        # This is the expensive step (~5–20s for large files).
        # Runs OUTSIDE session.lock to avoid blocking preview renders.
        import re
        safe_shop_id = 'preview_originals'  # Generic folder for originals

        try:
            from shared.cloudinary_helper import upload_file_to_cloudinary
            from shared.file_processor import _compress_file_for_upload

            # Auto-compress if over Cloudinary limit (same as /api/upload)
            MAX_CLOUDINARY_SIZE = 9 * 1024 * 1024
            upload_path = str(original_path)
            if actual_size > MAX_CLOUDINARY_SIZE:
                compressed = _compress_file_for_upload(
                    str(original_path), file_ext
                )
                if compressed != str(original_path):
                    upload_path = compressed

            cloudinary_url, public_id = upload_file_to_cloudinary(
                upload_path, safe_shop_id,
                session.original_filename or original_filename
            )

            # Cleanup compressed temp if different from original
            if upload_path != str(original_path) and os.path.exists(upload_path):
                try:
                    os.remove(upload_path)
                except Exception:
                    pass

        except Exception as cloud_err:
            logger.error(f"ORIGINAL UPLOAD: Cloudinary failed for "
                         f"session {session_id[:8]}: {cloud_err}")
            with session.lock:
                session.original_upload_status = 'failed'
            return jsonify({
                'success': False,
                'error': f'Cloud upload failed: {str(cloud_err)}'
            }), 500

        # ── 6. Update session with Cloudinary result ─────────────────────
        with session.lock:
            session.original_file_path = str(original_path)
            session.original_cloudinary_url = cloudinary_url
            session.original_cloudinary_public_id = public_id
            session.original_upload_status = 'ready'
            session.original_upload_completed_at = time.time()

        elapsed = time.time() - session.original_upload_started_at
        logger.info(f"ORIGINAL UPLOAD: Complete — session={session_id[:8]}, "
                     f"elapsed={elapsed:.1f}s, url={cloudinary_url[:60]}...")

        # Touch again to extend TTL after long upload
        session.touch()

        return jsonify({
            'success': True,
            'original_ready': True,
            'message': 'Original file uploaded successfully'
        })

    except Exception as e:
        logger.error(f"ORIGINAL UPLOAD: Failed — {e}")
        import traceback
        traceback.print_exc()
        # Try to mark session as failed
        try:
            with _preview_sessions_mutex:
                s = _preview_sessions.get(session_id)
            if s:
                with s.lock:
                    s.original_upload_status = 'failed'
        except Exception:
            pass
        return jsonify({
            'success': False,
            'error': f'Original upload failed: {str(e)}'
        }), 500


# ── Instant Print Submit Endpoint (Phase 3) ──────────────────────────────────
# Creates a PrintJob using the pre-uploaded original file from the session.
# Accepts ONLY JSON (session_id + print settings) — NO file upload.
# Reuses ALL existing billing, dedup, and notification logic from /api/upload.
#
# This endpoint is ADDITIVE — no existing code calls it.
# Frontend wiring happens in Phase 5.
# Rollback: delete this function.  Zero impact.

@app.route('/api/print/submit', methods=['POST'])
def submit_print_from_session():
    """Create a PrintJob using a pre-uploaded original file.

    This is the FAST PATH for print submission.  Instead of re-uploading
    the original file (20-40s), the frontend sends only the session_id
    and print settings (~200 bytes JSON).

    The backend reads the pre-stored Cloudinary URL from the session and
    creates the PrintJob identically to /api/upload, minus the file upload.

    CRITICAL RULES:
      - PrintJob.file_path = original_cloudinary_url (NEVER preview file)
      - original_upload_status must be 'ready' (NEVER skip this check)
      - All billing/dedup/notification logic is identical to /api/upload

    Fallback: If this endpoint fails for ANY reason, the frontend
    automatically falls back to the legacy /api/upload flow.
    """
    def _handle_print_submit():
        # ── 1. Parse JSON payload ────────────────────────────────────────
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'success': False, 'error': 'JSON payload required'}), 400

        session_id = data.get('preview_session_id')
        shop_id = data.get('shop_id')

        if not session_id:
            return jsonify({'success': False, 'error': 'preview_session_id is required'}), 400
        if not shop_id:
            return jsonify({'success': False, 'error': 'shop_id is required'}), 400

        # ── 2. Verify shop exists ────────────────────────────────────────
        shopkeeper = db_session().query(Shopkeeper).filter(
            Shopkeeper.shop_id == shop_id
        ).first()
        if not shopkeeper:
            return jsonify({'success': False, 'error': 'Shop not found'}), 404

        # ── 3. Session lookup and validation ─────────────────────────────
        with _preview_sessions_mutex:
            session = _preview_sessions.get(session_id)

        if session is None:
            return jsonify({
                'success': False,
                'error': 'Preview session not found or expired. Please re-upload.',
                'fallback_required': True
            }), 404

        if session.is_expired:
            with _preview_sessions_mutex:
                _preview_sessions.pop(session_id, None)
            _cleanup_preview_session(session)
            return jsonify({
                'success': False,
                'error': 'Preview session expired. Please re-upload.',
                'fallback_required': True
            }), 410

        session.touch()

        # ── 4. Verify original is uploaded ───────────────────────────────
        # CRITICAL: This is the safety gate. We NEVER create a PrintJob
        # unless the original is fully uploaded to Cloudinary.
        if session.original_upload_status != 'ready':
            return jsonify({
                'success': False,
                'error': f'Original file not ready (status={session.original_upload_status}). '
                         f'Please wait or re-upload.',
                'fallback_required': True,
                'original_upload_status': session.original_upload_status
            }), 409

        if not session.original_cloudinary_url:
            return jsonify({
                'success': False,
                'error': 'Original Cloudinary URL missing despite ready status.',
                'fallback_required': True
            }), 500

        # ── 5. Extract print settings from JSON ──────────────────────────
        # Mirrors the form-field extraction in /api/upload
        print_settings = {
            'page_range': data.get('page_range', ''),
            'copies': int(data.get('copies', 1)),
            'page_size': data.get('page_size', 'A4'),
            'orientation': data.get('orientation', 'Portrait'),
            'print_side': data.get('print_side', 'Single'),
            'color_mode': data.get('color_mode', 'Black & White'),
            'layout_pages': int(data.get('layout_pages', 1)),
            'layout_type': data.get('layout_type', 'normal')
        }

        # ── 6. Use session metadata for file info ────────────────────────
        # CRITICAL: file_path is the ORIGINAL Cloudinary URL, not preview
        file_path = session.original_cloudinary_url
        original_filename = session.original_filename
        file_size = session.file_size
        file_type = session.file_type
        cloudinary_public_id = session.original_cloudinary_public_id

        logger.info(f"PRINT SUBMIT: session={session_id[:8]}, "
                     f"shop={shop_id}, file={original_filename}")

        # ── 7. Page count (use cached from session) ──────────────────────
        total_page_count = session.page_count or 1

        # ── 8. Calculate billing (identical to /api/upload) ──────────────
        page_range_str = print_settings.get('page_range', '').strip()
        selected_pages = None
        if page_range_str:
            try:
                selected_pages = parse_page_range(page_range_str, total_page_count)
                if not selected_pages:
                    selected_pages = list(range(1, total_page_count + 1))
            except (ValueError, Exception) as e:
                logger.warning(f"PRINT SUBMIT: page range parse error: {e}")
                selected_pages = list(range(1, total_page_count + 1))
        else:
            selected_pages = list(range(1, total_page_count + 1))

        pricing = db_session().query(ShopPricing).filter(
            ShopPricing.shop_id == shop_id
        ).first()
        if pricing:
            bw_single, bw_double = pricing.bw_single, pricing.bw_double
            color_single, color_double = pricing.color_single, pricing.color_double
        else:
            bw_single, bw_double, color_single, color_double = 2.0, 1.5, 10.0, 8.0

        color_mode = print_settings.get('color_mode', 'Black & White')
        color_page_dict = session.color_classification  # May be None

        # ── Phase 3A: Override with user-selected color pages if provided ──
        _raw_cp_submit = data.get('color_pages', None)
        _color_pages_json_submit = None
        if _raw_cp_submit and isinstance(_raw_cp_submit, list) and color_mode.lower() != 'black & white':
            _user_dict = build_color_page_dict(_raw_cp_submit, total_page_count)
            if _user_dict:
                color_page_dict = _user_dict
                _color_pages_json_submit = json.dumps(sorted(
                    pg for pg, m in _user_dict.items() if m == 'color'
                ))
                logger.info(f"PRINT SUBMIT: Using user-selected color pages, "
                            f"color_count={sum(1 for v in _user_dict.values() if v == 'color')}")

        pricing_dict = {
            'bw_single': bw_single, 'bw_double': bw_double,
            'color_single': color_single, 'color_double': color_double
        }

        billing = calculate_billing(
            color_mode=color_mode,
            print_side=print_settings.get('print_side', 'Single'),
            copies=print_settings.get('copies', 1),
            layout_pages=print_settings.get('layout_pages', 1),
            selected_pages=selected_pages,
            color_page_dict=color_page_dict,
            pricing=pricing_dict
        )

        total_amount = billing['total_amount']
        color_sheets = billing['color_sheets']
        bw_sheets = billing['bw_sheets']
        page_count = billing['page_count']

        logger.info(f"PRINT SUBMIT: Billing — color={color_sheets}, "
                     f"bw={bw_sheets}, total={total_amount:.2f}")

        # ── 9. Dedup guard (identical to /api/upload) ────────────────────
        dedup_key = f"{shop_id}:{original_filename}:{file_size}"

        with _upload_locks_mutex:
            if dedup_key not in _upload_locks:
                _upload_locks[dedup_key] = threading.Lock()
            _dedup_lock = _upload_locks[dedup_key]

        print_job = None
        try:
            with _dedup_lock:
                dedup_cutoff = datetime.utcnow() - timedelta(seconds=10)
                existing_dup = db_session().query(PrintJob).filter(
                    PrintJob.shop_id == shop_id,
                    PrintJob.filename == original_filename,
                    PrintJob.file_size == file_size,
                    PrintJob.created_at >= dedup_cutoff
                ).first()
                if existing_dup:
                    logger.warning(
                        f"PRINT SUBMIT: Duplicate blocked — "
                        f"shop={shop_id}, file={original_filename}, "
                        f"existing_job={existing_dup.job_id}"
                    )
                    return jsonify({
                        'success': True,
                        'job_id': existing_dup.job_id,
                        'file_type': existing_dup.file_type,
                        'message': 'File already uploaded',
                        'duplicate': True
                    })

                # ── 10. Create PrintJob ──────────────────────────────────
                # CRITICAL: file_path = original_cloudinary_url
                # This is the ORIGINAL file, NOT the compressed preview.
                print_job = PrintJob(
                    shop_id=shop_id,
                    filename=original_filename,
                    file_path=file_path,  # Original Cloudinary URL
                    file_size=file_size,
                    file_type=file_type,
                    amount=total_amount,
                    total_pages=page_count,
                    cloudinary_public_id=cloudinary_public_id,
                    **print_settings
                )
                # Phase 3A: Persist user-selected color pages for audit/reprint
                if _color_pages_json_submit:
                    print_job.color_pages = _color_pages_json_submit

                dbi = db_session()
                dbi.add(print_job)
                dbi.commit()
        finally:
            with _upload_locks_mutex:
                _upload_locks.pop(dedup_key, None)

        # ── 11. Mark session as print-job-created ────────────────────────
        # Prevents Cloudinary orphan cleanup from deleting the asset
        session.print_job_created = True

        logger.info(f"PRINT SUBMIT: PrintJob created — "
                     f"job_id={print_job.job_id}, status={print_job.status}")

        # ── 12. Notify shopkeeper (identical to /api/upload) ─────────────
        try:
            notify_shop_v2(shop_id, {
                'type': 'new_print_job',
                'job': {
                    'job_id': print_job.job_id,
                    'shop_id': shop_id,
                    'filename': original_filename,
                    'file_size': file_size,
                    'file_type': file_type,
                    'page_count': page_count,
                    'status': print_job.status,
                    'print_settings': print_settings,
                    'created_at': print_job.created_at.isoformat()
                }
            })
            logger.info(f"PRINT SUBMIT: Notification sent for job "
                         f"{print_job.job_id}")
        except Exception as e:
            logger.error(f"PRINT SUBMIT: Notification failed: {e}")

        # ── 13. Background proxy generation (same as /api/upload) ────────
        _trigger_background_proxy_generation(
            file_path, file_type,
            original_filename=original_filename,
            file_size=file_size
        )

        return jsonify({
            'success': True,
            'job_id': print_job.job_id,
            'file_type': file_type,
            'message': 'Print job created successfully (instant path)'
        })

    return safe_execute(
        _handle_print_submit,
        error_context="PRINT_SUBMIT",
        default_return=(jsonify({
            'success': False,
            'error': 'Print submit failed due to internal error',
            'fallback_required': True
        }), 500)
    )


@app.route('/api/convert-docx', methods=['POST'])
def convert_docx_to_pdf():
    """
    Convert multiple DOCX files into a single merged PDF.
    Used by the frontend multi-DOCX upload flow.
    Reuses existing convert_to_pdf() from file_processor.
    """
    try:
        if 'file[]' not in request.files:
            return jsonify({'error': 'No files uploaded'}), 400

        files = request.files.getlist('file[]')
        if not files or len(files) < 2:
            return jsonify({'error': 'At least 2 DOCX files required'}), 400

        # Validate all files are DOCX
        for idx, file in enumerate(files):
            if not file.filename.lower().endswith('.docx'):
                return jsonify({'error': f'File {idx + 1} is not a DOCX file'}), 400

        import tempfile
        import shutil
        import fitz  # PyMuPDF (already a project dependency)
        from shared.file_processor import convert_to_pdf

        temp_dir = tempfile.mkdtemp()
        converted_pdfs = []

        try:
            # Step 1: Save each DOCX and convert to PDF (preserving selection order)
            for idx, file in enumerate(files):
                safe_name = secure_filename(file.filename) or f"doc_{idx}.docx"
                docx_path = os.path.join(temp_dir, f"{idx}_{safe_name}")
                file.save(docx_path)

                pdf_path = convert_to_pdf(docx_path, 'docx')
                if pdf_path == docx_path:
                    # Conversion failed - convert_to_pdf returns original path on failure
                    return jsonify({'error': f'Failed to convert "{file.filename}" to PDF. Ensure LibreOffice or MS Word is available.'}), 500

                converted_pdfs.append(pdf_path)
                logger.info(f"DOCX convert: [{idx + 1}/{len(files)}] {file.filename} -> PDF OK")

            # Step 2: Merge all converted PDFs in order
            merged_doc = fitz.open()
            for pdf_path in converted_pdfs:
                src_doc = fitz.open(pdf_path)
                merged_doc.insert_pdf(src_doc)
                src_doc.close()

            # Step 3: Save merged PDF and return as binary
            merged_path = os.path.join(temp_dir, "merged_docx_result.pdf")
            merged_doc.save(merged_path)
            merged_doc.close()

            logger.info(f"DOCX merge complete: {len(files)} files -> {os.path.getsize(merged_path)} bytes")

            with open(merged_path, 'rb') as f:
                pdf_bytes = f.read()

            from flask import Response
            return Response(
                pdf_bytes,
                mimetype='application/pdf',
                headers={'Content-Disposition': 'attachment; filename=merged_docx.pdf'}
            )

        finally:
            # Cleanup all temp files
            shutil.rmtree(temp_dir, ignore_errors=True)
            # Also cleanup any converted PDFs outside temp_dir (defensive)
            for pdf_path in converted_pdfs:
                if os.path.exists(pdf_path) and not pdf_path.startswith(temp_dir):
                    try:
                        os.remove(pdf_path)
                    except Exception:
                        pass

    except Exception as e:
        logger.error(f"DOCX conversion error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Conversion failed: {str(e)}'}), 500

@app.route('/api/convert-mixed', methods=['POST'])
def convert_mixed_to_pdf():
    """
    Convert a mix of image, PDF, and DOCX files into a single merged PDF.
    Used by the frontend mixed-file upload flow.
    Preserves user selection order.
    Reuses existing convert_to_pdf(), combine_images_to_pdf() utilities.
    """
    try:
        if 'file[]' not in request.files:
            return jsonify({'error': 'No files uploaded'}), 400

        files = request.files.getlist('file[]')
        if not files or len(files) < 2:
            return jsonify({'error': 'At least 2 files required for mixed upload'}), 400

        import tempfile
        import shutil
        import fitz  # PyMuPDF (already a project dependency)
        from shared.file_processor import convert_to_pdf

        temp_dir = tempfile.mkdtemp()
        normalized_pdfs = []  # List of PDF paths in selection order

        try:
            for idx, file in enumerate(files):
                filename = file.filename or f'file_{idx}'
                ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
                safe_name = secure_filename(filename) or f"file_{idx}.bin"
                saved_path = os.path.join(temp_dir, f"{idx}_{safe_name}")
                file.save(saved_path)

                # Classify and normalize each file to PDF
                if ext in ('png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'webp'):
                    # Image -> single-page PDF using existing combine_images_to_pdf
                    img_pdf_path = os.path.join(temp_dir, f"{idx}_img.pdf")
                    combine_images_to_pdf([saved_path], img_pdf_path)
                    normalized_pdfs.append(img_pdf_path)
                    logger.info(f"Mixed convert: [{idx + 1}/{len(files)}] {filename} (image) -> PDF OK")

                elif ext == 'pdf':
                    # PDF -> use directly
                    normalized_pdfs.append(saved_path)
                    logger.info(f"Mixed convert: [{idx + 1}/{len(files)}] {filename} (PDF) -> direct")

                elif ext in ('docx', 'doc'):
                    # DOCX -> convert to PDF using existing convert_to_pdf
                    pdf_path = convert_to_pdf(saved_path, ext)
                    if pdf_path == saved_path:
                        # Conversion failed - convert_to_pdf returns original path on failure
                        return jsonify({'error': f'Failed to convert "{filename}" to PDF. Ensure LibreOffice or MS Word is available.'}), 500
                    normalized_pdfs.append(pdf_path)
                    logger.info(f"Mixed convert: [{idx + 1}/{len(files)}] {filename} (DOCX) -> PDF OK")

                else:
                    return jsonify({'error': f'Unsupported file type: "{filename}"'}), 400

            # Merge all normalized PDFs in selection order
            merged_doc = fitz.open()
            for pdf_path in normalized_pdfs:
                src_doc = fitz.open(pdf_path)
                merged_doc.insert_pdf(src_doc)
                src_doc.close()

            merged_path = os.path.join(temp_dir, "merged_mixed_result.pdf")
            merged_doc.save(merged_path)
            merged_doc.close()

            logger.info(f"Mixed merge complete: {len(files)} files -> {os.path.getsize(merged_path)} bytes")

            with open(merged_path, 'rb') as f:
                pdf_bytes = f.read()

            from flask import Response
            return Response(
                pdf_bytes,
                mimetype='application/pdf',
                headers={'Content-Disposition': 'attachment; filename=merged_mixed.pdf'}
            )

        finally:
            # Cleanup all temp files
            shutil.rmtree(temp_dir, ignore_errors=True)
            # Also cleanup any converted PDFs outside temp_dir (defensive)
            for pdf_path in normalized_pdfs:
                if os.path.exists(pdf_path) and not pdf_path.startswith(temp_dir):
                    try:
                        os.remove(pdf_path)
                    except Exception:
                        pass

    except Exception as e:
        logger.error(f"Mixed conversion error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Conversion failed: {str(e)}'}), 500

@app.route('/api/job/<job_id>/status')
def get_job_status(job_id):
    """Get job status"""
    try:
        job = db_session().query(PrintJob).filter(PrintJob.job_id == job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        
        return jsonify({
            'job_id': job.job_id,
            'status': job.status,
            'created_at': job.created_at.isoformat(),
            'started_at': job.started_at.isoformat() if job.started_at else None,
            'completed_at': job.completed_at.isoformat() if job.completed_at else None,
            'error_message': job.error_message
        })
        
    except Exception as e:
        logger.error(f"Error getting job status: {e}")
        return jsonify({'error': f'Failed to get job status: {str(e)}'}), 500

@app.route('/api/health')
def health_check():
    """Health check endpoint for startup verification"""
    try:
        return jsonify({
            'status': 'healthy',
            'service': 'EzPrint Web Interface',
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return jsonify({'error': f'Health check failed: {str(e)}'}), 500

@app.route('/api/ws-health')
def websocket_health_check():
    """Health check endpoint (Legacy WebSocket removed)"""
    try:
        status = {
            'websocket_server_running': False,
            'timestamp': datetime.utcnow().isoformat(),
            'info': 'Legacy asyncio WebSocket server and in-memory registry have been removed. System is fully Redis-driven.'
        }
        
        return jsonify(status)
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return jsonify({
            'websocket_server_running': False,
            'error': str(e)
        }), 500

@app.route('/api/jobs/<shop_id>')
def list_jobs(shop_id):
    """List recent jobs for a shop with statuses"""
    try:
        jobs = db_session().query(PrintJob).filter(PrintJob.shop_id == shop_id).order_by(PrintJob.created_at.desc()).limit(20).all()
        return jsonify({
            'success': True,
            'jobs': [
                {
                    'job_id': j.job_id,
                    'filename': j.filename,
                    'status': j.status,
                    'created_at': j.created_at.isoformat(),
                    'started_at': j.started_at.isoformat() if j.started_at else None,
                    'completed_at': j.completed_at.isoformat() if j.completed_at else None,
                    'error_message': j.error_message,
                    'copies': j.copies,
                    'page_range': j.page_range,
                    'layout_pages': j.layout_pages,
                } for j in jobs
            ]
        })
    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        return jsonify({'error': f'Failed to list jobs: {str(e)}'}), 500

@app.route('/api/pricing/<shop_id>')
def get_pricing(shop_id):
    """Get pricing configuration for a shop"""
    def _get_pricing():
        # Verify shop exists
        shopkeeper = db_session().query(Shopkeeper).filter(Shopkeeper.shop_id == shop_id).first()
        if not shopkeeper:
            return jsonify({'error': 'Shop not found'}), 404
        
        # Get pricing or return defaults
        pricing = db_session().query(ShopPricing).filter(ShopPricing.shop_id == shop_id).first()
        
        if pricing:
            return jsonify({
                'success': True,
                'pricing': {
                    'bw_single': pricing.bw_single,
                    'bw_double': pricing.bw_double,
                    'color_single': pricing.color_single,
                    'color_double': pricing.color_double
                }
            })
        else:
            # Return default values
            return jsonify({
                'success': True,
                'pricing': {
                    'bw_single': 2.0,
                    'bw_double': 1.5,
                    'color_single': 10.0,
                    'color_double': 8.0
                }
            })
    
    return safe_execute(_get_pricing, error_context="GET_PRICING",
                       default_return=(jsonify({'error': 'Failed to get pricing'}), 500))

# ── License Check Endpoint ────────────────────────────────────────────────────
@app.route('/api/license/check', methods=['POST'])
def license_check():
    """
    POST /api/license/check
    
    Unauthenticated endpoint — called by desktop client BEFORE login.
    Checks device license status. Creates 15-day trial for new devices.
    Fail-open: server errors return status='active' to never lock out users.
    """
    device_id = None
    try:
        data = request.get_json(silent=True) or {}
        device_id = (data.get('device_id') or '').strip()
        email = (data.get('email') or '').strip() or None
        shop_name = (data.get('shop_name') or '').strip() or None

        # 1. Validate — device_id is required
        if not device_id:
            return jsonify({
                'status': 'error',
                'days_remaining': None,
                'message': 'device_id is required',
                'trial_end': None,
                'device_id': None
            }), 400

        db = SessionLocal()
        try:
            # 2. Look up existing license
            lic = db.query(License).filter(License.device_id == device_id).first()

            now = datetime.now(timezone.utc)

            # 3. New device — create trial
            if lic is None:
                trial_end = now + timedelta(days=15)
                lic = License(
                    device_id=device_id,
                    email=email,
                    shop_name=shop_name,
                    status='trial',
                    trial_start=now,
                    trial_end=trial_end,
                )
                db.add(lic)
                db.commit()
                logger.info(f"License: new trial created for device {device_id[:12]}...")
                return jsonify({
                    'status': 'trial',
                    'days_remaining': 15,
                    'message': 'Trial started — 15 days free',
                    'trial_end': trial_end.isoformat(),
                    'device_id': device_id
                }), 200

            # 4. Existing device — evaluate status
            status = (lic.status or 'trial').lower()

            if status == 'active':
                resp_status, days_rem, msg = 'active', None, 'License is active'
                trial_end_iso = None

            elif status == 'blocked':
                resp_status, days_rem, msg = 'blocked', 0, 'Device is blocked — contact support'
                trial_end_iso = None

            elif status == 'trial':
                if lic.trial_end:
                    delta = lic.trial_end - now
                    days_rem = max(0, delta.days)
                else:
                    days_rem = 0

                if days_rem <= 0:
                    # Trial expired — persist the status change
                    lic.status = 'expired'
                    db.commit()
                    resp_status, days_rem, msg = 'expired', 0, 'Trial has expired'
                else:
                    resp_status = 'trial'
                    msg = f'{days_rem} day{"s" if days_rem != 1 else ""} remaining in your trial'

                trial_end_iso = lic.trial_end.isoformat() if lic.trial_end else None

            else:  # 'expired' or any unknown
                resp_status, days_rem, msg = 'expired', 0, 'Trial has expired'
                trial_end_iso = lic.trial_end.isoformat() if lic.trial_end else None

            # 5. Write-once email update (never overwrite existing)
            updated = False
            if email and not lic.email:
                lic.email = email
                updated = True
            if shop_name and not lic.shop_name:
                lic.shop_name = shop_name
                updated = True
            if updated:
                db.commit()

            return jsonify({
                'status': resp_status,
                'days_remaining': days_rem,
                'message': msg,
                'trial_end': trial_end_iso,
                'device_id': device_id
            }), 200

        finally:
            db.close()

    except Exception as e:
        # FAIL-OPEN: never lock out a user due to server error
        logger.error(f"License check error: {e}", exc_info=True)
        return jsonify({
            'status': 'active',
            'days_remaining': None,
            'message': 'License server unavailable - access granted',
            'trial_end': None,
            'device_id': device_id
        }), 200
    
@app.route('/uploads/<shop_id>/<filename>')
def serve_uploaded_file(shop_id, filename):
    """Serve locally stored files as fallback when Cloudinary unavailable"""
    try:
        import re
        if not re.match(r'^[A-Za-z0-9_-]+$', shop_id):
            return jsonify({'error': 'Invalid shop_id'}), 400
        if not re.match(r'^[A-Za-z0-9._-]+$', filename):
            return jsonify({'error': 'Invalid filename'}), 400
        upload_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'uploads', shop_id
        )
        full_path = os.path.join(upload_dir, filename)
        if not os.path.exists(full_path):
            return jsonify({'error': 'File not found'}), 404
        return send_from_directory(upload_dir, filename)
    except Exception as e:
        logger.error(f"Error serving local file: {e}")
        return jsonify({'error': 'File not found'}), 404

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info('Client disconnected')

@socketio.on('join_shop')
def handle_join_shop(data):
    """Handle client joining a shop room for real-time updates"""
    shop_id = data.get('shop_id')
    if shop_id:
        join_room(f'shop_{shop_id}')
        logger.info(f'Client joined shop room: {shop_id}')

@socketio.on("connect", namespace="/shops")
def handle_shop_connect():
    """Handle shop connection to /shops namespace"""
    logger.info(f"Shop attempting connection to /shops namespace: {request.sid}")

@socketio.on("register_shop", namespace="/shops")
def register_shop(data):
    """
    Authenticate and register shop to their private room.
    Expects: {"token": "JWT_TOKEN"}
    """
    token = data.get("token")
    if not token:
        logger.warning(f"Registration failed: No token provided by sid {request.sid}")
        disconnect()
        return

    # Validate JWT token
    payload = validate_token(token)
    if not payload:
        logger.warning(f"Registration failed: Invalid token from sid {request.sid}")
        disconnect()
        return

    shop_id = payload.get("shop_id")
    if not shop_id:
        logger.warning(f"Registration failed: No shop_id in token from sid {request.sid}")
        disconnect()
        return

    # Join private shop room
    join_room(shop_id)
    logger.info(f"Shop {shop_id} REGISTERED and joined room [{shop_id}] via sid {request.sid}")

    # Confirm registration to the specific client
    socketio.emit(
        "registration_confirmed",
        {"shop_id": shop_id},
        room=request.sid,
        namespace="/shops"
    )

@socketio.on("disconnect", namespace="/shops")
def handle_shop_disconnect():
    """Log shop disconnection from /shops namespace"""
    logger.info(f"Shop disconnected from /shops namespace: {request.sid}")

def notify_shop_v2(shop_id: str, payload: dict):
    """
    Notification delivery:
    Emits via SocketIO (Redis bridged)
    """
    # SocketIO delivery
    socketio.emit(
        "new_print_job",
        payload,
        room=shop_id,
        namespace="/shops"
    )
    logger.info(f"Notification emitted to SocketIO room {shop_id} [/shops]")

if __name__ == '__main__':
    # Initialize error handling
    initialize_error_handling()
    
    # Initialize database with error handling
    safe_execute(init_database, error_context="WEB_DATABASE_INIT", show_dialog=False)
    
    # Run Flask-SocketIO app with eventlet
    # Hardened for Production: host, port, debug come from cfg
    if __name__ == "__main__":
        socketio.run(
            app,
            host="0.0.0.0",
            port=int(os.environ.get("PORT", 5000)),
            debug=False
        )


