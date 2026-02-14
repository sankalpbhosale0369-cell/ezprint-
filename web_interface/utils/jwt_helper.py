"""
JWT token generation and validation for API authentication
"""
import jwt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import os

# Use centralized config for consistency
from shared import config as cfg
SECRET_KEY = cfg.SECRET_KEY
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 8  # 8-hour work shift

def generate_token(shop_id: str, username: str) -> str:
    """
    Generate JWT token for authenticated shopkeeper
    
    Args:
        shop_id: Unique shop identifier
        username: Shopkeeper username
    
    Returns:
        JWT token string
    """
    payload = {
        "shop_id": shop_id,
        "username": username,
        "iat": datetime.utcnow(),  # Issued at
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
    }
    
    token = jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token

def validate_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Validate JWT token and return payload
    
    Args:
        token: JWT token string
    
    Returns:
        Decoded payload if valid, None if invalid
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None  # Token expired
    except jwt.InvalidTokenError:
        return None  # Invalid token

def refresh_token(token: str) -> Optional[str]:
    """
    Refresh JWT token (extend expiration)
    
    Args:
        token: Current JWT token
    
    Returns:
        New JWT token if valid, None if invalid
    """
    payload = validate_token(token)
    if not payload:
        return None
    
    # Generate new token with same data but new expiration
    return generate_token(payload["shop_id"], payload["username"])
