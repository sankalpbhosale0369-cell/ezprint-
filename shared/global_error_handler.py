"""
Global Error Handling System for EzPrint MVP
Provides comprehensive error handling, logging, and user-friendly error dialogs
"""
import sys
import traceback
import logging
import threading
import os
from datetime import datetime
from pathlib import Path
from functools import wraps
from typing import Optional, Callable, Any

# Import UI libraries with fallback
try:
    from PyQt5.QtWidgets import QMessageBox, QApplication
    from PyQt5.QtCore import QTimer
    PYQT5_AVAILABLE = True
except ImportError:
    PYQT5_AVAILABLE = False

try:
    import customtkinter as ctk
    from customtkinter import CTkMessagebox
    CTK_AVAILABLE = True
except (ImportError, AttributeError):
    CTK_AVAILABLE = False

# Setup logging
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
ERROR_LOG_FILE = LOG_DIR / "error.log"

# Configure error logging
error_logger = logging.getLogger("error_handler")
error_logger.setLevel(logging.ERROR)
error_handler = logging.FileHandler(ERROR_LOG_FILE, encoding='utf-8')
error_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
)
error_handler.setFormatter(error_formatter)
error_logger.addHandler(error_handler)

class GlobalErrorHandler:
    """Global error handler for the application"""
    
    def __init__(self):
        self.error_count = 0
        self.max_errors_per_session = 10
        self.error_dialog_shown = False
        self._setup_exception_hook()
    
    def _setup_exception_hook(self):
        """Setup global exception hook for uncaught exceptions"""
        def handle_exception(exc_type, exc_value, exc_traceback):
            # Don't handle KeyboardInterrupt
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            
            # Log the full traceback
            error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self._log_error(error_msg, "UNCAUGHT_EXCEPTION")
            
            # Show user-friendly error dialog
            self._show_error_dialog(
                "An unexpected error occurred.\nPlease restart the software.",
                error_msg
            )
        
        sys.excepthook = handle_exception
    
    def _log_error(self, error_msg: str, context: str = "UNKNOWN"):
        """Log error to file"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"\n{'='*80}\n"
            log_entry += f"ERROR - {timestamp}\n"
            log_entry += f"Context: {context}\n"
            log_entry += f"Thread: {threading.current_thread().name}\n"
            log_entry += f"Error Details:\n{error_msg}\n"
            log_entry += f"{'='*80}\n"
            
            error_logger.error(log_entry)
            self.error_count += 1
            
        except Exception as e:
            # Fallback logging if file logging fails
            print(f"CRITICAL: Failed to log error: {e}")
            print(f"Original error: {error_msg}")
    
    def _show_error_dialog(self, user_message: str, detailed_error: str = ""):
        """Show user-friendly error dialog"""
        try:
            # Prevent multiple error dialogs
            if self.error_dialog_shown:
                return
            
            self.error_dialog_shown = True
            
            # Try PyQt5 first
            if PYQT5_AVAILABLE and QApplication.instance() is not None:
                self._show_pyqt5_error_dialog(user_message, detailed_error)
            # Try CTk as fallback
            elif CTK_AVAILABLE:
                self._show_ctk_error_dialog(user_message, detailed_error)
            else:
                # Fallback to console
                print(f"ERROR: {user_message}")
                if detailed_error:
                    print(f"DETAILS: {detailed_error}")
            
            # Reset flag after a delay
            if PYQT5_AVAILABLE and QApplication.instance() is not None:
                QTimer.singleShot(5000, lambda: setattr(self, 'error_dialog_shown', False))
            else:
                threading.Timer(5.0, lambda: setattr(self, 'error_dialog_shown', False)).start()
                
        except Exception as e:
            print(f"CRITICAL: Failed to show error dialog: {e}")
    
    def _show_pyqt5_error_dialog(self, user_message: str, detailed_error: str):
        """Show PyQt5 error dialog"""
        try:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("Application Error")
            msg.setText("Something went wrong. Please restart the software.")
            msg.setInformativeText(user_message)
            
            if detailed_error:
                msg.setDetailedText(detailed_error)
            
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec_()
        except Exception as e:
            print(f"Failed to show PyQt5 error dialog: {e}")
    
    def _show_ctk_error_dialog(self, user_message: str, detailed_error: str):
        """Show CTk error dialog"""
        try:
            # Create a simple CTk window for error display
            root = ctk.CTk()
            root.withdraw()  # Hide main window
            
            msg = CTkMessagebox(
                title="Application Error",
                message="Something went wrong. Please restart the software.",
                detail_text=user_message,
                icon="error",
                option_1="OK"
            )
            msg.get()
            root.destroy()
        except Exception as e:
            print(f"Failed to show CTk error dialog: {e}")
    
    def handle_ui_error(self, error: Exception, context: str = "UI_ACTION"):
        """Handle errors in UI actions"""
        try:
            error_msg = f"UI Error in {context}: {str(error)}\n{traceback.format_exc()}"
            self._log_error(error_msg, context)
            
            # Show user-friendly message
            self._show_error_dialog(
                "An error occurred while performing this action.\nPlease try again.",
                f"Error in {context}: {str(error)}"
            )
        except Exception as e:
            print(f"Failed to handle UI error: {e}")
    
    def handle_thread_error(self, error: Exception, context: str = "THREAD"):
        """Handle errors in worker threads"""
        try:
            error_msg = f"Thread Error in {context}: {str(error)}\n{traceback.format_exc()}"
            self._log_error(error_msg, context)
            
            # Don't show dialog for thread errors to avoid blocking
            print(f"Thread error in {context}: {str(error)}")
        except Exception as e:
            print(f"Failed to handle thread error: {e}")
    
    def handle_printer_error(self, error: Exception, context: str = "PRINTER"):
        """Handle printer-related errors"""
        try:
            error_msg = f"Printer Error in {context}: {str(error)}\n{traceback.format_exc()}"
            self._log_error(error_msg, context)
            
            self._show_error_dialog(
                "A printer error occurred.\nPlease check your printer connection and try again.",
                f"Printer error: {str(error)}"
            )
        except Exception as e:
            print(f"Failed to handle printer error: {e}")
    
    def handle_database_error(self, error: Exception, context: str = "DATABASE"):
        """Handle database-related errors"""
        try:
            error_msg = f"Database Error in {context}: {str(error)}\n{traceback.format_exc()}"
            self._log_error(error_msg, context)
            
            self._show_error_dialog(
                "A database error occurred.\nPlease restart the software.",
                f"Database error: {str(error)}"
            )
        except Exception as e:
            print(f"Failed to handle database error: {e}")
    
    def is_error_limit_reached(self) -> bool:
        """Check if error limit per session is reached"""
        return self.error_count >= self.max_errors_per_session

# Global error handler instance
global_error_handler = GlobalErrorHandler()

def safe_execute(func: Callable, *args, error_context: str = "UNKNOWN", 
                default_return: Any = None, show_dialog: bool = True, **kwargs) -> Any:
    """
    Safely execute a function with comprehensive error handling
    
    Args:
        func: Function to execute
        *args: Function arguments
        error_context: Context for error logging
        default_return: Value to return on error
        show_dialog: Whether to show error dialog
        **kwargs: Function keyword arguments
    
    Returns:
        Function result or default_return on error
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        error_msg = f"Error in {error_context}: {str(e)}\n{traceback.format_exc()}"
        global_error_handler._log_error(error_msg, error_context)
        
        if show_dialog and not global_error_handler.is_error_limit_reached():
            global_error_handler._show_error_dialog(
                f"An error occurred in {error_context}.\nPlease try again.",
                str(e)
            )
        
        return default_return

