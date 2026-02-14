import os
from pathlib import Path
from flask import Blueprint

# Resolve template/static paths relative to the web_interface package root
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "templates" / "admin"
STATIC_DIR = BASE_DIR / "static" / "admin"

admin_bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin",
    template_folder=str(TEMPLATE_DIR),
    static_folder=str(STATIC_DIR),
    static_url_path="/admin/static",
)

# Ensure routes are registered
from . import routes  # noqa: E402,F401

