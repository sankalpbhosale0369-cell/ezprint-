"""
Internet Printing Protocol (IPP) and Line Printer Remote (LPR) Printing Implementation
Provides complete IPP and LPR printing support for network printers
"""
import socket
import logging
import time
import threading
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass
from datetime import datetime
import struct
import tempfile
import os

logger = logging.getLogger(__name__)

@dataclass
class IPPJob:
    """IPP print job information"""
    job_id: int
    job_name: str
    job_state: str
    job_uri: str
    job_printer_uri: str
    time_at_creation: int
    time_at_processing: int
    time_at_completed: int

class IPPPrinting:
    """
    Internet Printing Protocol (IPP) printing implementation
    Supports IPP/1.1 and IPP/2.0 for modern network printers
    """
    
    def __init__(self):
        self.ipp_port = 631
        self.ipp_version = "2.0"
        self.timeout = 30
        self.retry_attempts = 3
        
    def print_to_ipp_printer(self, 
                            printer_info: Dict[str, Any], 
                            file_path: str, 
                            file_type: str,
                            settings: Dict[str, Any],
                            job_id: Optional[str] = None) -> Tuple[bool, str]:
        """
        Print to IPP printer
        
        Args:
            printer_info: Printer information dictionary
            file_path: Path to file to print
            file_type: Type of file (pdf, image, text)
            settings: Print settings
            job_id: Optional job ID for tracking
            
        Returns:
            Tuple of (success, message)
        """
        try:
            ip = printer_info.get('ip_address')
            port = printer_info.get('port', self.ipp_port)
            
            if not ip:
                return False, "No IP address provided for IPP printer"
            
            # Convert file to appropriate format
            if file_type.lower() == 'pdf':
                print_data = self._convert_pdf_to_ipp(file_path, settings)
            elif file_type.lower() in ['jpg', 'jpeg', 'png', 'bmp']:
                print_data = self._convert_image_to_ipp(file_path, settings)
            else:
                print_data = self._convert_text_to_ipp(file_path, settings)
            
            if not print_data:
                return False, "Failed to convert file for IPP printing"
            
            # Send IPP print job
            success = self._send_ipp_job(ip, port, print_data, settings, job_id)
            
            if success:
                return True, f"Successfully printed via IPP to {printer_info.get('name', ip)}"
            else:
                return False, f"Failed to send IPP job to {printer_info.get('name', ip)}"
                
        except Exception as e:
            logger.error(f"IPP printing failed: {e}")
            return False, f"IPP printing failed: {str(e)}"
    
    def _send_ipp_job(self, ip: str, port: int, data: bytes, settings: Dict[str, Any], job_id: Optional[str]) -> bool:
        """Send IPP print job to printer"""
        try:
            # Create IPP request
            ipp_request = self._create_ipp_request(data, settings, job_id)
            
            # Send request to printer
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect((ip, port))
                
                # Send HTTP POST request with IPP data
                http_request = self._create_http_request(ip, port, len(ipp_request))
                sock.sendall(http_request.encode())
                sock.sendall(ipp_request)
                
                # Read response
                response = sock.recv(4096)
                
                # Parse IPP response
                success = self._parse_ipp_response(response)
                
                return success
                
        except Exception as e:
            logger.error(f"Failed to send IPP job to {ip}:{port}: {e}")
            return False
    
    def _create_ipp_request(self, data: bytes, settings: Dict[str, Any], job_id: Optional[str]) -> bytes:
        """Create IPP print job request"""
        # IPP request structure
        request = bytearray()
        
        # IPP version (2.0)
        request.extend(struct.pack('>BB', 2, 0))
        
        # Operation ID (Print-Job = 0x0002)
        request.extend(struct.pack('>H', 0x0002))
        
        # Request ID
        request_id = int(time.time()) & 0xFFFFFFFF
        request.extend(struct.pack('>I', request_id))
        
        # Operation attributes
        # Printer URI
        printer_uri = f"ipp://printer/ipp/print"
        request.extend(self._encode_string_attribute(0x45, "printer-uri", printer_uri))
        
        # Job name
        job_name = job_id or f"Print Job {int(time.time())}"
        request.extend(self._encode_string_attribute(0x42, "job-name", job_name))
        
        # Document format
        document_format = "application/pdf"  # Default to PDF
        request.extend(self._encode_string_attribute(0x49, "document-format", document_format))
        
        # Copies
        copies = settings.get('copies', 1)
        request.extend(self._encode_integer_attribute(0x21, "copies", copies))
        
        # Orientation
        orientation = settings.get('orientation', 'Portrait')
        if orientation == 'Landscape':
            request.extend(self._encode_string_attribute(0x23, "orientation-requested", "landscape"))
        else:
            request.extend(self._encode_string_attribute(0x23, "orientation-requested", "portrait"))
        
        # Color mode
        color_mode = settings.get('color_mode', 'Color')
        if color_mode == 'Black & White':
            request.extend(self._encode_string_attribute(0x23, "print-color-mode", "monochrome"))
        else:
            request.extend(self._encode_string_attribute(0x23, "print-color-mode", "color"))
        
        # End of attributes
        request.append(0x03)
        
        # Document data
        request.extend(data)
        
        return bytes(request)
    
    def _create_http_request(self, ip: str, port: int, content_length: int) -> str:
        """Create HTTP POST request for IPP"""
        return f"""POST /ipp/print HTTP/1.1\r
Host: {ip}:{port}\r
Content-Type: application/ipp\r
Content-Length: {content_length}\r
\r
"""
    
    def _encode_string_attribute(self, tag: int, name: str, value: str) -> bytes:
        """Encode string attribute for IPP request"""
        name_bytes = name.encode('utf-8')
        value_bytes = value.encode('utf-8')
        
        # Attribute tag
        result = bytearray([tag])
        
        # Name length and name
        result.extend(struct.pack('>H', len(name_bytes)))
        result.extend(name_bytes)
        
        # Value length and value
        result.extend(struct.pack('>H', len(value_bytes)))
        result.extend(value_bytes)
        
        return bytes(result)
    
    def _encode_integer_attribute(self, tag: int, name: str, value: int) -> bytes:
        """Encode integer attribute for IPP request"""
        name_bytes = name.encode('utf-8')
        
        # Attribute tag
        result = bytearray([tag])
        
        # Name length and name
        result.extend(struct.pack('>H', len(name_bytes)))
        result.extend(name_bytes)
        
        # Value length (4 bytes for integer)
        result.extend(struct.pack('>H', 4))
        
        # Value (4-byte integer)
        result.extend(struct.pack('>I', value))
        
        return bytes(result)
    
    def _parse_ipp_response(self, response: bytes) -> bool:
        """Parse IPP response to check for success"""
        try:
            if len(response) < 8:
                return False
            
            # Parse IPP response header
            version_major, version_minor = struct.unpack('>BB', response[0:2])
            status_code = struct.unpack('>H', response[2:4])[0]
            request_id = struct.unpack('>I', response[4:8])[0]
            
            # Check status code (0x0000 = successful)
            return status_code == 0x0000
            
        except Exception as e:
            logger.error(f"Error parsing IPP response: {e}")
            return False
    
    def _convert_pdf_to_ipp(self, file_path: str, settings: Dict[str, Any]) -> bytes:
        """Convert PDF to IPP-compatible format"""
        try:
            # For IPP, we can send PDF directly as most modern printers support PDF
            with open(file_path, 'rb') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error converting PDF to IPP: {e}")
            return b""
    
    def _convert_image_to_ipp(self, file_path: str, settings: Dict[str, Any]) -> bytes:
        """Convert image to IPP-compatible format"""
        try:
            # For IPP, we can send JPEG directly as most printers support it
            with open(file_path, 'rb') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error converting image to IPP: {e}")
            return b""
    
    def _convert_text_to_ipp(self, file_path: str, settings: Dict[str, Any]) -> bytes:
        """Convert text to IPP-compatible format"""
        try:
            # For IPP, we can send plain text directly
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
            return text.encode('utf-8')
        except Exception as e:
            logger.error(f"Error converting text to IPP: {e}")
            return b""

