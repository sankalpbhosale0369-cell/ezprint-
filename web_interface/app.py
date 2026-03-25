import eventlet
eventlet.monkey_patch()

"""
Flask web application for customer interface
"""

import os
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory, url_for
from flask_socketio import SocketIO, emit, join_room, disconnect
from flask_cors import CORS
from werkzeug.utils import secure_filename
from shared.cloudinary_helper import upload_file_to_cloudinary
import logging
import sys
import threading

# Add parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import Shopkeeper, PrintJob, ShopPricing, License, SessionLocal, init_database
from shared.file_processor import save_uploaded_file, get_page_count, create_preview_image, create_preview_image_with_layout, allowed_file, generate_multi_page_previews, parse_page_range, combine_pages_into_layout_sheets, combine_images_to_pdf, classify_color_pages, calculate_billing
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
async_mode = "eventlet" if cfg.ENV == "prod" else "threading"

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
        
        # Get color page dict if color mode is Color
        color_page_dict = None
        if color_mode.lower() != 'black & white':
            color_page_dict = classify_color_pages(file_path, file_type)
        
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
        from shared.file_processor import generate_final_print_pdf
        import fitz as _fitz

        final_pdf = generate_final_print_pdf(
            file_path=str(temp_path),
            file_type=file_type,
            page_size=page_size,
            orientation=orientation,
            layout_pages=layout_pages,
            color_mode=color_mode,
            page_range=page_range
        )

        # Cleanup temp file
        if os.path.exists(str(temp_path)):
            os.remove(str(temp_path))

        # Convert PDF pages to preview images
        preview_urls = []
        preview_dir = UPLOAD_FOLDER / "previews"
        preview_dir.mkdir(exist_ok=True)

        doc = _fitz.open(final_pdf)
        total_preview_pages = len(doc)

        for page_num in range(total_preview_pages):
            page = doc[page_num]
            scale = 2.0 if layout_pages > 1 else 1.5
            mat = _fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            preview_filename = f"preview_{uuid.uuid4().hex[:8]}_sheet_{page_num+1}.png"
            preview_path = preview_dir / preview_filename
            pix.save(str(preview_path))
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
            'total_pages': total_preview_pages,
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


