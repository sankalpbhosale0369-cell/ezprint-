"""
Authentication middleware for API endpoints
"""
from functools import wraps
from flask import request, jsonify
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.jwt_helper import validate_token

def require_auth(f):
    """
    Decorator to require JWT authentication for API endpoints
    
    Usage:
        @app.route('/api/protected')
        @require_auth
        def protected_route():
            shop_id = request.shop_id  # Injected by middleware
            username = request.username  # Injected by middleware
            return {"message": "Authenticated"}
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get Authorization header
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            return jsonify({
                "success": False,
                "message": "Missing Authorization header"
            }), 401
        
        # Extract token from "Bearer <token>"
        parts = auth_header.split()
        if len(parts) != 2 or parts[0] != 'Bearer':
            return jsonify({
                "success": False,
                "message": "Invalid Authorization header format. Use: Bearer <token>"
            }), 401
        
        token = parts[1]
        
        # Validate token
        payload = validate_token(token)
        if not payload:
            return jsonify({
                "success": False,
                "message": "Invalid or expired token"
            }), 401
        
        # Inject shop_id and username into request context
        request.shop_id = payload["shop_id"]
        request.username = payload["username"]
        
        return f(*args, **kwargs)
    
    return decorated_function
