"""Office document conversion helpers for customer previews."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


SUPPORTED_OFFICE_EXTENSIONS = {"doc", "docx"}
MAX_OFFICE_PREVIEW_BYTES = 25 * 1024 * 1024


class DocumentConversionError(RuntimeError):
    """Raised when LibreOffice cannot produce a preview PDF."""


def convert_office_bytes_to_pdf(data: bytes, filename: str, timeout: int = 45) -> bytes:
    """Convert a Word document to PDF using headless LibreOffice."""
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in SUPPORTED_OFFICE_EXTENSIONS:
        raise DocumentConversionError("Only DOC and DOCX previews are supported")
    if len(data) > MAX_OFFICE_PREVIEW_BYTES:
        raise DocumentConversionError("Document is too large to preview")

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise DocumentConversionError("LibreOffice is not installed in the API container")

    with tempfile.TemporaryDirectory(prefix="ezprint-preview-") as tmp:
        tmpdir = Path(tmp)
        input_path = tmpdir / f"input.{ext}"
        input_path.write_bytes(data)
        profile_dir = tmpdir / "lo-profile"
        output_dir = tmpdir / "out"
        output_dir.mkdir()

        cmd = [
            soffice,
            "--headless",
            "--nologo",
            "--nodefault",
            "--nofirststartwizard",
            "--nolockcheck",
            f"-env:UserInstallation=file://{profile_dir}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(input_path),
        ]
        try:
            completed = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise DocumentConversionError("Document preview conversion timed out") from exc

        pdf_path = output_dir / "input.pdf"
        if completed.returncode != 0 or not pdf_path.exists():
            details = (completed.stderr or completed.stdout or "").strip()
            raise DocumentConversionError(
                "LibreOffice failed to convert document"
                + (f": {details[:300]}" if details else "")
            )

        return pdf_path.read_bytes()
