"""
Authentication system for shopkeeper application
"""
import bcrypt
import uuid
from datetime import datetime
from sqlalchemy.orm import Session
import sys
import os

# Add parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import Shopkeeper, SessionLocal
from shared.qr_generator import generate_qr_code
from shared.config import LOG_FILE, EZPRINT_BASE_URL
from shopkeeper_app.api_client import ApiClient
import logging

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

class AuthManager:
    def __init__(self):
        self.db = SessionLocal()
        self.api_client = ApiClient()
    
    def hash_password(self, password):
        """Hash password using bcrypt"""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def verify_password(self, password, hashed):
        """Verify password against hash"""
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    
    def register_shopkeeper(self, username, email, password, shop_name):
        """
        Register a new shopkeeper
        
        Args:
            username (str): Username
            email (str): Email address
            password (str): Plain text password
            shop_name (str): Name of the shop
        
        Returns:
            tuple: (success, message, shopkeeper_data)
        """
        try:
            # Check if username or email already exists
            existing_user = self.db.query(Shopkeeper).filter(
                (Shopkeeper.username == username) | (Shopkeeper.email == email)
            ).first()
            
            if existing_user:
                return False, "Username or email already exists", None
            
            # Hash password
            password_hash = self.hash_password(password)
            
            # Create shopkeeper
            shopkeeper = Shopkeeper(
                username=username,
                email=email,
                password_hash=password_hash,
                shop_name=shop_name
            )
            
            # Generate QR code
            qr_path = generate_qr_code(shopkeeper.shop_id, shop_name)
            shopkeeper.qr_code_path = qr_path
            
            # Save to database
            self.db.add(shopkeeper)
            self.db.commit()
            
            logger.info(f"New shopkeeper registered: {username} (Shop ID: {shopkeeper.shop_id})")
            
            return True, "Registration successful", {
                'shop_id': shopkeeper.shop_id,
                'username': shopkeeper.username,
                'shop_name': shopkeeper.shop_name,
                'shop_address': shopkeeper.shop_address,
                'contact_number': shopkeeper.contact_number,
                'shopkeeper_name': shopkeeper.shopkeeper_name,
                'email': shopkeeper.email,
                'qr_code_path': qr_path
            }
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Registration error: {e}")
            return False, f"Registration failed: {str(e)}", None
    
    def login_shopkeeper(self, username, password):
        """
        Login shopkeeper (API-First with DB Fallback)
        
        Args:
            username (str): Username or email
            password (str): Plain text password
        
        Returns:
            tuple: (success, message, shopkeeper_data)
        """
        try:
            # Phase 4: Primary API Login attempt
            logger.info(f"Attempting API-first login for user: {username}")
            api_success, api_data, api_error = self.api_client.login(username, password)
            
            if api_success and api_data:
                logger.info(f"API login successful for user: {username}")
                # API returns full shopkeeper data including session_token
                return True, "Login successful", api_data
            
            # If API failed, check if it was a connection error or a credential error
            if api_error and "Cannot connect" in api_error:
                logger.warning(f"API unavailable, falling back to database authentication: {api_error}")
            else:
                # If API returned a specific 401/403 (Invalid credentials), we still try DB fallback 
                # as a safety measure for backward compatibility (e.g. user exists in local DB but not remote yet)
                logger.warning(f"API login failed ({api_error}), attempting database fallback for user: {username}")

            # Database Fallback
            shopkeeper = self.db.query(Shopkeeper).filter(
                (Shopkeeper.username == username) | (Shopkeeper.email == username)
            ).first()
            
            if not shopkeeper:
                return False, "Invalid credentials", None
            
            if not shopkeeper.is_active:
                return False, "Account is deactivated", None
            
            # Verify password against local hash
            if not self.verify_password(password, shopkeeper.password_hash):
                return False, "Invalid credentials", None
            
            logger.info(f"Database login successful (Fallback) for user: {shopkeeper.username}")
            
            # Prepare shopkeeper data from DB
            shopkeeper_data = {
                'shop_id': shopkeeper.shop_id,
                'username': shopkeeper.username,
                'shop_name': shopkeeper.shop_name,
                'shop_address': shopkeeper.shop_address,
                'contact_number': shopkeeper.contact_number,
                'shopkeeper_name': shopkeeper.shopkeeper_name,
                'email': shopkeeper.email,
                'qr_code_path': shopkeeper.qr_code_path,
                'session_token': None  # No JWT available from DB fallback
            }
            
            return True, "Login successful (Database Fallback)", shopkeeper_data
            
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False, f"Login failed: {str(e)}", None
    
    def logout_shopkeeper(self, shop_id=None):
        """
        Logout shopkeeper from API and cleanup local state
        """
        try:
            logger.info(f"Logging out shopkeeper: {shop_id}")
            # Attempt API logout first
            success, _, error = self.api_client.logout()
            if not success:
                logger.warning(f"API logout failed or was already inactive: {error}")
            
            # Local cleanup (if needed in future)
            return True, "Logged out successfully"
        except Exception as e:
            logger.error(f"Logout error: {e}")
            return False, str(e)
    
    def get_shopkeeper_by_id(self, shop_id):
        """Get shopkeeper by shop ID"""
        try:
            shopkeeper = self.db.query(Shopkeeper).filter(
                Shopkeeper.shop_id == shop_id
            ).first()
            
            if shopkeeper:
                return {
                    'shop_id': shopkeeper.shop_id,
                    'username': shopkeeper.username,
                    'shop_name': shopkeeper.shop_name,
                    'shop_address': shopkeeper.shop_address,
                    'contact_number': shopkeeper.contact_number,
                    'shopkeeper_name': shopkeeper.shopkeeper_name,
                    'email': shopkeeper.email,
                    'qr_code_path': shopkeeper.qr_code_path
                }
            return None
            
        except Exception as e:
            logger.error(f"Error getting shopkeeper: {e}")
            return None
    
    def update_shop_info(self, shop_id, shop_name=None, shop_address=None, contact_number=None, email=None, shopkeeper_name=None):
        """Update shopkeeper information"""
        try:
            shopkeeper = self.db.query(Shopkeeper).filter(Shopkeeper.shop_id == shop_id).first()
            if not shopkeeper:
                return False, "Shopkeeper not found", None
            
            # Update fields if provided
            if shop_name is not None:
                shopkeeper.shop_name = shop_name
            if shop_address is not None:
                shopkeeper.shop_address = shop_address
            if contact_number is not None:
                shopkeeper.contact_number = contact_number
            if email is not None:
                shopkeeper.email = email
            if shopkeeper_name is not None:
                shopkeeper.shopkeeper_name = shopkeeper_name
            
            self.db.commit()
            logger.info(f"Shop info updated for shop ID: {shop_id}")
            
            return True, "Shop information updated successfully", {
                'shop_id': shopkeeper.shop_id,
                'username': shopkeeper.username,
                'shop_name': shopkeeper.shop_name,
                'shop_address': shopkeeper.shop_address,
                'contact_number': shopkeeper.contact_number,
                'shopkeeper_name': shopkeeper.shopkeeper_name,
                'email': shopkeeper.email,
                'qr_code_path': shopkeeper.qr_code_path
            }
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error updating shop info: {e}")
            return False, f"Update failed: {str(e)}", None
    
    def close(self):
        """Close database connection"""
        self.db.close()
