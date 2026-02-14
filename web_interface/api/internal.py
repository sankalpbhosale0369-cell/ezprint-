"""
Internal API endpoints for background tasks and maintenance.
"""
import os
import logging
import json
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from sqlalchemy import or_, and_
from shared.database import SessionLocal, PrintJob
import cloudinary.uploader
from utils.lifecycle_cleanup import delete_local_previews, delete_cloudinary_asset

logger = logging.getLogger(__name__)

internal_bp = Blueprint('internal_api', __name__, url_prefix='/internal')

INTERNAL_TOKEN = os.environ.get("INTERNAL_CLEANUP_TOKEN")

@internal_bp.route('/run-asset-cleanup', methods=['POST'])
def run_asset_cleanup_endpoint():
    """
    POST /internal/run-asset-cleanup
    Distributed-safe internal endpoint using per-row locking loop.
    """
    # 1. Security Validation
    token = request.headers.get("X-Internal-Token")
    if not INTERNAL_TOKEN or token != INTERNAL_TOKEN:
        logger.warning(f"[CLEANUP-API] Unauthorized access attempt from {request.remote_addr}")
        return jsonify({"error": "Unauthorized"}), 401

    db = SessionLocal()
    processed = 0
    deleted = 0
    errors = 0
    
    try:
        now = datetime.utcnow()
        threshold_24h = now - timedelta(hours=24)
        
        # 4. Per-row locking loop (Limit 20)
        while processed < 20:
            # Query ONE eligible PrintJob using FOR UPDATE SKIP LOCKED
            job = db.query(PrintJob).filter(
                and_(
                    PrintJob.assets_deleted == False,
                    or_(
                        and_(PrintJob.status.in_(['Cancelled', 'Failed']), PrintJob.assets_delete_scheduled == True),
                        and_(PrintJob.status == 'Completed', PrintJob.completed_at < threshold_24h),
                        and_(PrintJob.status == 'Pending', PrintJob.created_at < threshold_24h)
                    )
                )
            ).with_for_update(skip_locked=True).first()

            if not job:
                break
                
            processed += 1
            
            try:
                # One job, one transaction boundary
                success_local = delete_local_previews(job.preview_paths)
                success_cloud = delete_cloudinary_asset(job.cloudinary_public_id, job.file_type)

                # Update metadata
                job.assets_deleted = True
                job.assets_delete_attempted_at = datetime.utcnow()
                
                # Commit immediately to release lock
                db.commit()
                deleted += 1
                logger.info(f"[CLEANUP-API] Finalized cleanup for job {job.job_id}")
                
            except Exception as e:
                db.rollback()
                errors += 1
                logger.error(f"[CLEANUP-API] Failed to process job {job.job_id}: {e}")
                
    except Exception as e:
        logger.error(f"[CLEANUP-API] Fatal loop failure: {e}")
        return jsonify({"error": "Batch engine failure"}), 500
    finally:
        db.close()

    return jsonify({
        "processed": processed,
        "deleted": deleted,
        "errors": errors
    })
