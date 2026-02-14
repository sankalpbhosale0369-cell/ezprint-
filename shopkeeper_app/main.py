"""
Main application entry point for shopkeeper desktop app
"""
import sys
import os
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QLabel, QPushButton, QLineEdit, 
                           QMessageBox, QTabWidget, QGroupBox, QTextEdit,
                           QComboBox, QCheckBox, QFormLayout, QFrame)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QPixmap, QIcon
import logging

# Add parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shopkeeper_app.auth import AuthManager
from shopkeeper_app.dashboard import DashboardWindow
from shared.database import init_database
from shared.config import LOG_FILE
from shared.global_error_handler import (
    global_error_handler, safe_execute, safe_ui_action, 
    wrap_main_application, initialize_error_handling
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class LoginWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.auth_manager = AuthManager()
        self.init_ui()
    
    def init_ui(self):
        """Initialize the user interface (modern SaaS style)"""
        self.setWindowTitle("EzPrint - Shopkeeper Portal")
        self.resize(800, 600)

        # Central widget
        central_widget = QWidget()
        central_widget.setStyleSheet("background:#f9f9f9;")
        self.setCentralWidget(central_widget)

        # Main layout centered
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)
        main_layout.setAlignment(Qt.AlignCenter)

        # Landing header (title, subtitle, desc, CTA)
        header = QVBoxLayout()
        header.setSpacing(6)

        title = QLabel("Print Documents")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Segoe UI", 26, QFont.Bold))
        title.setStyleSheet("color:#111111;")
        header.addWidget(title)

        subtitle = QLabel("Without the Hassle")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setFont(QFont("Segoe UI", 18, QFont.Bold))
        subtitle.setStyleSheet("color:#1976d2;")
        header.addWidget(subtitle)

        desc = QLabel("Easily manage and print documents with your connected printers.")
        desc.setAlignment(Qt.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#6b7280; font-size:13px;")
        header.addWidget(desc)

        cta_btn = QPushButton("Login as Shopkeeper")
        cta_btn.setCursor(Qt.PointingHandCursor)
        cta_btn.setStyleSheet("""
            QPushButton { background:#1976d2; color:#ffffff; border:none; padding:10px 18px; border-radius:8px; font-weight:700; }
            QPushButton:hover { background:#165fa8; }
        """)
        header.addWidget(cta_btn, alignment=Qt.AlignCenter)

        main_layout.addLayout(header)

        # Auth tabs (hidden tab bar; acts like stacked pages)
        self.tab_widget = QTabWidget()
        self.tab_widget.tabBar().setVisible(False)
        self.tab_widget.setStyleSheet("QTabWidget::pane { border:0; }")
        main_layout.addWidget(self.tab_widget, 1)

        # Login and Register pages
        login_tab = self.create_login_tab()
        register_tab = self.create_register_tab()
        self.tab_widget.addTab(login_tab, "Login")
        self.tab_widget.addTab(register_tab, "Register")

        # CTA should focus the login card
        def goto_login():
            self.tab_widget.setCurrentIndex(0)
            try:
                self.login_username.setFocus()
            except Exception:
                pass
        cta_btn.clicked.connect(goto_login)
    
    def create_login_tab(self):
        """Create login tab (modern card)"""
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setAlignment(Qt.AlignTop)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        # Portal card
        card = QFrame()
        card.setStyleSheet("""
            QFrame { background:#ffffff; border:1px solid #e5e7eb; border-radius:12px; }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.setSpacing(12)

        title = QLabel("Shopkeeper Portal")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        card_layout.addWidget(title)

        # Inputs with modern style
        input_style = (
            "QLineEdit { padding:10px 12px; border:1px solid #e5e7eb; border-radius:8px; background:#ffffff; }"
            "QLineEdit:focus { border:1px solid #1976d2; }"
        )

        self.login_username = QLineEdit()
        self.login_username.setPlaceholderText("Enter your email")
        self.login_username.setStyleSheet(input_style)
        card_layout.addWidget(self.login_username)

        self.login_password = QLineEdit()
        self.login_password.setEchoMode(QLineEdit.Password)
        self.login_password.setPlaceholderText("Enter your password")
        self.login_password.setStyleSheet(input_style)
        card_layout.addWidget(self.login_password)

        self.remember_me = QCheckBox("Remember me for 30 days")
        card_layout.addWidget(self.remember_me)

        login_btn = QPushButton("Sign In")
        login_btn.setCursor(Qt.PointingHandCursor)
        login_btn.setStyleSheet("""
            QPushButton { background:#1976d2; color:#ffffff; border:none; padding:10px 16px; border-radius:8px; font-weight:700; }
            QPushButton:hover { background:#165fa8; }
        """)
        login_btn.clicked.connect(self.login)
        card_layout.addWidget(login_btn)

        # Register link
        register_link = QLabel("Don't have an account? <a href='#'>Register your shop</a>")
        register_link.setAlignment(Qt.AlignCenter)
        register_link.setStyleSheet("color:#1976d2;")
        register_link.setOpenExternalLinks(False)
        register_link.linkActivated.connect(lambda _: self.tab_widget.setCurrentIndex(1))
        card_layout.addWidget(register_link)

        outer.addWidget(card, alignment=Qt.AlignHCenter)
        outer.addStretch()
        return tab
    
    def create_register_tab(self):
        """Create register tab (modern card)"""
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setAlignment(Qt.AlignTop)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        # Titles
        title = QLabel("Register Your Shop")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Segoe UI", 22, QFont.Bold))
        title.setStyleSheet("color:#111111;")
        outer.addWidget(title)

        subtitle = QLabel("Join our printing network")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setFont(QFont("Segoe UI", 16, QFont.Bold))
        subtitle.setStyleSheet("color:#1976d2;")
        outer.addWidget(subtitle)

        # Card
        card = QFrame()
        card.setStyleSheet("QFrame { background:#ffffff; border:1px solid #e5e7eb; border-radius:12px; }")
        form = QVBoxLayout(card)
        form.setContentsMargins(24, 24, 24, 24)
        form.setSpacing(12)

        input_style = (
            "QLineEdit { padding:10px 12px; border:1px solid #e5e7eb; border-radius:8px; background:#ffffff; }"
            "QLineEdit:focus { border:1px solid #1976d2; }"
        )

        self.reg_shop_name = QLineEdit()
        self.reg_shop_name.setPlaceholderText("Enter shop name")
        self.reg_shop_name.setStyleSheet(input_style)
        form.addWidget(self.reg_shop_name)

        self.reg_email = QLineEdit()
        self.reg_email.setPlaceholderText("Enter your email")
        self.reg_email.setStyleSheet(input_style)
        form.addWidget(self.reg_email)

        self.reg_username = QLineEdit()
        self.reg_username.setPlaceholderText("Create username")
        self.reg_username.setStyleSheet(input_style)
        form.addWidget(self.reg_username)

        self.reg_password = QLineEdit()
        self.reg_password.setEchoMode(QLineEdit.Password)
        self.reg_password.setPlaceholderText("Create password")
        self.reg_password.setStyleSheet(input_style)
        form.addWidget(self.reg_password)

        self.reg_confirm_password = QLineEdit()
        self.reg_confirm_password.setEchoMode(QLineEdit.Password)
        self.reg_confirm_password.setPlaceholderText("Confirm password")
        self.reg_confirm_password.setStyleSheet(input_style)
        form.addWidget(self.reg_confirm_password)

        register_btn = QPushButton("Register")
        register_btn.setCursor(Qt.PointingHandCursor)
        register_btn.setStyleSheet("""
            QPushButton { background:#1976d2; color:#ffffff; border:none; padding:10px 16px; border-radius:8px; font-weight:700; }
            QPushButton:hover { background:#165fa8; }
        """)
        register_btn.clicked.connect(self.register)
        form.addWidget(register_btn)

        login_link = QLabel("Already have an account? <a href='#'>Login here</a>")
        login_link.setAlignment(Qt.AlignCenter)
        login_link.setStyleSheet("color:#1976d2;")
        login_link.setOpenExternalLinks(False)
        login_link.linkActivated.connect(lambda _: self.tab_widget.setCurrentIndex(0))
        form.addWidget(login_link)

        outer.addWidget(card, alignment=Qt.AlignHCenter)
        outer.addStretch()
        return tab
    
    @safe_ui_action("LOGIN")
    def login(self, *args, **kwargs):
        """Handle login"""
        username = self.login_username.text().strip()
        password = self.login_password.text()
        
        if not username or not password:
            self.show_error_message("Please fill in all fields")
            return
        
        success, message, shopkeeper_data = self.auth_manager.login_shopkeeper(username, password)
        
        if success:
            self.show_success_message("Login Successful")
            # Small delay to show success message before opening dashboard
            # Use safe delayed open to avoid invoking methods on deleted windows
            def _open():
                try:
                    self.open_dashboard(shopkeeper_data)
                except Exception:
                    pass
            QTimer.singleShot(1000, _open)
        else:
            self.show_error_message("Invalid credentials")
    
    @safe_ui_action("REGISTRATION")
    def register(self):
        """Handle registration"""
        username = self.reg_username.text().strip()
        email = self.reg_email.text().strip()
        shop_name = self.reg_shop_name.text().strip()
        password = self.reg_password.text()
        confirm_password = self.reg_confirm_password.text()
        
        # Validation
        if not all([username, email, shop_name, password, confirm_password]):
            QMessageBox.warning(self, "Warning", "Please fill in all fields")
            return
        
        if password != confirm_password:
            QMessageBox.warning(self, "Warning", "Passwords do not match")
            return
        
        if len(password) < 6:
            QMessageBox.warning(self, "Warning", "Password must be at least 6 characters")
            return
        
        success, message, shopkeeper_data = self.auth_manager.register_shopkeeper(
            username, email, password, shop_name
        )
        
        if success:
            self.show_success_message(f"Registration Successful! Shop ID: {shopkeeper_data['shop_id']}")
            # Small delay to show success message before opening dashboard
            def _open_after_register():
                try:
                    self.open_dashboard(shopkeeper_data)
                except Exception:
                    pass
            QTimer.singleShot(1500, _open_after_register)
        else:
            self.show_error_message(message)
    
    @safe_ui_action("OPEN_DASHBOARD")
    def open_dashboard(self, shopkeeper_data):
        """Open dashboard window"""
        try:
            logger.info("Opening dashboard window...")
            
            def on_logout():
                try:
                    logger.info("Logout requested, returning to login window")
                    self.show()
                except Exception as e:
                    logger.error(f"Error during logout: {e}")
                    pass
            
            # Create dashboard window with error handling
            logger.info("Creating DashboardWindow instance...")
            self.dashboard = DashboardWindow(shopkeeper_data, on_logout=on_logout)
            
            logger.info("Showing dashboard window...")
            self.dashboard.show()
            
            logger.info("Hiding login window...")
            self.hide()
            
            # Update startup signal file to indicate dashboard is ready
            try:
                startup_signal_file = os.path.join(os.path.dirname(__file__), "startup_signal.tmp")
                with open(startup_signal_file, 'w') as f:
                    f.write(f"Dashboard ready at {datetime.now().isoformat()}")
                logger.info(f"Startup signal file updated: {startup_signal_file}")
            except Exception as e:
                logger.warning(f"Could not update startup signal file: {e}")
            
            logger.info("Dashboard window opened successfully")
            
        except Exception as e:
            logger.error(f"Failed to open dashboard: {e}")
            self.show_error_message(f"Failed to open dashboard: {e}")
            # Don't hide the login window if dashboard fails
    
    def show_success_message(self, message):
        """Show a success toast message that auto-disappears"""
        self.show_toast_message(message, "#10b981", 1000)  # Green color, 1 second
    
    def show_error_message(self, message):
        """Show an error toast message that auto-disappears"""
        self.show_toast_message(message, "#ef4444", 2000)  # Red color, 2 seconds
    
    def show_toast_message(self, message, color, duration):
        """Show a toast-style message at the top of the window"""
        try:
            # Create toast label
            toast = QLabel(message)
            toast.setStyleSheet(f"""
                QLabel {{
                    background-color: {color};
                    color: white;
                    padding: 12px 20px;
                    border-radius: 8px;
                    font-weight: 500;
                    font-size: 14px;
                    border: none;
                }}
            """)
            toast.setAlignment(Qt.AlignCenter)
            toast.setWordWrap(True)
            
            # Set minimum width and height
            toast.setMinimumWidth(200)
            toast.setFixedHeight(50)
            
            # Position at top center of the window
            x = (self.width() - toast.width()) // 2
            y = 30  # 30px from top
            toast.move(x, y)
            toast.show()
            
            # Auto-hide after duration
            try:
                QTimer.singleShot(duration, toast.deleteLater)
            except Exception:
                pass
            
        except Exception as e:
            logger.error(f"Error showing toast message: {e}")
            # Fallback to simple message box if toast fails
            QMessageBox.information(self, "Info", message)

def main():
    """Main application entry point"""
    # Initialize error handling
    initialize_error_handling()
    
    # Initialize database with error handling
    safe_execute(init_database, error_context="DATABASE_INIT", show_dialog=True)
    
    # Create application
    app = QApplication(sys.argv)
    app.setApplicationName("EzPrint Shopkeeper")
    app.setApplicationVersion("1.0.0")
    
    # Set up fast shutdown handling
    def force_quit():
        """Force quit the application immediately"""
        logger.info("Force quit requested")
        app.quit()
        sys.exit(0)
    
    # Handle Ctrl+C and other termination signals
    import signal
    signal.signal(signal.SIGINT, lambda s, f: force_quit())
    signal.signal(signal.SIGTERM, lambda s, f: force_quit())
    
    # Create and show login window
    login_window = safe_execute(LoginWindow, error_context="LOGIN_WINDOW_CREATION", show_dialog=True)
    if login_window:
        login_window.show()
        
        # Create startup signal file to indicate GUI is ready
        try:
            startup_signal_file = os.path.join(os.path.dirname(__file__), "startup_signal.tmp")
            with open(startup_signal_file, 'w') as f:
                f.write(f"Login window ready at {datetime.now().isoformat()}")
            logger.info(f"Startup signal file created: {startup_signal_file}")
        except Exception as e:
            logger.warning(f"Could not create startup signal file: {e}")
        
        # Run application with error handling and aggressive shutdown
        try:
            # Set up aggressive shutdown handling
            def force_shutdown():
                logger.info("Force shutdown requested")
                app.quit()
                sys.exit(0)
            
            # Handle Ctrl+C and other termination signals
            import signal
            signal.signal(signal.SIGINT, lambda s, f: force_shutdown())
            signal.signal(signal.SIGTERM, lambda s, f: force_shutdown())
            
            # Run with timeout to prevent hanging
            exit_code = wrap_main_application(app.exec_)
            
        except KeyboardInterrupt:
            logger.info("Application interrupted by user")
            exit_code = 0
        except Exception as e:
            logger.error(f"Unexpected error in main application: {e}")
            exit_code = 1
        finally:
            # Cleanup startup signal file
            try:
                startup_signal_file = os.path.join(os.path.dirname(__file__), "startup_signal.tmp")
                if os.path.exists(startup_signal_file):
                    os.remove(startup_signal_file)
            except Exception:
                pass
            
            # Force exit if still running
            try:
                app.quit()
            except Exception:
                pass
        
        # Force exit
        try:
            os._exit(exit_code)
        except Exception:
            sys.exit(exit_code)
    else:
        logger.error("Failed to create login window")
        sys.exit(1)

if __name__ == "__main__":
    main()
