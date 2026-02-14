"""
Retry and Backoff Utilities for Network Operations
Provides configurable retry logic with exponential backoff for all network operations
"""
import time
import logging
import random
from typing import Callable, Any, Optional, Tuple
from functools import wraps
import threading

logger = logging.getLogger(__name__)

class RetryConfig:
    """Configuration for retry behavior"""
    def __init__(self, 
                 max_attempts: int = 3,
                 base_delay: float = 1.0,
                 max_delay: float = 60.0,
                 exponential_base: float = 2.0,
                 jitter: bool = True,
                 backoff_multiplier: float = 1.0):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.backoff_multiplier = backoff_multiplier

# Default retry configurations for different operation types
DISCOVERY_RETRY_CONFIG = RetryConfig(max_attempts=3, base_delay=1.0, max_delay=10.0)
CONNECTIVITY_RETRY_CONFIG = RetryConfig(max_attempts=5, base_delay=2.0, max_delay=30.0)
PRINTING_RETRY_CONFIG = RetryConfig(max_attempts=3, base_delay=1.0, max_delay=15.0)
MONITORING_RETRY_CONFIG = RetryConfig(max_attempts=2, base_delay=5.0, max_delay=20.0)

def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """
    Calculate delay for retry attempt using exponential backoff with jitter
    
    Args:
        attempt: Current attempt number (0-based)
        config: Retry configuration
        
    Returns:
        Delay in seconds
    """
    if attempt <= 0:
        return 0.0
    
    # Calculate exponential backoff delay
    delay = config.base_delay * (config.exponential_base ** (attempt - 1))
    
    # Apply backoff multiplier
    delay *= config.backoff_multiplier
    
    # Cap at maximum delay
    delay = min(delay, config.max_delay)
    
    # Add jitter to prevent thundering herd
    if config.jitter:
        jitter_range = delay * 0.1  # 10% jitter
        delay += random.uniform(-jitter_range, jitter_range)
    
    return max(0.0, delay)

def retry_with_backoff(config: RetryConfig = None, 
                      exceptions: Tuple = (Exception,),
                      operation_name: str = "operation"):
    """
    Decorator for retry logic with exponential backoff
    
    Args:
        config: Retry configuration (uses default if None)
        exceptions: Tuple of exceptions to retry on
        operation_name: Name of operation for logging
    """
    if config is None:
        config = RetryConfig()
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(config.max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt < config.max_attempts - 1:
                        delay = calculate_delay(attempt + 1, config)
                        logger.warning(f"{operation_name} failed (attempt {attempt + 1}/{config.max_attempts}): {e}. Retrying in {delay:.2f}s...")
                        time.sleep(delay)
                    else:
                        logger.error(f"{operation_name} failed after {config.max_attempts} attempts: {e}")
                        raise e
            
            # This should never be reached, but just in case
            if last_exception:
                raise last_exception
                
        return wrapper
    return decorator

class NetworkOperationRetry:
    """
    Context manager for retry operations with detailed logging and metrics
    """
    
    def __init__(self, config: RetryConfig = None, operation_name: str = "network_operation"):
        self.config = config or RetryConfig()
        self.operation_name = operation_name
        self.attempts = 0
        self.start_time = None
        self.last_exception = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            duration = time.time() - self.start_time
            logger.info(f"{self.operation_name} succeeded after {self.attempts + 1} attempts in {duration:.2f}s")
        return False  # Don't suppress exceptions
    
    def execute(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with retry logic
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            Last exception if all attempts fail
        """
        for attempt in range(self.config.max_attempts):
            self.attempts = attempt
            try:
                return func(*args, **kwargs)
            except Exception as e:
                self.last_exception = e
                
                if attempt < self.config.max_attempts - 1:
                    delay = calculate_delay(attempt + 1, self.config)
                    logger.warning(f"{self.operation_name} failed (attempt {attempt + 1}/{self.config.max_attempts}): {e}. Retrying in {delay:.2f}s...")
                    time.sleep(delay)
                else:
                    duration = time.time() - self.start_time
                    logger.error(f"{self.operation_name} failed after {self.config.max_attempts} attempts in {duration:.2f}s: {e}")
                    raise e
        
        # This should never be reached
        if self.last_exception:
            raise self.last_exception

# Thread-safe retry metrics
class RetryMetrics:
    """Thread-safe metrics collection for retry operations"""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._metrics = {
            'total_operations': 0,
            'successful_operations': 0,
            'failed_operations': 0,
            'total_retries': 0,
            'average_attempts': 0.0
        }
    
    def record_operation(self, success: bool, attempts: int):
        """Record operation result"""
        with self._lock:
            self._metrics['total_operations'] += 1
            if success:
                self._metrics['successful_operations'] += 1
            else:
                self._metrics['failed_operations'] += 1
            
            if attempts > 1:
                self._metrics['total_retries'] += (attempts - 1)
            
            # Update average attempts
            total_ops = self._metrics['total_operations']
            total_attempts = self._metrics['total_retries'] + self._metrics['successful_operations']
            self._metrics['average_attempts'] = total_attempts / total_ops if total_ops > 0 else 0.0
    
    def get_metrics(self) -> dict:
        """Get current metrics"""
        with self._lock:
            return self._metrics.copy()
    
    def reset_metrics(self):
        """Reset all metrics"""
        with self._lock:
            self._metrics = {
                'total_operations': 0,
                'successful_operations': 0,
                'failed_operations': 0,
                'total_retries': 0,
                'average_attempts': 0.0
            }

# Global metrics instance
retry_metrics = RetryMetrics()

def get_retry_metrics() -> dict:
    """Get global retry metrics"""
    return retry_metrics.get_metrics()

def reset_retry_metrics():
    """Reset global retry metrics"""
    retry_metrics.reset_metrics()
