"""
Main application entry point for shopkeeper desktop app
"""
import sys
import os
from datetime import datetime, timedelta
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                           QHBoxLayout, QLabel, QPushButton, QLineEdit, 
                           QMessageBox, QTabWidget, QGroupBox, QTextEdit,
                           QComboBox, QCheckBox, QFormLayout, QFrame,
                           QDialog, QStackedWidget)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QPixmap, QIcon
import logging

# Add parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shopkeeper_app.auth import AuthManager
from shopkeeper_app.dashboard import DashboardWindow
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


import json

SESSION_DIR = os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~/.ezprint"),
    "EzPrint",
)
SESSION_FILE = os.path.join(SESSION_DIR, "session.json")

def save_session(shopkeeper_data):
    try:
        os.makedirs(SESSION_DIR, exist_ok=True)
        session = {
            "shopkeeper_data": shopkeeper_data,
            "timestamp": datetime.now().isoformat()
        }
        with open(SESSION_FILE, "w") as f:
            json.dump(session, f)
        logger.info("Session saved")
    except Exception as e:
        logger.error(f"Session save failed: {e}")

def load_session():
    try:
        if not os.path.exists(SESSION_FILE):
            return None
        with open(SESSION_FILE, "r") as f:
            data = json.load(f)
        timestamp = datetime.fromisoformat(data["timestamp"])
        if datetime.now() - timestamp > timedelta(days=15):
            os.remove(SESSION_FILE)
            return None
        return data["shopkeeper_data"]
    except Exception as e:
        logger.error(f"Session load failed: {e}")
        return None

def clear_session():
    try:
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
            logger.info("Session cleared")
    except Exception as e:
        logger.error(f"Session clear failed: {e}")

class ForgotPasswordDialog(QDialog):
    def __init__(self, auth_manager, parent=None):
        super().__init__(parent)
        self.auth_manager = auth_manager
        self.username = None
        self.setWindowTitle("Forgot Password")
        self.setFixedWidth(400)
        self.setStyleSheet("""
            QDialog { background-color: #f8fafc; }
            QLabel { color: #0d2a5e; font-size: 14px; }
            QLineEdit {
                padding: 10px;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                font-size: 14px;
                background: white;
            }
            QPushButton {
                background-color: #1A73E8;
                color: white;
                padding: 10px;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover { background-color: #114488; }
        """)
        
        self.stack = QStackedWidget()
        self.init_screen1()
        self.init_screen2()
        self.init_screen3()
        
        layout = QVBoxLayout()
        layout.addWidget(self.stack)
        self.setLayout(layout)
    
    def init_screen1(self):
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        title = QLabel("Forgot Password")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        
        info = QLabel("Enter your username or email.\nOTP will be sent to your registered email.")
        info.setAlignment(Qt.AlignCenter)
        info.setStyleSheet("color: #64748b; font-size: 13px;")
        info.setWordWrap(True)
        
        self.s1_username = QLineEdit()
        self.s1_username.setPlaceholderText("Enter your username or email")
        
        btn = QPushButton("Send OTP")
        btn.clicked.connect(self.handle_send_otp)
        
        layout.addWidget(title)
        layout.addWidget(info)
        layout.addWidget(QLabel("Username"))
        layout.addWidget(self.s1_username)
        layout.addWidget(btn)
        widget.setLayout(layout)
        self.stack.addWidget(widget)
    
    def init_screen2(self):
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        title = QLabel("Enter OTP")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        
        self.s2_info = QLabel("OTP sent to your registered email.\nValid for 10 minutes.")
        self.s2_info.setAlignment(Qt.AlignCenter)
        self.s2_info.setStyleSheet("color: #64748b; font-size: 13px;")
        self.s2_info.setWordWrap(True)
        
        self.s2_otp = QLineEdit()
        self.s2_otp.setPlaceholderText("Enter 6-digit OTP")
        self.s2_otp.setMaxLength(6)
        self.s2_otp.setAlignment(Qt.AlignCenter)
        
        btn = QPushButton("Verify OTP")
        btn.clicked.connect(self.handle_verify_otp)
        
        layout.addWidget(title)
        layout.addWidget(self.s2_info)
        layout.addWidget(QLabel("OTP"))
        layout.addWidget(self.s2_otp)
        layout.addWidget(btn)
        widget.setLayout(layout)
        self.stack.addWidget(widget)
    
    def init_screen3(self):
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        title = QLabel("Reset Password")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        
        self.s3_new_pass = QLineEdit()
        self.s3_new_pass.setPlaceholderText("Enter new password")
        self.s3_new_pass.setEchoMode(QLineEdit.Password)
        
        self.s3_confirm_pass = QLineEdit()
        self.s3_confirm_pass.setPlaceholderText("Confirm new password")
        self.s3_confirm_pass.setEchoMode(QLineEdit.Password)
        
        btn = QPushButton("Reset Password")
        btn.clicked.connect(self.handle_reset_password)
        
        layout.addWidget(title)
        layout.addWidget(QLabel("New Password"))
        layout.addWidget(self.s3_new_pass)
        layout.addWidget(QLabel("Confirm Password"))
        layout.addWidget(self.s3_confirm_pass)
        layout.addWidget(btn)
        widget.setLayout(layout)
        self.stack.addWidget(widget)
    
    def handle_send_otp(self):
        username = self.s1_username.text().strip()
        if not username:
            QMessageBox.warning(self, "Error", "Please enter username")
            return
        success, message = self.auth_manager.send_otp_email(username)
        if success:
            self.username = username
            self.stack.setCurrentIndex(1)
        else:
            QMessageBox.warning(self, "Error", message)
    
    def handle_verify_otp(self):
        otp = self.s2_otp.text().strip()
        if len(otp) != 6:
            QMessageBox.warning(self, "Error", "Enter valid 6-digit OTP")
            return
        success, message = self.auth_manager.verify_otp(self.username, otp)
        if success:
            self.stack.setCurrentIndex(2)
        else:
            QMessageBox.warning(self, "Error", message)
    
    def handle_reset_password(self):
        new_pass = self.s3_new_pass.text()
        confirm = self.s3_confirm_pass.text()
        if not new_pass or not confirm:
            QMessageBox.warning(self, "Error", "Please fill all fields")
            return
        if new_pass != confirm:
            QMessageBox.warning(self, "Error", "Passwords do not match")
            return
        if len(new_pass) < 6:
            QMessageBox.warning(self, "Error", "Minimum 6 characters required")
            return
        success, message = self.auth_manager.reset_password(self.username, new_pass)
        if success:
            QMessageBox.information(self, "Success", "Password reset successful!")
            self.accept()
        else:
            QMessageBox.warning(self, "Error", message)


class LoginWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.auth_manager = AuthManager()
        self.setWindowIcon(QIcon("assets/icons/ezprint.ico"))
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
        subtitle.setStyleSheet("color:#1A73E8;")
        header.addWidget(subtitle)

        desc = QLabel("Easily manage and print documents with your connected printers.")
        desc.setAlignment(Qt.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#6b7280; font-size:13px;")
        header.addWidget(desc)

        cta_btn = QPushButton("Login as Shopkeeper")
        cta_btn.setCursor(Qt.PointingHandCursor)
        cta_btn.setStyleSheet("""
            QPushButton { background:#1A73E8; color:#ffffff; border:none; padding:10px 18px; border-radius:8px; font-weight:700; }
            QPushButton:hover { background:#114488; }
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
            "QLineEdit:focus { border:1px solid #1A73E8; }"
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
            QPushButton { background:#1A73E8; color:#ffffff; border:none; padding:10px 16px; border-radius:8px; font-weight:700; }
            QPushButton:hover { background:#114488; }
        """)
        login_btn.clicked.connect(self.login)
        card_layout.addWidget(login_btn)

        # Forgot password link
        forgot_link = QPushButton("Forgot Password?")
        forgot_link.setStyleSheet("""
            QPushButton {
                background: none;
                border: none;
                color: #1A73E8;
                font-size: 13px;
                text-decoration: underline;
            }
            QPushButton:hover { color: #114488; }
        """)
        forgot_link.setCursor(Qt.PointingHandCursor)
        forgot_link.clicked.connect(self.open_forgot_password)
        card_layout.addWidget(forgot_link)

        # Register link
        register_link = QLabel("Don't have an account? <a href='#'>Register your shop</a>")
        register_link.setAlignment(Qt.AlignCenter)
        register_link.setStyleSheet("color:#1A73E8;")
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
        subtitle.setStyleSheet("color:#1A73E8;")
        outer.addWidget(subtitle)

        # Card
        card = QFrame()
        card.setStyleSheet("QFrame { background:#ffffff; border:1px solid #e5e7eb; border-radius:12px; }")
        form = QVBoxLayout(card)
        form.setContentsMargins(24, 24, 24, 24)
        form.setSpacing(12)

        input_style = (
            "QLineEdit { padding:10px 12px; border:1px solid #e5e7eb; border-radius:8px; background:#ffffff; }"
            "QLineEdit:focus { border:1px solid #1A73E8; }"
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
            QPushButton { background:#1A73E8; color:#ffffff; border:none; padding:10px 16px; border-radius:8px; font-weight:700; }
            QPushButton:hover { background:#114488; }
        """)
        register_btn.clicked.connect(self.register)
        form.addWidget(register_btn)

        login_link = QLabel("Already have an account? <a href='#'>Login here</a>")
        login_link.setAlignment(Qt.AlignCenter)
        login_link.setStyleSheet("color:#1A73E8;")
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
            save_session(shopkeeper_data)
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
            self.show_error_message(message)
    
    def open_forgot_password(self):
        dialog = ForgotPasswordDialog(self.auth_manager, self)
        dialog.exec_()
    
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
            from shopkeeper_app.licensing import check_license
            check_license(email=email, shop_name=shop_name)
            self.show_success_message(f"Registration Successful! Shop ID: {shopkeeper_data['shop_id']}")
            save_session(shopkeeper_data)
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
                    clear_session()
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
        self.show_toast_message(message, "#34A853", 1000)  # Green color, 1 second
    
    def show_error_message(self, message):
        """Show an error toast message that auto-disappears"""
        self.show_toast_message(message, "#ef4444", 2000)  # Red color, 2 seconds
    
    def show_toast_message(self, message, color, duration):
        """Show a toast-style message at the top of the window"""
        try:
            # Create toast label
            toast = QLabel(message, self.centralWidget())
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
            toast.adjustSize()
            x = (self.width() - toast.width()) // 2
            y = 30
            toast.move(x, y)
            toast.show()
            
            # Auto-hide after duration
            try:
                QTimer.singleShot(duration, toast.deleteLater)
            except Exception:
                pass
            
        except Exception as e:
            logger.error(f"Error showing toast message: {e}")
            # No recursive call — just log the error

def main():
    """Main application entry point"""

    # Initialize error handling
    initialize_error_handling()

    # The FastAPI backend owns all persistence now, but a few client paths
    # (notably `printer_manager` activation / heartbeat bookkeeping) still
    # read & write a local SQLite cache via `shared.database`. Ensure that
    # schema exists before the UI boots so activation doesn't fail with
    # "no such table: printers" on a fresh install. This whole block can be
    # removed once the printer registry is fully migrated to the API.
    try:
        from shared.database import init_database
        init_database()
    except Exception as db_init_err:
        logger.warning(f"Local schema bootstrap failed (non-fatal): {db_init_err}")

    import os
    import sys
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    # DPI / scaling support
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    # Create application
    app = QApplication(sys.argv)

    app.setApplicationName("EzPrint Shopkeeper")
    app.setApplicationVersion("1.0.0")
    app.setWindowIcon(QIcon("assets/icons/ezprint.ico"))
    
    # --- License gate ---
    from shopkeeper_app.licensing import verify_startup_license
    if not verify_startup_license():
        sys.exit(0)

    # --- Check for updates (background) ---
    def check_updates_on_startup():
        """Check for updates in background and notify user"""
        try:
            from shared.auto_updater import check_for_updates_async
            from shared import version as app_version

            def on_update_available(update_info):
                """Show update notification dialog"""
                try:
                    from PyQt5.QtWidgets import QMessageBox

                    msg_box = QMessageBox()
                    msg_box.setWindowTitle("Update Available")
                    msg_box.setIcon(QMessageBox.Information)

                    version_str = update_info.get('version', 'Unknown')
                    is_critical = update_info.get('critical', False)
                    release_notes = update_info.get('release_notes', 'New version available')

                    if is_critical:
                        msg_box.setText(f"Critical Update Required: v{version_str}")
                        msg_box.setInformativeText(
                            f"A critical security update is available.\n\n{release_notes}\n\n"
                            "The application will now download and install the update."
                        )
                        msg_box.setStandardButtons(QMessageBox.Ok)
                        msg_box.exec_()

                        # Start automatic download for critical updates
                        from shared.auto_updater import download_and_install_async
                        download_and_install_async(update_info)
                    else:
                        msg_box.setText(f"Update Available: v{version_str}")
                        msg_box.setInformativeText(
                            f"Current version: v{app_version.VERSION}\n"
                            f"Latest version: v{version_str}\n\n{release_notes}\n\n"
                            "Would you like to download and install this update?"
                        )
                        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)

                        result = msg_box.exec_()
                        if result == QMessageBox.Yes:
                            from shared.auto_updater import download_and_install_async
                            download_and_install_async(update_info)
                except Exception as e:
                    logger.error(f"Error showing update dialog: {e}")

            # Check for updates in background
            check_for_updates_async(callback=on_update_available)
            logger.info("Background update check initiated")
        except Exception as e:
            logger.warning(f"Update check failed: {e}")

    # Start update check after a short delay (non-blocking)
    QTimer.singleShot(3000, check_updates_on_startup)  # Check after 3 seconds

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
    saved_session = load_session()
    login_window = safe_execute(LoginWindow, error_context="LOGIN_WINDOW_CREATION", show_dialog=True)
    if login_window:
        if saved_session:
            logger.info("Auto-login session found, refreshing tokens...")
            # Validate the saved session and refresh tokens before opening the
            # dashboard. resume_session() refreshes the access token, mints a
            # fresh agent JWT, and returns an updated shopkeeper_data dict.
            fresh = login_window.auth_manager.resume_session()
            if fresh:
                logger.info("Session resumed successfully")
                login_window.open_dashboard(fresh)
            else:
                logger.info("Saved session expired or invalid, showing login")
                login_window.show()
        else:
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
