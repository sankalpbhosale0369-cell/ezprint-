"""
QR Code generation utilities
"""
import hashlib
import os
import sys
from pathlib import Path

import qrcode
from PIL import Image
from shared.config import BASE_DIR, QR_CODE_SIZE, QR_CODE_BORDER, EZPRINT_BASE_URL


def _qr_storage_dir() -> Path:
    """Platform-aware directory for storing generated QR code images."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        data_dir = Path(base) / "EzPrint" / "uploads" / "qr_codes"
    elif sys.platform == "darwin":
        data_dir = Path.home() / "Library" / "Application Support" / "EzPrint" / "qr_codes"
    else:
        xdg = os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
        data_dir = Path(xdg) / "EzPrint" / "qr_codes"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        data_dir = Path(BASE_DIR) / "qr_codes"
        data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _expected_qr_filename(shop_slug: str) -> str:
    """Deterministic filename bound to the current EZPRINT_BASE_URL.

    We stamp a short hash of the full upload URL into the filename so that
    when the agent is pointed at a new backend (e.g. migrating from
    ``ezprints.duckdns.org`` to the Azure host) the cached PNG is no longer
    a cache hit, forcing a regenerate with the correct URL encoded.
    """
    upload_url = f"{EZPRINT_BASE_URL}/shop/{shop_slug}"
    url_hash = hashlib.sha1(upload_url.encode("utf-8")).hexdigest()[:10]
    return f"qr_{shop_slug}_{url_hash}.png"


def expected_qr_path(shop_slug: str) -> str:
    """Return the absolute path the current-URL QR should live at."""
    return str(_qr_storage_dir() / _expected_qr_filename(shop_slug))


def generate_qr_code(shop_slug, shop_name):
    """
    Generate QR code for shop upload page.

    Args:
        shop_slug (str): The tenant slug used in the customer-facing URL
                         (``/shop/{slug}``).  Falls back gracefully if a
                         numeric shop_id is passed instead.
        shop_name (str): Name of the shop (used only for logging / filename).

    Returns:
        str: Path to the generated QR code image.
    """
    # Customer-facing upload page lives at /shop/{slug}
    upload_url = f"{EZPRINT_BASE_URL}/shop/{shop_slug}"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=QR_CODE_SIZE,
        border=QR_CODE_BORDER,
    )

    qr.add_data(upload_url)
    qr.make(fit=True)

    qr_image = qr.make_image(fill_color="black", back_color="white")

    qr_dir = _qr_storage_dir()
    qr_filename = _expected_qr_filename(shop_slug)
    qr_path = qr_dir / qr_filename

    qr_image.save(qr_path)

    # Prune stale PNGs for the same slug that were built against a different
    # base URL so the dashboard never has a chance to pick them up.
    try:
        for old in qr_dir.glob(f"qr_{shop_slug}*.png"):
            if old.name != qr_filename:
                try:
                    old.unlink()
                except Exception:
                    pass
    except Exception:
        pass

    return str(qr_path)


def get_qr_code_url(shop_slug):
    """
    Get the URL for accessing a shop's QR code.

    Args:
        shop_slug (str): Shop slug identifier.

    Returns:
        str: URL to the QR code image.
    """
    return f"/static/images/qr_codes/qr_{shop_slug}.png"


def get_upload_url(shop_slug):
    """
    Get the customer-facing upload URL for a shop.

    Args:
        shop_slug (str): Shop slug identifier.

    Returns:
        str: Upload URL (``/shop/{slug}``).
    """
    return f"{EZPRINT_BASE_URL}/shop/{shop_slug}"
