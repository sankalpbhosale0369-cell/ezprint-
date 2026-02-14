import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
)
from sqlalchemy import func, case

from shared.database import SessionLocal, Shopkeeper, PrintJob, ShopPricing, Printer
from . import admin_bp

# Admin credentials (env-driven; defaults for dev only)
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")


def require_admin():
    """Simple session-based admin guard."""
    if not session.get("admin_user"):
        return False
    return True


def get_db_session():
    """Per-request session helper."""
    return SessionLocal()


@admin_bp.before_app_request
def _set_session_permanent():
    # Keep admin session alive for a reasonable time
    session.permanent = True
    # 8 hours lifetime
    admin_bp.permanent_session_lifetime = timedelta(hours=8)


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin_user"] = username
            return redirect(url_for("admin.dashboard"))
        flash("Invalid credentials", "error")
    return render_template("admin/login.html")


@admin_bp.route("/logout")
def logout():
    session.pop("admin_user", None)
    return redirect(url_for("admin.login"))


@admin_bp.route("/")
def dashboard():
    if not require_admin():
        return redirect(url_for("admin.login"))

    db = get_db_session()
    try:
        metrics = build_metrics(db)
        charts = build_charts(db)
    finally:
        db.close()

    return render_template(
        "admin/dashboard.html",
        metrics=metrics,
        charts=charts,
        admin_user=session.get("admin_user"),
    )


@admin_bp.route("/api/metrics")
def metrics_api():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401

    db = get_db_session()
    try:
        metrics = build_metrics(db)
        charts = build_charts(db)
    finally:
        db.close()

    return jsonify({"metrics": metrics, "charts": charts})


def build_metrics(db) -> Dict[str, Any]:
    """Aggregate KPI metrics for the dashboard."""
    total_shops = db.query(func.count(Shopkeeper.id)).scalar() or 0
    active_shops = (
        db.query(func.count(Shopkeeper.id))
        .filter(Shopkeeper.is_active.is_(True))
        .scalar()
        or 0
    )
    inactive_shops = max(total_shops - active_shops, 0)

    # Shops with custom pricing vs default pricing (no assumptions about "paid" plans)
    custom_pricing_shops = (
        db.query(func.count(func.distinct(ShopPricing.shop_id))).scalar() or 0
    )
    default_pricing_shops = max(total_shops - custom_pricing_shops, 0)

    total_jobs = db.query(func.count(PrintJob.id)).scalar() or 0
    total_revenue = (
        db.query(func.coalesce(func.sum(PrintJob.amount), 0))
        .filter(PrintJob.status == 'Completed')
        .scalar() or 0.0
    )

    # Jobs by status distribution
    status_rows = (
        db.query(PrintJob.status, func.count(PrintJob.id))
        .group_by(PrintJob.status)
        .all()
    )
    jobs_by_status = {row[0] or "Unknown": row[1] for row in status_rows}

    return {
        "total_shops": total_shops,
        "active_shops": active_shops,
        "inactive_shops": inactive_shops,
        "total_jobs": total_jobs,
        "total_revenue": round(float(total_revenue), 2),
        "jobs_by_status": jobs_by_status,
        "pricing_split": {
            "custom_pricing": custom_pricing_shops,
            "default_pricing": default_pricing_shops,
        },
    }


def build_charts(db) -> Dict[str, Any]:
    """Prepare chart datasets for daily/monthly trends and plan split."""
    daily = (
        db.query(
            func.strftime("%Y-%m-%d", PrintJob.created_at).label("day"),
            func.count(PrintJob.id).label("jobs"),
            func.coalesce(func.sum(PrintJob.amount), 0).label("revenue"),
        )
        .filter(PrintJob.status == 'Completed')
        .group_by("day")
        .order_by("day")
        .limit(30)
        .all()
    )

    monthly = (
        db.query(
            func.strftime("%Y-%m", PrintJob.created_at).label("month"),
            func.count(PrintJob.id).label("jobs"),
            func.coalesce(func.sum(PrintJob.amount), 0).label("revenue"),
        )
        .filter(PrintJob.status == 'Completed')
        .group_by("month")
        .order_by("month")
        .limit(12)
        .all()
    )

    # Custom vs default pricing split (schema-backed only)
    pricing_split_row = db.query(
        func.count(func.distinct(ShopPricing.shop_id)).label("custom"),
        func.count(Shopkeeper.id).label("total"),
    ).first()
    custom_pricing = pricing_split_row.custom if pricing_split_row else 0
    total_shops = pricing_split_row.total if pricing_split_row else 0
    default_pricing = max(total_shops - custom_pricing, 0)

    # Status distribution for charting
    status_rows = (
        db.query(PrintJob.status, func.count(PrintJob.id))
        .group_by(PrintJob.status)
        .all()
    )
    status_labels = [row[0] or "Unknown" for row in status_rows]
    status_counts = [row[1] for row in status_rows]

    return {
        "daily": {
            "labels": [row.day for row in daily],
            "jobs": [row.jobs for row in daily],
            "revenue": [round(float(row.revenue), 2) for row in daily],
        },
        "monthly": {
            "labels": [row.month for row in monthly],
            "jobs": [row.jobs for row in monthly],
            "revenue": [round(float(row.revenue), 2) for row in monthly],
        },
        "status_distribution": {
            "labels": status_labels,
            "counts": status_counts,
        },
        "pricing_split": {
            "custom_pricing": custom_pricing,
            "default_pricing": default_pricing,
        },
    }


