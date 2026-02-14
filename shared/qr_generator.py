"""
QR Code generation utilities
"""
import qrcode
from PIL import Image
import os
from shared.config import BASE_DIR, QR_CODE_SIZE, QR_CODE_BORDER, EZPRINT_BASE_URL

def generate_qr_code(shop_id, shop_name):
    """
    Generate QR code for shop upload page
    
    Args:
        shop_id (str): Unique shop identifier
        shop_name (str): Name of the shop
    
    Returns:
        str: Path to the generated QR code image
    """
    # Create upload URL
    upload_url = f"{EZPRINT_BASE_URL}/upload/{shop_id}"
    
    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=QR_CODE_SIZE,
        border=QR_CODE_BORDER,
    )
    
    qr.add_data(upload_url)
    qr.make(fit=True)
    
    # Create QR code image
    qr_image = qr.make_image(fill_color="black", back_color="white")
    
    # Save QR code
    qr_dir = BASE_DIR / "web_interface" / "static" / "images" / "qr_codes"
    qr_dir.mkdir(exist_ok=True)
    
    qr_filename = f"qr_{shop_id}.png"
    qr_path = qr_dir / qr_filename
    
    qr_image.save(qr_path)
    
    return str(qr_path)

def get_qr_code_url(shop_id):
    """
    Get the URL for accessing a shop's QR code
    
    Args:
        shop_id (str): Shop identifier
    
    Returns:
        str: URL to the QR code image
    """
    return f"/static/images/qr_codes/qr_{shop_id}.png"

def get_upload_url(shop_id):
    """
    Get the upload URL for a shop
    
    Args:
        shop_id (str): Shop identifier
    
    Returns:
        str: Upload URL
    """
    return f"{EZPRINT_BASE_URL}/upload/{shop_id}"
