"""
Standardized API response builder
"""
from flask import jsonify
from typing import Any, Optional

def success_response(data: Any, message: str = "Success", status_code: int = 200):
    """
    Build success response
    
    Args:
        data: Response data
        message: Success message
        status_code: HTTP status code
    
    Returns:
        Flask JSON response
    """
    return jsonify({
        "success": True,
        "message": message,
        "data": data
    }), status_code

def error_response(message: str, status_code: int = 400, error_code: Optional[str] = None):
    """
    Build error response
    
    Args:
        message: Error message
        status_code: HTTP status code
        error_code: Optional error code for client handling
    
    Returns:
        Flask JSON response
    """
    response = {
        "success": False,
        "message": message
    }
    
    if error_code:
        response["error_code"] = error_code
    
    return jsonify(response), status_code