@admin_bp.route("/shops")
def shops():
    if not require_admin():
        return redirect(url_for("admin.login"))
    db = get_db_session()
    try:
        shops = db.query(Shopkeeper).order_by(Shopkeeper.created_at.desc()).all()

        # Aggregate jobs and revenue per shop
        # job_count: all jobs, revenue: only completed jobs
        job_stats_rows = (
            db.query(
                PrintJob.shop_id,
                func.count(PrintJob.id).label("job_count"),
                func.coalesce(
                    func.sum(
                        case(
                            (PrintJob.status == 'Completed', PrintJob.amount),
                            else_=0
                        )
                    ), 0
                ).label("revenue"),
            )
            .group_by(PrintJob.shop_id)
            .all()
        )
        job_stats = {
            row.shop_id: {"job_count": row.job_count, "revenue": float(row.revenue)}
            for row in job_stats_rows
        }

        # Printers per shop
        printer_rows = (
            db.query(Printer.shop_id, func.count(Printer.id).label("printer_count"))
            .group_by(Printer.shop_id)
            .all()
        )
        printer_counts = {row.shop_id: row.printer_count for row in printer_rows}

    finally:
        db.close()

    return render_template(
        "admin/shops.html",
        shops=shops,
        job_stats=job_stats,
        printer_counts=printer_counts,
        admin_user=session.get("admin_user"),
    )


@admin_bp.route("/shopkeepers")
def shopkeepers():
    if not require_admin():
        return redirect(url_for("admin.login"))
    db = get_db_session()
    try:
        keepers = db.query(Shopkeeper).order_by(Shopkeeper.created_at.desc()).all()
    finally:
        db.close()

    return render_template(
        "admin/shopkeepers.html",
        shopkeepers=keepers,
        admin_user=session.get("admin_user"),
    )


@admin_bp.route("/subscriptions")
def subscriptions():
    if not require_admin():
        return redirect(url_for("admin.login"))
    # Phase 1 does not expose subscription concepts; reuse shops/pricing views instead.
    return redirect(url_for("admin.shops"))


@admin_bp.route("/print-jobs")
def jobs():
    if not require_admin():
        return redirect(url_for("admin.login"))

    # Filters: status, shop_id, date_from, date_to
    status = request.args.get("status") or None
    shop_id = request.args.get("shop_id") or None
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None

    db = get_db_session()
    try:
        query = db.query(PrintJob, Shopkeeper.shop_name).join(
            Shopkeeper, PrintJob.shop_id == Shopkeeper.shop_id
        )

        if status:
            query = query.filter(PrintJob.status == status)
        if shop_id:
            query = query.filter(PrintJob.shop_id == shop_id)
        if date_from:
            try:
                dt_from = datetime.fromisoformat(date_from)
                query = query.filter(PrintJob.created_at >= dt_from)
            except ValueError:
                pass
        if date_to:
            try:
                dt_to = datetime.fromisoformat(date_to)
                query = query.filter(PrintJob.created_at <= dt_to)
            except ValueError:
                pass

        jobs = (
            query.order_by(PrintJob.created_at.desc())
            .limit(200)
            .all()
        )

        # For filter dropdowns
        all_shops = db.query(Shopkeeper).order_by(Shopkeeper.shop_name).all()
        statuses = (
            db.query(PrintJob.status)
            .distinct()
            .order_by(PrintJob.status.asc())
            .all()
        )

    finally:
        db.close()

    return render_template(
        "admin/print_jobs.html",
        jobs=jobs,
        all_shops=all_shops,
        statuses=[s[0] for s in statuses if s[0]],
        active_filters={
            "status": status or "",
            "shop_id": shop_id or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
        },
        admin_user=session.get("admin_user"),
    )


