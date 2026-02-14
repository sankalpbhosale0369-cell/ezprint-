"""
Startup script for EzPrint MVP - Direct Shopkeeper App Launcher
"""
import os
import sys
import subprocess
import time
import threading
import logging
import requests
import socket
from pathlib import Path
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

# Add parent directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from shopkeeper_app.main import LoginWindow
from shared.database import init_database
from shared.global_error_handler import (
    global_error_handler, safe_execute, initialize_error_handling
)
from shared.config import WEB_HOST, WEB_PORT, EZPRINT_BASE_URL

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_dependencies():
    """Check if all required dependencies are installed"""
    try:
        import PyQt5
        import flask
        import qrcode
        import websockets
        import sqlalchemy
        import requests
        print("✓ All dependencies are installed")
        return True
    except ImportError as e:
        print(f"✗ Missing dependency: {e}")
        print("Please run: pip install -r requirements.txt")
        return False

def check_app_is_running(port=WEB_PORT, timeout=5):
    """Check if the web interface is running by pinging the health endpoint"""
    try:
        # First check if port is open
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((WEB_HOST, port))
        sock.close()
        
        if result != 0:
            return False
            
        # Try to ping the health endpoint
        response = requests.get(f'{EZPRINT_BASE_URL}/api/health', timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            return data.get('status') == 'healthy'
        return False
        
    except Exception as e:
        logger.debug(f"Health check failed: {e}")
        return False

def check_shopkeeper_app_running(process, startup_signal_file):
    """Check if the shopkeeper app is running by monitoring process and startup signal"""
    try:
        # Check if process is still running
        if process.poll() is not None:
            logger.debug("Shopkeeper process has terminated")
            return False
        
        # Check for startup signal file
        if os.path.exists(startup_signal_file):
            logger.debug("Startup signal file found - app is ready")
            return True
        
        # Fallback: Check if process has been running for a reasonable time
        # This helps catch cases where the signal file mechanism fails
        # but the app is actually running
        return False  # Only return True if we have the signal file
        
    except Exception as e:
        logger.debug(f"Shopkeeper app check failed: {e}")
        return False

def start_web_interface():
    """Start the web interface"""
    def _start_web():
        print("Starting web interface...")
        # Get absolute path to web_interface directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        web_interface_dir = os.path.join(current_dir, "web_interface")
        if not os.path.exists(web_interface_dir):
            print(f"Error: {web_interface_dir} directory not found")
            return
        os.chdir(web_interface_dir)
        subprocess.run([sys.executable, "app.py"], check=True)
    
    safe_execute(_start_web, error_context="WEB_INTERFACE_START", show_dialog=False)

def start_shopkeeper_app():
    """Start the shopkeeper desktop application with robust startup monitoring"""
    def _start_shopkeeper():
        logger.info("Starting shopkeeper application...")
        print("Starting shopkeeper application...")
        
        # Get absolute path to shopkeeper_app directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        shopkeeper_dir = os.path.join(current_dir, "shopkeeper_app")
        if not os.path.exists(shopkeeper_dir):
            error_msg = f"Shopkeeper directory not found: {shopkeeper_dir}"
            logger.error(error_msg)
            print(f"Error: {error_msg}")
            return False
        
        # Change to shopkeeper directory
        original_dir = os.getcwd()
        os.chdir(shopkeeper_dir)
        
        try:
            # Create startup signal file path
            startup_signal_file = os.path.join(shopkeeper_dir, "startup_signal.tmp")
            
            # Clean up any existing signal file
            if os.path.exists(startup_signal_file):
                os.remove(startup_signal_file)
            
            # Start the process without waiting
            logger.info("Launching shopkeeper process...")
            process = subprocess.Popen([sys.executable, "main.py"], 
                                     stdout=subprocess.PIPE, 
                                     stderr=subprocess.PIPE, 
                                     text=True)
            
            # Polling configuration
            max_retries = 15  # 30 seconds total (15 * 2 seconds)
            poll_interval = 2  # Check every 2 seconds
            fallback_timeout = 10  # Consider started if running for 10+ seconds without signal
            
            logger.info(f"Monitoring shopkeeper startup for up to {max_retries * poll_interval} seconds...")
            logger.info(f"Looking for startup signal file: {startup_signal_file}")
            
            start_time = time.time()
            
            for attempt in range(max_retries):
                logger.info(f"Startup check attempt {attempt + 1}/{max_retries}")
                
                # Check if process is still running
                if process.poll() is not None:
                    # Process has terminated
                    stdout, stderr = process.communicate()
                    error_msg = f"Shopkeeper app process terminated unexpectedly. Exit code: {process.returncode}"
                    if stderr:
                        error_msg += f"\nError output: {stderr}"
                    if stdout:
                        error_msg += f"\nOutput: {stdout}"
                    logger.error(error_msg)
                    print(f"Error: {error_msg}")
                    return False
                
                # Check if the app is running using the new method
                if check_shopkeeper_app_running(process, startup_signal_file):
                    logger.info("Shopkeeper app started successfully - startup signal detected")
                    print("✓ Shopkeeper app started successfully")
                    
                    # Clean up signal file
                    try:
                        if os.path.exists(startup_signal_file):
                            os.remove(startup_signal_file)
                    except Exception as e:
                        logger.warning(f"Could not clean up signal file: {e}")
                    
                    return True
                
                # Fallback: If process has been running for a while without crashing, consider it started
                elapsed_time = time.time() - start_time
                if elapsed_time >= fallback_timeout:
                    logger.info(f"Fallback: Process has been running for {elapsed_time:.1f} seconds without crashing")
                    print("✓ Shopkeeper app started successfully (fallback detection)")
                    return True
                
                # Log process output for debugging
                try:
                    # Non-blocking check for output
                    if process.stdout.readable():
                        # This won't block since we're not reading all output
                        pass
                except Exception as e:
                    logger.debug(f"Output check failed: {e}")
                
                # Wait before next check
                time.sleep(poll_interval)
            
            # If we get here, timeout occurred
            logger.error("Shopkeeper app startup timed out - no main window detected")
            print("✗ Shopkeeper app startup timed out")
            
            # Try to get any error output
            try:
                stdout, stderr = process.communicate(timeout=5)
                if stderr:
                    logger.error(f"Shopkeeper app error output: {stderr}")
                    print(f"Possible error: {stderr}")
            except subprocess.TimeoutExpired:
                logger.warning("Could not retrieve error output from timed out process")
            
            # Terminate the process if it's still running
            if process.poll() is None:
                logger.info("Terminating hung shopkeeper process...")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning("Force killing hung shopkeeper process...")
                    process.kill()
            
            return False
            
        except FileNotFoundError:
            error_msg = "Python executable not found. Please ensure Python is installed and in PATH."
            logger.error(error_msg)
            print(f"Error: {error_msg}")
            return False
        except Exception as e:
            error_msg = f"Unexpected error starting shopkeeper app: {e}"
            logger.error(error_msg)
            print(f"Error: {error_msg}")
            return False
        finally:
            # Restore original directory
            os.chdir(original_dir)
    
    success = safe_execute(_start_shopkeeper, error_context="SHOPKEEPER_APP_START", show_dialog=False)
    
    if not success:
        print("\n" + "="*60)
        print("SHOPKEEPER APP STARTUP FAILED")
        print("="*60)
        print("Possible reasons:")
        print("• Missing dependencies - run: pip install -r requirements.txt")
        print("• Database connection issues - check database configuration")
        print("• PyQt5 display issues - ensure GUI environment is available")
        print("• Configuration errors - check shared/config.py")
        print("• Port conflicts - ensure no other apps are using required ports")
        print("\nCheck the logs for detailed error information:")
        print(f"• Error log: {os.path.join(os.path.dirname(__file__), 'logs', 'error.log')}")
        print(f"• Main log: {os.path.join(os.path.dirname(__file__), 'logs', 'ezprint.log')}")
        print("="*60)
    
    return success

def main():
    """Main startup function"""
    # Initialize error handling
    initialize_error_handling()
    
    print("EzPrint MVP - Hybrid Printing System")
    print("=" * 40)
    
    # Check if we're in the right directory
    if not Path("requirements.txt").exists():
        print("✗ Please run this script from the project root directory")
        return
    
    # Check dependencies
    if not check_dependencies():
        return
    
    # Initialize database with error handling
    success = safe_execute(init_database, error_context="STARTUP_DATABASE_INIT", show_dialog=False)
    if success:
        print("✓ Database initialized")
    else:
        print("✗ Database initialization failed")
        return
    
    print("\nChoose startup option:")
    print("1. Start Web Interface only")
    print("2. Start Shopkeeper App only")
    print("3. Start Both (recommended)")
    print("4. Exit")
    
    choice = input("\nEnter your choice (1-4): ").strip()
    
    if choice == "1":
        start_web_interface()
    elif choice == "2":
        success = start_shopkeeper_app()
        if not success:
            print("\nShopkeeper app failed to start. Please check the error messages above.")
    elif choice == "3":
        print("\nStarting both applications...")
        print(f"Web interface will be available at: {EZPRINT_BASE_URL}")
        print("Press Ctrl+C to stop both applications")
        
        # Start web interface in a separate thread with error handling
        def safe_web_thread():
            safe_execute(start_web_interface, error_context="WEB_THREAD", show_dialog=False)
        
        web_thread = threading.Thread(target=safe_web_thread)
        web_thread.daemon = True
        web_thread.start()
        
        # Wait a moment for web interface to start
        time.sleep(2)
        
        # Start shopkeeper app in main thread with error handling
        try:
            success = start_shopkeeper_app()
            if not success:
                print("\nShopkeeper app failed to start. Web interface may still be running.")
        except KeyboardInterrupt:
            print("\nShutting down...")
    elif choice == "4":
        print("Goodbye!")
    else:
        print("Invalid choice. Please run the script again.")

if __name__ == "__main__":
    main()
