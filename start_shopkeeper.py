"""
Direct Shopkeeper App Launcher
"""
import os
import sys
import logging
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

# Fix Windows console encoding for emoji characters
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach())

# Add parent directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from shopkeeper_app.main import LoginWindow
from shared.database import init_database

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    """Main application entry point"""
    try:
        # Initialize database
        init_database()
        
        # Create application
        app = QApplication(sys.argv)
        app.setApplicationName("EzPrint Shopkeeper")
        app.setApplicationVersion("1.0.0")
        
        # Create and show login window
        login_window = LoginWindow()
        login_window.show()
        
        # Run application
        sys.exit(app.exec_())
        
    except Exception as e:
        logger.error(f"Application error: {e}")
        print(f"Application failed to start: {e}")

if __name__ == "__main__":
    main()
