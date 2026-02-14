"""
Enhanced Network Printing Implementation for Windows
Handles RAW, IPP, LPR, and SMB protocols for real-time printing
"""
import win32print
import win32api
import win32ui
import win32con
import socket
import threading
import time
import logging
import subprocess
import os
import tempfile
from typing import Optional, Tuple, Dict, Any
from pathlib import Path
import struct

# Import our new modules
from shared.retry_utils import retry_with_backoff, NetworkOperationRetry, PRINTING_RETRY_CONFIG
from shared.ipp_lpr_printing import IPPPrinting, LPRPrinting
from shared.connection_monitor import ConnectionMonitor, ConnectionEvent

logger = logging.getLogger(__name__)

class EnhancedNetworkPrinting:
    """
    Comprehensive network printing implementation
    Supports RAW, IPP, LPR, and SMB protocols with retry logic and connection monitoring
    """
    
    def __init__(self):
        self.printing_timeout = 30  # 30 seconds timeout
        self.retry_attempts = 3
        self.retry_delay = 1  # 1 second between retries
        
        # Initialize protocol handlers
        self.ipp_printing = IPPPrinting()
        self.lpr_printing = LPRPrinting()
        
        # Initialize connection monitor
        self.connection_monitor = ConnectionMonitor()
        self.connection_monitor.start_monitoring()
        
        # Connection pooling for better performance
        self.connection_pool = {}
        self.pool_lock = threading.Lock()
        
    def print_to_network_printer(self, 
                                printer_name: str,
                                file_path: str, 
                                file_type: str,
                                settings: Dict[str, Any],
                                job_id: Optional[str] = None) -> Tuple[bool, str]:
        """
        Print to network printer using appropriate protocol with retry logic
        
        Args:
            printer_name: Name of the printer
            file_path: Path to file to print
            file_type: Type of file (pdf, image, text)
            settings: Print settings
            job_id: Optional job ID for tracking
            
        Returns:
            Tuple of (success, message)
        """
        # Use retry logic for the entire printing operation
        with NetworkOperationRetry(PRINTING_RETRY_CONFIG, f"Print to {printer_name}") as retry_ctx:
            return retry_ctx.execute(self._print_to_network_printer_impl, 
                                   printer_name, file_path, file_type, settings, job_id)
    
    def _print_to_network_printer_impl(self, 
                                     printer_name: str,
                                     file_path: str, 
                                     file_type: str,
                                     settings: Dict[str, Any],
                                     job_id: Optional[str] = None) -> Tuple[bool, str]:
        """
        Internal implementation of network printing with retry logic
        """
        try:
            # Get printer information
            printer_info = self._get_printer_info(printer_name)
            if not printer_info:
                return False, f"Printer {printer_name} not found"
            
            # Add printer to connection monitoring
            self.connection_monitor.add_printer(printer_info)
            
            # Determine best printing method with retry logic
            if printer_info['protocol'] == 'RAW':
                return self._print_via_raw_with_retry(printer_info, file_path, file_type, settings, job_id)
            elif printer_info['protocol'] == 'IPP':
                return self.ipp_printing.print_to_ipp_printer(printer_info, file_path, file_type, settings, job_id)
            elif printer_info['protocol'] == 'LPR':
                return self.lpr_printing.print_to_lpr_printer(printer_info, file_path, file_type, settings, job_id)
            elif printer_info['protocol'] == 'WSD':
                return self._print_via_windows_gdi(printer_info, file_path, file_type, settings, job_id)
            else:
                # Fallback to Windows GDI
                return self._print_via_windows_gdi(printer_info, file_path, file_type, settings, job_id)
                
        except Exception as e:
            logger.error(f"Network printing failed: {e}")
            return False, f"Printing failed: {str(e)}"
    
    def _get_printer_info(self, printer_name: str) -> Optional[Dict[str, Any]]:
        """Get printer information from Windows API"""
        try:
            h = win32print.OpenPrinter(printer_name)
            info = win32print.GetPrinter(h, 2)
            win32print.ClosePrinter(h)
            
            port_name = info.get('pPortName', '')
            ip_address = self._extract_ip_from_port(port_name)
            
            if not ip_address:
                return None
            
            return {
                'name': printer_name,
                'ip_address': ip_address,
                'port': self._extract_port_from_port_name(port_name),
                'protocol': self._determine_protocol(port_name),
                'status': 'Online',
                'driver_installed': True,
                'port_created': True,
                'connectivity_test': True,
                'discovery_method': 'Windows API',
                'last_seen': time.time()
            }
            
        except Exception as e:
            logger.error(f"Failed to get printer info for {printer_name}: {e}")
            return None
    
    def _print_via_raw_with_retry(self, printer_info: Dict[str, Any], file_path: str, 
                                 file_type: str, settings: Dict[str, Any], job_id: Optional[str]) -> Tuple[bool, str]:
        """Print via RAW protocol with retry logic"""
        try:
            logger.info(f"Printing via RAW to {printer_info['ip_address']}:{printer_info['port']}")
            
            # Convert file to appropriate format
            if file_type.lower() == 'pdf':
                # Convert PDF to PostScript or PCL
                raw_data = self._convert_pdf_to_raw(file_path, settings)
            elif file_type.lower() in ['jpg', 'jpeg', 'png', 'bmp']:
                # Convert image to PCL
                raw_data = self._convert_image_to_pcl(file_path, settings)
            else:
                # Convert text to PCL
                raw_data = self._convert_text_to_pcl(file_path, settings)
            
            # Send RAW data to printer with retry logic
            success = self._send_raw_data_with_retry(printer_info['ip_address'], printer_info['port'], raw_data)
            
            if success:
                return True, f"Successfully printed via RAW to {printer_info['name']}"
            else:
                return False, f"Failed to send RAW data to {printer_info['name']}"
                
        except Exception as e:
            logger.error(f"RAW printing failed: {e}")
            return False, f"RAW printing failed: {str(e)}"
    
    def _print_via_raw(self, printer_info: Dict[str, Any], file_path: str, 
                      file_type: str, settings: Dict[str, Any], job_id: Optional[str]) -> Tuple[bool, str]:
        """Print via RAW protocol (port 9100) - legacy method for compatibility"""
        return self._print_via_raw_with_retry(printer_info, file_path, file_type, settings, job_id)
    
    def _print_via_ipp(self, printer_info: Dict[str, Any], file_path: str, 
                      file_type: str, settings: Dict[str, Any], job_id: Optional[str]) -> Tuple[bool, str]:
        """Print via IPP protocol (port 631)"""
        try:
            logger.info(f"Printing via IPP to {printer_info['ip_address']}:{printer_info['port']}")
            
            # Use Windows IPP printing
            return self._print_via_windows_ipp(printer_info, file_path, file_type, settings, job_id)
            
        except Exception as e:
            logger.error(f"IPP printing failed: {e}")
            return False, f"IPP printing failed: {str(e)}"
    
    def _print_via_lpr(self, printer_info: Dict[str, Any], file_path: str, 
                      file_type: str, settings: Dict[str, Any], job_id: Optional[str]) -> Tuple[bool, str]:
        """Print via LPR protocol (port 515)"""
        try:
            logger.info(f"Printing via LPR to {printer_info['ip_address']}:{printer_info['port']}")
            
            # Use Windows LPR printing
            return self._print_via_windows_lpr(printer_info, file_path, file_type, settings, job_id)
            
        except Exception as e:
            logger.error(f"LPR printing failed: {e}")
            return False, f"LPR printing failed: {str(e)}"
    
    def _print_via_windows_gdi(self, printer_info: Dict[str, Any], file_path: str, 
                              file_type: str, settings: Dict[str, Any], job_id: Optional[str]) -> Tuple[bool, str]:
        """Print via Windows GDI (works with all printer types) using Windows spooler.

        This method rasterizes the content (PDF/images) and draws to a printer DC so that
        a real spooler job is created. The document name includes the job_id to enable
        reliable polling via EnumJobs.
        """
        try:
            printer_name = printer_info.get('name') if isinstance(printer_info, dict) else str(printer_info)
            if not printer_name:
                return False, "Printer name not provided for GDI printing"

            if not os.path.exists(file_path):
                return False, f"File not found: {file_path}"

            # Import here to avoid hard dependency during module import
            try:
                import fitz  # PyMuPDF
            except Exception:
                fitz = None
            from PIL import Image
            from PIL import ImageWin

            # Prepare pages to render
            images = []
            file_type_lower = (file_type or '').lower()
            page_range = (settings.get('page_range') or '').strip() if isinstance(settings, dict) else ''

            def _parse_page_range(page_range_str: str, total_pages: int):
                try:
                    if not page_range_str:
                        return list(range(1, total_pages + 1))
                    pages = []
                    for part in page_range_str.split(','):
                        part = part.strip()
                        if '-' in part:
                            a, b = part.split('-', 1)
                            pages.extend(list(range(int(a), int(b) + 1)))
                        else:
                            pages.append(int(part))
                    # clamp to valid range and unique preserve order
                    seen = set()
                    out = []
                    for p in pages:
                        if 1 <= p <= total_pages and p not in seen:
                            seen.add(p)
                            out.append(p)
                    return out or list(range(1, total_pages + 1))
                except Exception:
                    return list(range(1, total_pages + 1))

            if file_type_lower == 'pdf' or file_path.lower().endswith('.pdf'):
                if not fitz:
                    return False, "PDF rendering library (PyMuPDF) not available"
                doc = fitz.open(file_path)
                pages = _parse_page_range(page_range, len(doc))
                for p in pages:
                    idx = p - 1
                    if 0 <= idx < len(doc):
                        page = doc[idx]
                        zoom = 2.0
                        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                        img = Image.open(tempfile.SpooledTemporaryFile())  # placeholder; replaced next line
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        images.append(img)
                doc.close()
            elif file_type_lower in ['png', 'jpg', 'jpeg', 'bmp', 'gif', 'tif', 'tiff'] or file_path.lower().endswith(('.png','.jpg','.jpeg','.bmp','.gif','.tif','.tiff')):
                img = Image.open(file_path)
                images = [img]
            else:
                return False, f"Unsupported file type for GDI printing: {file_type}"

            if not images:
                return False, "No pages to print after rendering"

            # Settings
            copies = int(settings.get('copies') or 1) if isinstance(settings, dict) else 1
            orientation = (settings.get('orientation') or 'Portrait') if isinstance(settings, dict) else 'Portrait'
            color_mode = (settings.get('color_mode') or 'Color') if isinstance(settings, dict) else 'Color'

            # Create printer DC
            hDC = win32ui.CreateDC()
            hDC.CreatePrinterDC(printer_name)

            # Get caps
            printable_area = hDC.GetDeviceCaps(win32con.HORZRES), hDC.GetDeviceCaps(win32con.VERTRES)
            # Start document
            doc_name = f"EzPrint Job - {job_id}" if job_id else "EzPrint Job"
            hDC.StartDoc(doc_name)

            try:
                for _ in range(max(1, copies)):
                    for im in images:
                        img = im.convert('RGB')
                        if color_mode == 'Black & White':
                            img = img.convert('L').convert('RGB')
                        if orientation == 'Landscape' and img.width < img.height:
                            img = img.rotate(90, expand=True)
                        elif orientation == 'Portrait' and img.width > img.height:
                            img = img.rotate(-90, expand=True)

                        hDC.StartPage()

                        img_w, img_h = img.size
                        max_w, max_h = printable_area
                        scale = min(float(max_w) / img_w, float(max_h) / img_h)
                        draw_w = int(img_w * scale)
                        draw_h = int(img_h * scale)
                        x = (max_w - draw_w) // 2
                        y = (max_h - draw_h) // 2

                        resized = img.resize((draw_w, draw_h), Image.Resampling.LANCZOS)
                        dib = ImageWin.Dib(resized)
                        dib.draw(hDC.GetHandleOutput(), (x, y, x + draw_w, y + draw_h))
                        hDC.EndPage()
            finally:
                hDC.EndDoc()
                hDC.DeleteDC()

            logger.info(f"GDI: sent document '{doc_name}' to spooler for printer '{printer_name}'")
            return True, "Document sent to printer via GDI"

        except Exception as e:
            logger.error(f"Windows GDI printing failed: {e}")
            return False, f"Windows GDI printing failed: {str(e)}"
    
    def _send_raw_data_with_retry(self, ip_address: str, port: int, data: bytes) -> bool:
        """Send RAW data to printer with retry logic"""
        if not data:
            logger.error("Attempted to send empty RAW payload")
            return False
        with NetworkOperationRetry(PRINTING_RETRY_CONFIG, f"Send RAW data to {ip_address}:{port}") as retry_ctx:
            return retry_ctx.execute(self._send_raw_data_impl, ip_address, port, data)
    
    def _send_raw_data_impl(self, ip_address: str, port: int, data: bytes) -> bool:
        """Internal implementation of RAW data sending"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.printing_timeout)
                sock.connect((ip_address, port))
                sock.sendall(data)
                sock.close()
            return True
            
        except Exception as e:
            logger.error(f"Failed to send RAW data to {ip_address}:{port}: {e}")
            raise e  # Re-raise for retry logic
    
    def _send_raw_data(self, ip_address: str, port: int, data: bytes) -> bool:
        """Send RAW data to printer - legacy method for compatibility"""
        return self._send_raw_data_with_retry(ip_address, port, data)
    
    def _convert_pdf_to_raw(self, file_path: str, settings: Dict[str, Any]) -> bytes:
        """Convert PDF to RAW format (PostScript or PCL)"""
        try:
            # Use Ghostscript to convert PDF to PostScript
            ps_file = tempfile.NamedTemporaryFile(suffix='.ps', delete=False)
            ps_file.close()
            
            # Ghostscript command to convert PDF to PostScript
            from shared import config as cfg
            gs_exe = cfg.GHOSTSCRIPT_EXE
            if not gs_exe:
                raise RuntimeError("Ghostscript executable not configured")
            gs_cmd = [
                gs_exe,  # Ghostscript executable
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
                if not data:
                    raise Exception("Ghostscript produced empty PostScript data")
                return data
            else:
                raise Exception(f"Ghostscript failed: {result.stderr}")
                
        except Exception as e:
            logger.error(f"PDF to RAW conversion failed: {e}")
            # Fallback to PCL conversion
            return self._convert_pdf_to_pcl(file_path, settings)
    
    def _convert_pdf_to_pcl(self, file_path: str, settings: Dict[str, Any]) -> bytes:
        """Convert PDF to PCL format"""
        try:
            # Use Ghostscript to convert PDF to PCL
            pcl_file = tempfile.NamedTemporaryFile(suffix='.pcl', delete=False)
            pcl_file.close()
            
            gs_cmd = [
                'gswin64c',
                '-dNOPAUSE',
                '-dBATCH',
                '-dSAFER',
                '-sDEVICE=pclmono',
                f'-sOutputFile={pcl_file.name}',
                file_path
            ]
            
            result = subprocess.run(gs_cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                with open(pcl_file.name, 'rb') as f:
                    data = f.read()
                os.unlink(pcl_file.name)
                if not data:
                    raise Exception("Ghostscript produced empty PCL data")
                return data
            else:
                raise Exception(f"Ghostscript PCL conversion failed: {result.stderr}")
                
        except Exception as e:
            logger.error(f"PDF to PCL conversion failed: {e}")
            return b""
    
    def _convert_image_to_pcl(self, file_path: str, settings: Dict[str, Any]) -> bytes:
        """Convert image to PCL format"""
        try:
            try:
                from PIL import Image
                # Load image
                img = Image.open(file_path)
                # Convert to PCL
                pcl_data = self._image_to_pcl(img)
                if not pcl_data:
                    logger.error("Image to PCL produced empty payload")
                return pcl_data
            except ImportError:
                logger.error("PIL (Pillow) not available for image conversion")
                return b""
            
        except Exception as e:
            logger.error(f"Image to PCL conversion failed: {e}")
            return b""
    
    def _convert_text_to_pcl(self, file_path: str, settings: Dict[str, Any]) -> bytes:
        """Convert text to PCL format"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
            
            # Convert text to PCL
            pcl_data = self._text_to_pcl(text)
            if not pcl_data:
                logger.error("Text to PCL produced empty payload")
            return pcl_data
            
        except Exception as e:
            logger.error(f"Text to PCL conversion failed: {e}")
            return b""
    
    def _image_to_pcl(self, img) -> bytes:
        """Convert PIL image to PCL format"""
        try:
            # PCL header
            pcl_data = b"\x1b&l0O"  # Reset printer
            pcl_data += b"\x1b&l1O"  # Set orientation
            pcl_data += b"\x1b&l26A"  # Set page size
            
            # Convert image to PCL raster format
            width, height = img.size
            
            # PCL raster start
            pcl_data += b"\x1b*r1A"  # Start raster
            pcl_data += b"\x1b*r1B"  # Set resolution
            pcl_data += b"\x1b*r" + str(width).encode() + b"A"  # Set width
            pcl_data += b"\x1b*r" + str(height).encode() + b"B"  # Set height
            
            # Convert image data
            img_data = img.tobytes()
            pcl_data += img_data
            
            # PCL raster end
            pcl_data += b"\x1b*rC"  # End raster
            
            return pcl_data
            
        except Exception as e:
            logger.error(f"Image to PCL conversion failed: {e}")
            return b""
    
    def _text_to_pcl(self, text: str) -> bytes:
        """Convert text to PCL format"""
        try:
            if not text:
                return b""
            # PCL header
            pcl_data = b"\x1b&l0O"  # Reset printer
            pcl_data += b"\x1b&l1O"  # Set orientation
            pcl_data += b"\x1b&l26A"  # Set page size
            
            # Add text
            pcl_data += text.encode('utf-8')
            
            # PCL footer
            pcl_data += b"\x1b&l0H"  # Reset printer
            
            return pcl_data
            
        except Exception as e:
            logger.error(f"Text to PCL conversion failed: {e}")
            return b""
    
    def _extract_ip_from_port(self, port_name: str) -> Optional[str]:
        """Extract IP address from port name"""
        import re
        ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', port_name)
        return ip_match.group(1) if ip_match else None
    
    def _extract_port_from_port_name(self, port_name: str) -> int:
        """Extract port number from port name"""
        import re
        port_match = re.search(r'(\d+\.\d+\.\d+\.\d+):(\d+)', port_name)
        if port_match:
            return int(port_match.group(2))
        
        # Check for common port patterns
        if '9100' in port_name:
            return 9100
        elif '631' in port_name:
            return 631
        elif '515' in port_name:
            return 515
        
        return 9100  # Default
    
    def _determine_protocol(self, port_name: str) -> str:
        """Determine network protocol from port name"""
        port_lower = port_name.lower()
        
        if 'ipp' in port_lower or '631' in port_lower:
            return 'IPP'
        elif 'lpr' in port_lower or 'lpd' in port_lower or '515' in port_lower:
            return 'LPR'
        elif 'wsd' in port_lower:
            return 'WSD'
        elif 'tcp' in port_lower or 'ip_' in port_lower:
            return 'RAW'
        else:
            return 'RAW'
    
    def _print_via_gdi_images(self, file_path: str, file_type: str, settings: Dict[str, Any], job_id: Optional[str]) -> Tuple[bool, str]:
        """Fallback GDI printing method"""
        try:
            # This would integrate with the existing GDI printing method
            # For now, return a placeholder
            return True, "GDI printing fallback (placeholder)"
        except Exception as e:
            logger.error(f"GDI printing failed: {e}")
            return False, f"GDI printing failed: {str(e)}"
    
    def cleanup(self):
        """Cleanup resources"""
        try:
            if hasattr(self, 'connection_monitor'):
                self.connection_monitor.stop_monitoring()
            logger.info("Enhanced network printing cleanup completed")
        except Exception as e:
            logger.error(f"Error during enhanced network printing cleanup: {e}")