@admin_bp.route("/revenue")
def revenue():
    if not require_admin():
        return redirect(url_for("admin.login"))
    db = get_db_session()
    try:
        # Total expected revenue (only from completed jobs)
        total_revenue = (
            db.query(func.coalesce(func.sum(PrintJob.amount), 0))
            .filter(PrintJob.status == 'Completed')
            .scalar() or 0.0
        )

        # Revenue per shop (only from completed jobs)
        per_shop_rows = (
            db.query(
                Shopkeeper.shop_name,
                Shopkeeper.shop_id,
                func.coalesce(func.sum(PrintJob.amount), 0).label("revenue"),
            )
            .join(PrintJob, PrintJob.shop_id == Shopkeeper.shop_id)
            .filter(PrintJob.status == 'Completed')
            .group_by(Shopkeeper.shop_id)
            .order_by(func.sum(PrintJob.amount).desc())
            .all()
        )

        # Daily and monthly revenue reuse build_charts
        charts = build_charts(db)

    finally:
        db.close()

    return render_template(
        "admin/revenue.html",
        total_revenue=float(total_revenue),
        per_shop=per_shop_rows,
        charts=charts,
        admin_user=session.get("admin_user"),
    )


@admin_bp.route("/analytics")
def analytics():
    if not require_admin():
        return redirect(url_for("admin.login"))
    # Phase 1 keeps analytics limited to dashboard and revenue views.
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/feedback")
def feedback():
    if not require_admin():
        return redirect(url_for("admin.login"))
    # No feedback schema in Phase 1; route kept but redirected.
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/ads")
def ads():
    if not require_admin():
        return redirect(url_for("admin.login"))
    # Ads are not modeled in DB; keep route but redirect.
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/settings")
def settings():
    if not require_admin():
        return redirect(url_for("admin.login"))
    # Basic settings page can point admins to environment configuration.
    return render_template(
        "admin/settings.html",
        admin_user=session.get("admin_user"),
    )


@admin_bp.route("/shops/<shop_id>/block", methods=["POST"])
def block_shop(shop_id: str):
    if not require_admin():
        return redirect(url_for("admin.login"))

    db = get_db_session()
    try:
        shop = (
            db.query(Shopkeeper)
            .filter(Shopkeeper.shop_id == shop_id)
            .first()
        )
        if shop:
            shop.is_active = False
            db.commit()
            flash(f"Shop '{shop.shop_name}' blocked.", "success")
    finally:
        db.close()

    return redirect(url_for("admin.shops"))


@admin_bp.route("/shops/<shop_id>/unblock", methods=["POST"])
def unblock_shop(shop_id: str):
    if not require_admin():
        return redirect(url_for("admin.login"))

    db = get_db_session()
    try:
        shop = (
            db.query(Shopkeeper)
            .filter(Shopkeeper.shop_id == shop_id)
            .first()
        )
        if shop:
            shop.is_active = True
            db.commit()
            flash(f"Shop '{shop.shop_name}' unblocked.", "success")
    finally:
        db.close()

    return redirect(url_for("admin.shops"))


@admin_bp.route("/shopkeepers/<int:keeper_id>/block", methods=["POST"])
def block_shopkeeper(keeper_id: int):
    if not require_admin():
        return redirect(url_for("admin.login"))

    db = get_db_session()
    try:
        keeper = db.query(Shopkeeper).filter(Shopkeeper.id == keeper_id).first()
        if keeper:
            keeper.is_active = False
            db.commit()
            flash(f"Shopkeeper '{keeper.username}' blocked.", "success")
    finally:
        db.close()

    return redirect(url_for("admin.shopkeepers"))


@admin_bp.route("/shopkeepers/<int:keeper_id>/unblock", methods=["POST"])
def unblock_shopkeeper(keeper_id: int):
    if not require_admin():
        return redirect(url_for("admin.login"))

    db = get_db_session()
    try:
        keeper = db.query(Shopkeeper).filter(Shopkeeper.id == keeper_id).first()
        if keeper:
            keeper.is_active = True
            db.commit()
            flash(f"Shopkeeper '{keeper.username}' unblocked.", "success")
    finally:
        db.close()

    return redirect(url_for("admin.shopkeepers"))


@admin_bp.route("/printers")
def printers():
    if not require_admin():
        return redirect(url_for("admin.login"))

    db = get_db_session()
    try:
        rows = (
            db.query(
                Printer,
                Shopkeeper.shop_name,
            )
            .join(Shopkeeper, Printer.shop_id == Shopkeeper.shop_id)
            .order_by(Shopkeeper.shop_name.asc(), Printer.printer_name.asc())
            .all()
        )
    finally:
        db.close()

    return render_template(
        "admin/printers.html",
        printers=rows,
        admin_user=session.get("admin_user"),
    )

