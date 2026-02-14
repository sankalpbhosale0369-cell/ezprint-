"""
Dashboard API endpoints
"""
from flask import Blueprint, request
import sys
import os
import logging
from datetime import datetime, timedelta
from sqlalchemy import func

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import SessionLocal, PrintJob
from utils.response_builder import success_response, error_response
from api.middleware import require_auth

# Setup logging
logger = logging.getLogger(__name__)

dashboard_bp = Blueprint('dashboard_api', __name__, url_prefix='/api/shop')

@dashboard_bp.route('/<shop_id>/dashboard', methods=['GET'])
@require_auth
def get_dashboard(shop_id):
    """
    GET /api/shop/<shop_id>/dashboard?period=<today|week|month>&limit=50&offset=0
    
    Returns:
        {
            "success": true,
            "data": {
                "kpis": {
                    "total_jobs": 42,
                    "pending_jobs": 5,
                    "completed_jobs": 35,
                    "failed_jobs": 2,
                    "total_revenue": 1250.50,
                    "total_pages_printed": 823,
                    "period": "today"
                },
                "jobs": [...],
                "total_count": 42,
                "limit": 50,
                "offset": 0
            }
        }
    """
    try:
        # Validate shop_id matches authenticated user
        if shop_id != request.shop_id:
            logger.warning(f"Unauthorized dashboard access attempt: {request.shop_id} tried to access {shop_id}")
            return error_response("Unauthorized access to shop data", 403)
        
        # Get query parameters
        period = request.args.get('period', 'today')
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        status_filter = request.args.get('status')  # Optional: pending, completed, failed
        
        # Validate limit
        if limit > 200:
            return error_response("Limit cannot exceed 200", 400)
        
        # Calculate date range for KPIs
        now = datetime.utcnow()
        if period == 'today':
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'week':
            start_date = now - timedelta(days=7)
        elif period == 'month':
            start_date = now - timedelta(days=30)
        else:
            return error_response("Invalid period. Use: today, week, or month", 400)
        
        # Database queries
        db = SessionLocal()
        try:
            # === KPIs ===
            # Base query for KPIs
            kpi_base_query = db.query(PrintJob).filter(
                PrintJob.shop_id == shop_id,
                PrintJob.created_at >= start_date
            )
            
            # Count queries
            total_jobs = kpi_base_query.count()
            pending_jobs = kpi_base_query.filter(PrintJob.status.ilike('pending')).count()
            printing_jobs = kpi_base_query.filter(PrintJob.status.ilike('%printing%')).count()
            completed_jobs = kpi_base_query.filter(PrintJob.status.ilike('completed')).count()
            failed_jobs = kpi_base_query.filter(PrintJob.status.ilike('failed')).count()
            
            # Revenue (sum of amount for completed jobs)
            total_revenue = db.query(func.sum(PrintJob.amount)).filter(
                PrintJob.shop_id == shop_id,
                PrintJob.status.ilike('completed'),
                PrintJob.created_at >= start_date
            ).scalar() or 0.0
            
            # Total pages printed
            total_pages_printed = db.query(func.sum(PrintJob.total_pages)).filter(
                PrintJob.shop_id == shop_id,
                PrintJob.status.ilike('completed'),
                PrintJob.created_at >= start_date
            ).scalar() or 0
            
            kpis = {
                "total_jobs": total_jobs,
                "pending_jobs": pending_jobs,
                "printing_jobs": printing_jobs,
                "completed_jobs": completed_jobs,
                "failed_jobs": failed_jobs,
                "total_revenue": float(total_revenue),
                "total_pages_printed": int(total_pages_printed),
                "period": period,
                "last_updated": now.isoformat()
            }
            
            # === Job List ===
            # Base query for jobs (all time, not filtered by period)
            job_query = db.query(PrintJob).filter(PrintJob.shop_id == shop_id)
            
            # Filter by status if provided
            if status_filter:
                job_query = job_query.filter(PrintJob.status == status_filter)
            
            # Sort by created_at descending (newest first)
            job_query = job_query.order_by(PrintJob.created_at.desc())
            
            # Total count
            total_count = job_query.count()
            
            # Pagination
            jobs = job_query.limit(limit).offset(offset).all()
            
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
                    "copies": job.copies,
                    "page_range": job.page_range,
                    "page_size": job.page_size,
                    "orientation": job.orientation,
                    "print_side": job.print_side,
                    "color_mode": job.color_mode,
                    "layout_pages": job.layout_pages,
                    "amount": float(job.amount) if job.amount else 0.0,
                    "created_at": job.created_at.isoformat() if job.created_at else None,
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                    "customer_name": getattr(job, 'customer_name', None), # Might be added via migration if not in base model
                    "customer_phone": getattr(job, 'customer_phone', None)
                })
            
            response_data = {
                "kpis": kpis,
                "jobs": jobs_data,
                "total_count": total_count,
                "limit": limit,
                "offset": offset
            }
            
            logger.info(f"Dashboard data fetched for shop_id: {shop_id} (period: {period}, jobs: {len(jobs_data)})")
            return success_response(response_data, "Dashboard data fetched successfully", 200)
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Dashboard fetch error: {str(e)}", exc_info=True)
        return error_response(f"Failed to fetch dashboard data: {str(e)}", 500)