def safe_ui_action(error_context: str = "UI_ACTION"):
    """
    Decorator for UI actions with error handling
    
    Args:
        error_context: Context for error logging
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                # Try to call with all arguments first
                return func(*args, **kwargs)
            except TypeError as e:
                if "takes" in str(e) and "argument" in str(e):
                    # If it's an argument mismatch, try calling with just self
                    try:
                        return func(args[0]) if args else func()
                    except Exception:
                        # If that fails too, handle as regular error
                        global_error_handler.handle_ui_error(e, error_context)
                        return None
                elif "unexpected keyword argument" in str(e):
                    # If it's unexpected keyword arguments, try calling with just self
                    try:
                        return func(args[0]) if args else func()
                    except Exception:
                        # If that fails too, handle as regular error
                        global_error_handler.handle_ui_error(e, error_context)
                        return None
                else:
                    # Re-raise if it's not an argument mismatch
                    raise
            except Exception as e:
                global_error_handler.handle_ui_error(e, error_context)
                return None
        return wrapper
    return decorator

def safe_thread_action(error_context: str = "THREAD"):
    """
    Decorator for thread actions with error handling
    
    Args:
        error_context: Context for error logging
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                global_error_handler.handle_thread_error(e, error_context)
                return None
        return wrapper
    return decorator

def safe_printer_action(error_context: str = "PRINTER"):
    """
    Decorator for printer actions with error handling
    
    Args:
        error_context: Context for error logging
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                global_error_handler.handle_printer_error(e, error_context)
                return None
        return wrapper
    return decorator

def safe_database_action(error_context: str = "DATABASE"):
    """
    Decorator for database actions with error handling
    
    Args:
        error_context: Context for error logging
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                global_error_handler.handle_database_error(e, error_context)
                return None
        return wrapper
    return decorator

def wrap_main_application(app_exec_func, *args, **kwargs):
    """
    Wrap main application execution with global error handling
    
    Args:
        app_exec_func: Application exec function (e.g., app.exec_)
        *args: Arguments for the exec function
        **kwargs: Keyword arguments for the exec function
    """
    try:
        return app_exec_func(*args, **kwargs)
    except Exception as e:
        error_msg = f"Main application error: {str(e)}\n{traceback.format_exc()}"
        global_error_handler._log_error(error_msg, "MAIN_APPLICATION")
        global_error_handler._show_error_dialog(
            "The application encountered a critical error.\nPlease restart the software.",
            str(e)
        )
        return 1  # Error exit code

def wrap_thread_function(func, *args, **kwargs):
    """
    Wrap thread function with error handling
    
    Args:
        func: Function to execute in thread
        *args: Function arguments
        **kwargs: Function keyword arguments
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        global_error_handler.handle_thread_error(e, f"THREAD_{func.__name__}")
        return None

# Custom exception classes
class EzPrintError(Exception):
    """Base exception for EzPrint application"""
    pass

class PrinterError(EzPrintError):
    """Printer-related errors"""
    pass

class DatabaseError(EzPrintError):
    """Database-related errors"""
    pass

class FileProcessingError(EzPrintError):
    """File processing errors"""
    pass

class WebSocketError(EzPrintError):
    """WebSocket communication errors"""
    pass

class ValidationError(EzPrintError):
    """Validation errors"""
    pass

# Initialize error handling
def initialize_error_handling():
    """Initialize the global error handling system"""
    try:
        # Ensure log directory exists
        LOG_DIR.mkdir(exist_ok=True)
        
        # Log initialization
        error_logger.info("Global error handling system initialized")
        
        return True
    except Exception as e:
        print(f"Failed to initialize error handling: {e}")
        return False

# Auto-initialize when module is imported
initialize_error_handling()
