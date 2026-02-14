"""
Authentication API endpoints
"""
from flask import Blueprint, request
import sys
import os
import logging
import bcrypt

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import SessionLocal, Shopkeeper
from utils.jwt_helper import generate_token, refresh_token as refresh_jwt_token
from utils.response_builder import success_response, error_response
from api.middleware import require_auth

# Setup logging
logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth_api', __name__, url_prefix='/api/auth')

@auth_bp.route('/login', methods=['POST'])
def login():
    """
    POST /api/auth/login
    
    Request:
        {
            "username": "string",
            "password": "string"
        }
    
    Response:
        {
            "success": true,
            "message": "Login successful",
            "data": {
                "shop_id": "uuid",
                "username": "string",
                "shop_name": "string",
                "shop_address": "string|null",
                "contact_number": "string|null",
                "shopkeeper_name": "string|null",
                "email": "string",
                "qr_code_path": "string",
                "session_token": "jwt-token"
            }
        }
    """
    try:
        data = request.get_json()
        
        # Validate request
        if not data or 'username' not in data or 'password' not in data:
            logger.warning("Login attempt with missing credentials")
            return error_response("Missing username or password", 400)
        
        username = data['username']
        password = data['password']
        
        # Database query
        db = SessionLocal()
        try:
            shopkeeper = db.query(Shopkeeper).filter(
                (Shopkeeper.username == username) | (Shopkeeper.email == username)
            ).first()
            
            if not shopkeeper:
                logger.warning(f"Login attempt with invalid username: {username}")
                return error_response("Invalid credentials", 401)
            
            if not shopkeeper.is_active:
                logger.warning(f"Login attempt for deactivated account: {username}")
                return error_response("Account is deactivated", 401)
            
            # Verify password
            if not bcrypt.checkpw(password.encode('utf-8'), shopkeeper.password_hash.encode('utf-8')):
                logger.warning(f"Login attempt with invalid password for user: {username}")
                return error_response("Invalid credentials", 401)
            
            # Generate JWT token
            session_token = generate_token(shopkeeper.shop_id, shopkeeper.username)
            
            # Build response
            response_data = {
                'shop_id': shopkeeper.shop_id,
                'username': shopkeeper.username,
                'shop_name': shopkeeper.shop_name,
                'shop_address': shopkeeper.shop_address,
                'contact_number': shopkeeper.contact_number,
                'shopkeeper_name': shopkeeper.shopkeeper_name,
                'email': shopkeeper.email,
                'qr_code_path': shopkeeper.qr_code_path,
                'session_token': session_token
            }
            
            logger.info(f"Successful login for user: {username} (shop_id: {shopkeeper.shop_id})")
            return success_response(response_data, "Login successful", 200)
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Login error: {str(e)}", exc_info=True)
        return error_response(f"Login failed: {str(e)}", 500)

@auth_bp.route('/logout', methods=['POST'])
@require_auth
def logout():
    """
    POST /api/auth/logout
    
    Request Headers:
        Authorization: Bearer <token>
    
    Request Body:
        {
            "shop_id": "uuid"
        }
    
    Response:
        {
            "success": true,
            "message": "Logged out successfully"
        }
    """
    try:
        # In stateless JWT, logout is client-side (delete token)
        # Optionally implement token blacklist here in future
        
        shop_id = request.shop_id  # From middleware
        logger.info(f"Logout for shop_id: {shop_id}")
        
        return success_response(None, "Logged out successfully", 200)
        
    except Exception as e:
        logger.error(f"Logout error: {str(e)}", exc_info=True)
        return error_response(f"Logout failed: {str(e)}", 500)

@auth_bp.route('/session', methods=['GET'])
@require_auth
def get_session():
    """
    GET /api/auth/session
    
    Request Headers:
        Authorization: Bearer <token>
    
    Response:
        {
            "success": true,
            "data": {
                "shop_id": "uuid",
                "username": "string",
                "shop_name": "string",
                ...
            }
        }
    """
    try:
        shop_id = request.shop_id  # From middleware
        
        # Fetch shopkeeper data
        db = SessionLocal()
        try:
            shopkeeper = db.query(Shopkeeper).filter(
                Shopkeeper.shop_id == shop_id
            ).first()
            
            if not shopkeeper:
                return error_response("Shop not found", 404)
            
            response_data = {
                'shop_id': shopkeeper.shop_id,
                'username': shopkeeper.username,
                'shop_name': shopkeeper.shop_name,
                'shop_address': shopkeeper.shop_address,
                'contact_number': shopkeeper.contact_number,
                'shopkeeper_name': shopkeeper.shopkeeper_name,
                'email': shopkeeper.email,
                'qr_code_path': shopkeeper.qr_code_path,
                'is_active': shopkeeper.is_active
            }
            
            return success_response(response_data, "Session retrieved successfully", 200)
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Get session error: {str(e)}", exc_info=True)
        return error_response(f"Failed to retrieve session: {str(e)}", 500)

@auth_bp.route('/refresh', methods=['POST'])
@require_auth
def refresh():
    """
    POST /api/auth/refresh
    
    Request Headers:
        Authorization: Bearer <token>
    
    Response:
        {
            "success": true,
            "data": {
                "session_token": "new-jwt-token",
                "expires_at": "ISO-8601-timestamp"
            }
        }
    """
    try:
        # Get current token from header
        auth_header = request.headers.get('Authorization')
        token = auth_header.split()[1]
        
        # Refresh token
        new_token = refresh_jwt_token(token)
        
        if not new_token:
            return error_response("Failed to refresh token", 401)
        
        from datetime import datetime, timedelta
        from utils.jwt_helper import JWT_EXPIRATION_HOURS
        
        expires_at = (datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)).isoformat()
        
        logger.info(f"Token refreshed for shop_id: {request.shop_id}")
        
        return success_response({
            "session_token": new_token,
            "expires_at": expires_at
        }, "Token refreshed successfully", 200)
        
    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}", exc_info=True)
        return error_response(f"Failed to refresh token: {str(e)}", 500)
