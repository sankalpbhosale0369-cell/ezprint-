"""
API Client for Desktop Application
Handles communication with backend REST APIs with graceful fallback to database
"""
import requests
import logging
from typing import Optional, Dict, Any, Tuple
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import EZPRINT_BASE_URL

# Setup logging
logger = logging.getLogger(__name__)

class ApiClient:
    """
    API Client for desktop application
    
    Features:
    - Automatic JWT token attachment
    - Graceful fallback to database on API failures
    - Request timeout handling
    - Error logging
    """
    
    def __init__(self, base_url: str = None, session_token: str = None):
        """
        Initialize API client
        
        Args:
            base_url: Backend base URL (defaults to EZPRINT_BASE_URL from config)
            session_token: JWT session token (optional, can be set later)
        """
        self.base_url = base_url or EZPRINT_BASE_URL
        self.session_token = session_token
        self.timeout = 5  # 5 second timeout for API requests
        
        logger.info(f"ApiClient initialized with base_url: {self.base_url}")
    
    def set_session_token(self, token: str):
        """
        Set JWT session token for authenticated requests
        
        Args:
            token: JWT session token
        """
        self.session_token = token
        logger.info("Session token set for API client")
    
    def _get_headers(self) -> Dict[str, str]:
        """
        Build request headers with authentication if available
        
        Returns:
            Dictionary of HTTP headers
        """
        headers = {
            'Content-Type': 'application/json'
        }
        
        if self.session_token:
            headers['Authorization'] = f'Bearer {self.session_token}'
        
        return headers
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Make HTTP request to backend API
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (e.g., '/api/auth/login')
            **kwargs: Additional arguments for requests library
        
        Returns:
            Tuple of (success, data, error_message)
            - success: True if API call succeeded, False otherwise
            - data: Response data if success, None otherwise
            - error_message: Error message if failed, None otherwise
        """
        url = f"{self.base_url}{endpoint}"
        
        # Add default headers
        if 'headers' not in kwargs:
            kwargs['headers'] = self._get_headers()
        else:
            kwargs['headers'].update(self._get_headers())
        
        # Add default timeout
        if 'timeout' not in kwargs:
            kwargs['timeout'] = self.timeout
        
        try:
            logger.debug(f"API Request: {method} {url}")
            
            response = requests.request(method, url, **kwargs)
            
            # Check if response is successful
            if response.status_code >= 200 and response.status_code < 300:
                data = response.json()
                
                # Check if response has success field
                if 'success' in data and not data['success']:
                    error_msg = data.get('message', 'API request failed')
                    logger.warning(f"API request failed: {error_msg}")
                    return False, None, error_msg
                
                logger.debug(f"API Response: {response.status_code} - Success")
                return True, data.get('data'), None
            else:
                # Non-2xx status code
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message', f'HTTP {response.status_code}')
                except:
                    error_msg = f'HTTP {response.status_code}'
                
                logger.warning(f"API request failed: {error_msg}")
                return False, None, error_msg
                
        except requests.exceptions.Timeout:
            error_msg = "API request timeout"
            logger.warning(f"{error_msg}: {url}")
            return False, None, error_msg
        
        except requests.exceptions.ConnectionError:
            error_msg = "Cannot connect to backend API"
            logger.warning(f"{error_msg}: {url}")
            return False, None, error_msg
        
        except Exception as e:
            error_msg = f"API request error: {str(e)}"
            logger.error(f"{error_msg}: {url}", exc_info=True)
            return False, None, error_msg
    
    # ========== Authentication APIs ==========
    
    def login(self, username: str, password: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Login to backend API
        
        Args:
            username: Username or email
            password: Password
        
        Returns:
            Tuple of (success, data, error_message)
            data contains: shop_id, username, shop_name, session_token, etc.
        """
        endpoint = '/api/auth/login'
        payload = {
            'username': username,
            'password': password
        }
        
        success, data, error = self._make_request('POST', endpoint, json=payload)
        
        if success and data:
            # Automatically set session token
            if 'session_token' in data:
                self.set_session_token(data['session_token'])
                logger.info(f"Login successful for user: {username}")
        
        return success, data, error
    
    def get_session(self) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Get current session information
        
        Returns:
            Tuple of (success, data, error_message)
            data contains: shop_id, username, shop_name, etc.
        """
        endpoint = '/api/auth/session'
        return self._make_request('GET', endpoint)
    
    def refresh_token(self) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Refresh JWT session token
        
        Returns:
            Tuple of (success, data, error_message)
            data contains: session_token, expires_at
        """
        endpoint = '/api/auth/refresh'
        success, data, error = self._make_request('POST', endpoint)
        
        if success and data and 'session_token' in data:
            self.set_session_token(data['session_token'])
            logger.info("Session token refreshed")
        
    def logout(self) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Logout from backend API (invalidates session)
        
        Returns:
            Tuple of (success, data, error_message)
        """
        endpoint = '/api/auth/logout'
        success, data, error = self._make_request('POST', endpoint)
        
        if success:
            self.session_token = None
            logger.info("API logout successful")
            
        return success, data, error

    def refresh_token(self) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Refresh JWT session token
        
        Returns:
            Tuple of (success, data, error_message)
        """
        endpoint = '/api/auth/refresh'
        success, data, error = self._make_request('POST', endpoint)
        
        if success and data and 'session_token' in data:
            self.set_session_token(data['session_token'])
            logger.info("Token refreshed successfully")
            
        return success, data, error
    
    # ========== Dashboard APIs ==========
    
    def get_dashboard(self, shop_id: str, period: str = 'today', limit: int = 50, offset: int = 0, status: str = None) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Get dashboard data (KPIs + job list)
        
        Args:
            shop_id: Shop ID
            period: 'today', 'week', or 'month'
            limit: Number of jobs to fetch (max 200)
            offset: Pagination offset
            status: Optional status filter ('pending', 'completed', 'failed')
        
        Returns:
            Tuple of (success, data, error_message)
            data contains: kpis (dict), jobs (list), total_count, limit, offset
        """
        endpoint = f'/api/shop/{shop_id}/dashboard'
        params = {
            'period': period,
            'limit': limit,
            'offset': offset
        }
        
        if status:
            params['status'] = status
        
        return self._make_request('GET', endpoint, params=params)
    
    # ========== Config APIs ==========
    
    def get_config(self, shop_id: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Get full shop configuration
        
        Args:
            shop_id: Shop ID
        
        Returns:
            Tuple of (success, data, error_message)
            data contains: shop_info (dict), pricing (dict), printers (list)
        """
        endpoint = f'/api/shop/{shop_id}/config'
        return self._make_request('GET', endpoint)
    
    def get_pricing(self, shop_id: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Get pricing configuration
        
        Args:
            shop_id: Shop ID
        
        Returns:
            Tuple of (success, data, error_message)
            data contains: shop_id, bw_single, bw_double, color_single, color_double
        """
        endpoint = f'/api/shop/{shop_id}/pricing'
        return self._make_request('GET', endpoint)
    
    def update_pricing(self, shop_id: str, pricing: Dict[str, float]) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Update pricing configuration
        
        Args:
            shop_id: Shop ID
            pricing: Dictionary with pricing values (bw_single, bw_double, color_single, color_double)
        
        Returns:
            Tuple of (success, data, error_message)
            data contains: updated pricing values
        """
        endpoint = f'/api/shop/{shop_id}/pricing'
        return self._make_request('PUT', endpoint, json=pricing)
