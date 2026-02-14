"""
Lifecycle asset cleanup worker for PrintJobs.
Deletes local and cloud assets associated with terminal jobs after 24 hours.
"""
import os
import json
import logging
from datetime import datetime, timedelta
import cloudinary
import cloudinary.uploader
from shared.database import SessionLocal, PrintJob

# Setup logging
logger = logging.getLogger(__name__)

# Configure Cloudinary (ensure configuration is accessible to worker)
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True
)

def delete_local_previews(preview_paths_json):
    """
    Safely delete local preview files from a JSON-serialized list of paths.
    Idempotent and exception-safe. No DB access.
    """
    if not preview_paths_json:
        return True
    
    try:
        file_paths = json.loads(preview_paths_json)
        if not isinstance(file_paths, list):
            return True
            
        for path in file_paths:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
                    logger.info(f"[CLEANUP] Deleted local preview: {path}")
            except Exception as e:
                logger.warning(f"[CLEANUP] Could not delete file {path}: {e}")
        return True
    except (json.JSONDecodeError, TypeError):
        return True 
    except Exception as e:
        logger.error(f"[CLEANUP] Unexpected error in delete_local_previews: {e}")
        return False

def delete_cloudinary_asset(public_id, file_type):
    """
    Safely delete a Cloudinary asset by public_id.
    Idempotent and exception-safe. No DB access.
    """
    if not public_id:
        return True
        
    try:
        image_exts = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff']
        resource_type = "image" if file_type and file_type.lower() in image_exts else "raw"
        
        result = cloudinary.uploader.destroy(public_id, resource_type=resource_type)
        
        if result.get("result") in ["ok", "not found"]:
            logger.info(f"[CLEANUP] Cloudinary asset processed: {public_id}")
            return True
        return True
    except Exception as e:
        logger.error(f"[CLEANUP] Error deleting Cloudinary asset {public_id}: {e}")
        return False

def run_asset_cleanup():
    """
    Background worker to delete temporary assets associated with PrintJob 
    records 24 hours after completion.
    """
    db = SessionLocal()
    try:
        threshold = datetime.utcnow() - timedelta(hours=24)
        
        jobs = db.query(PrintJob).filter(
            PrintJob.status.in_(['Completed', 'Failed', 'Cancelled']),
            PrintJob.completed_at != None,
            PrintJob.completed_at < threshold,
            PrintJob.assets_deleted == False
        ).all()
        
        if not jobs:
            return

        logger.info(f"[LIFECYCLE] Found {len(jobs)} jobs for batch asset cleanup")
        
        for job in jobs:
            if delete_job_assets(job):
                db.commit()
                logger.info(f"[LIFECYCLE] Batch asset cleanup finalized for job: {job.job_id}")
            else:
                db.rollback()
                
    except Exception as e:
        logger.error(f"[LIFECYCLE] Cleanup worker error: {str(e)}")
    finally:
        db.close()