class LPRPrinting:
    """
    Line Printer Remote (LPR) printing implementation
    Supports LPR/LPD protocol for legacy network printers
    """
    
    def __init__(self):
        self.lpr_port = 515
        self.timeout = 30
        self.retry_attempts = 3
        
    def print_to_lpr_printer(self, 
                            printer_info: Dict[str, Any], 
                            file_path: str, 
                            file_type: str,
                            settings: Dict[str, Any],
                            job_id: Optional[str] = None) -> Tuple[bool, str]:
        """
        Print to LPR printer
        
        Args:
            printer_info: Printer information dictionary
            file_path: Path to file to print
            file_type: Type of file (pdf, image, text)
            settings: Print settings
            job_id: Optional job ID for tracking
            
        Returns:
            Tuple of (success, message)
        """
        try:
            ip = printer_info.get('ip_address')
            port = printer_info.get('port', self.lpr_port)
            
            if not ip:
                return False, "No IP address provided for LPR printer"
            
            # Convert file to appropriate format
            if file_type.lower() == 'pdf':
                print_data = self._convert_pdf_to_lpr(file_path, settings)
            elif file_type.lower() in ['jpg', 'jpeg', 'png', 'bmp']:
                print_data = self._convert_image_to_lpr(file_path, settings)
            else:
                print_data = self._convert_text_to_lpr(file_path, settings)
            
            if not print_data:
                return False, "Failed to convert file for LPR printing"
            
            # Send LPR print job
            success = self._send_lpr_job(ip, port, print_data, settings, job_id)
            
            if success:
                return True, f"Successfully printed via LPR to {printer_info.get('name', ip)}"
            else:
                return False, f"Failed to send LPR job to {printer_info.get('name', ip)}"
                
        except Exception as e:
            logger.error(f"LPR printing failed: {e}")
            return False, f"LPR printing failed: {str(e)}"
    
    def _send_lpr_job(self, ip: str, port: int, data: bytes, settings: Dict[str, Any], job_id: Optional[str]) -> bool:
        """Send LPR print job to printer"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect((ip, port))
                
                # Send LPR commands
                job_name = job_id or f"PrintJob{int(time.time())}"
                user = "user"  # Default user
                queue = "lp"   # Default queue
                
                # Send job command
                job_cmd = f"\x02{queue}\n"
                sock.send(job_cmd.encode())
                
                # Send control file
                control_data = self._create_lpr_control_file(job_name, user, len(data))
                control_cmd = f"\x02{len(control_data)} cfA{job_name}\n"
                sock.send(control_cmd.encode())
                sock.send(control_data)
                
                # Send data file
                data_cmd = f"\x03{len(data)} dfA{job_name}\n"
                sock.send(data_cmd.encode())
                sock.send(data)
                
                return True
                
        except Exception as e:
            logger.error(f"Failed to send LPR job to {ip}:{port}: {e}")
            return False
    
    def _create_lpr_control_file(self, job_name: str, user: str, data_size: int) -> bytes:
        """Create LPR control file"""
        control_lines = [
            f"H{user}",  # Host name
            f"P{user}",  # User name
            f"J{job_name}",  # Job name
            f"C{user}",  # Class for banner page
            f"L{user}",  # Print banner page
            f"U{data_size} dfA{job_name}",  # Unlink data file
            f"N{job_name}",  # Name of source file
        ]
        
        return "\n".join(control_lines).encode('utf-8')
    
    def _convert_pdf_to_lpr(self, file_path: str, settings: Dict[str, Any]) -> bytes:
        """Convert PDF to LPR-compatible format"""
        try:
            # For LPR, we need to convert PDF to PostScript
            # Use Ghostscript if available
            try:
                import subprocess
                import tempfile
                
                ps_file = tempfile.NamedTemporaryFile(suffix='.ps', delete=False)
                ps_file.close()
                
                from shared import config as cfg
                gs_exe = cfg.GHOSTSCRIPT_EXE
                if not gs_exe:
                    raise ImportError("Ghostscript executable not configured")
                gs_cmd = [
                    gs_exe,
                    '-dNOPAUSE',
                    '-dBATCH',
                    '-dSAFER',
                    '-sDEVICE=ps2write',
                    f'-sOutputFile={ps_file.name}',
                    file_path
                ]
                
                result = subprocess.run(gs_cmd, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    with open(ps_file.name, 'rb') as f:
                        data = f.read()
                    os.unlink(ps_file.name)
                    return data
                else:
                    raise Exception(f"Ghostscript failed: {result.stderr}")
                    
            except ImportError:
                # Fallback: send PDF as-is (some printers support PDF)
                with open(file_path, 'rb') as f:
                    return f.read()
                    
        except Exception as e:
            logger.error(f"Error converting PDF to LPR: {e}")
            return b""
    
    def _convert_image_to_lpr(self, file_path: str, settings: Dict[str, Any]) -> bytes:
        """Convert image to LPR-compatible format"""
        try:
            # For LPR, convert image to PostScript
            from PIL import Image
            import io
            
            img = Image.open(file_path)
            
            # Convert to PostScript
            ps_data = self._image_to_postscript(img)
            return ps_data
            
        except Exception as e:
            logger.error(f"Error converting image to LPR: {e}")
            return b""
    
    def _convert_text_to_lpr(self, file_path: str, settings: Dict[str, Any]) -> bytes:
        """Convert text to LPR-compatible format"""
        try:
            # For LPR, send text as-is
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
            return text.encode('utf-8')
        except Exception as e:
            logger.error(f"Error converting text to LPR: {e}")
            return b""
    
    def _image_to_postscript(self, img) -> bytes:
        """Convert PIL image to PostScript"""
        try:
            # Convert image to PostScript
            width, height = img.size
            
            ps_header = f"""%!PS-Adobe-3.0
%%Creator: EzPrint
%%Title: Image Print
%%Pages: 1
%%EndComments
%%Page: 1 1
gsave
{width} {height} scale
{width} {height} 8 [1 0 0 -1 0 {height}] currentfile /ASCIIHexDecode filter /DCTDecode filter false 3 colorimage
"""
            
            # Convert image to JPEG data
            img_bytes = io.BytesIO()
            img.save(img_bytes, format='JPEG')
            jpeg_data = img_bytes.getvalue()
            
            # Convert to ASCII hex
            hex_data = jpeg_data.hex().upper()
            
            ps_footer = """
grestore
showpage
%%EOF
"""
            
            return (ps_header + hex_data + ps_footer).encode('utf-8')
            
        except Exception as e:
            logger.error(f"Error converting image to PostScript: {e}")
            return b""
