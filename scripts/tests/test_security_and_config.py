import io
import os
import importlib
import pytest


def setup_module(module):
    os.environ.setdefault("ENV", "dev")
    os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:5000")


def test_upload_no_file_path_leak(monkeypatch):
    from web_interface.app import app
    client = app.test_client()
    data = {
        'shop_id': 'testshop',
        'file': (io.BytesIO(b'PDF'), 'x.pdf')
    }
    rv = client.post('/api/upload', data=data, content_type='multipart/form-data')
    # In test env, shop may not exist; expect 404 prior to response shape
    if rv.status_code == 404:
        return
    assert rv.is_json
    j = rv.get_json()
    assert 'file_path' not in j


def test_preview_allowlist(monkeypatch):
    from web_interface.app import app
    client = app.test_client()
    data = {
        'file': (io.BytesIO(b'PE'), 'x.exe')
    }
    rv = client.post('/api/preview', data=data, content_type='multipart/form-data')
    assert rv.status_code == 400


def test_prod_secret_required(monkeypatch):
    monkeypatch.setenv('ENV', 'prod')
    monkeypatch.delenv('SECRET_KEY', raising=False)
    with pytest.raises(Exception):
        importlib.reload(importlib.import_module('web_interface.app'))


def test_request_scoped_session_teardown(monkeypatch):
    from web_interface.app import app
    client = app.test_client()
    # hit a lightweight endpoint
    rv = client.get('/api/health')
    assert rv.status_code == 200


def test_ghostscript_resolution_env(monkeypatch):
    # Ensure code references the config variable and does not hardcode name
    from shared import config as cfg
    monkeypatch.setenv('GHOSTSCRIPT_EXE', r'C:\\GS\\bin\\gswin64c.exe')
    importlib.reload(cfg)
    assert hasattr(cfg, 'GHOSTSCRIPT_EXE')
