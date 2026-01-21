"""
Request registry for tracking pending WebSocket requests.
"""

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class PendingRequest:
    """A pending request waiting for Illustrator response."""
    future: asyncio.Future
    script: str
    command: Optional[Dict[str, Any]] = None  # Command metadata for logging


class RequestRegistry:
    """
    Manages pending requests and their futures.
    Thread-safe implementation using a lock.
    """
    
    def __init__(self):
        self._pending: Dict[int, PendingRequest] = {}
        self._request_id = 0
        self._lock = threading.Lock()
        
    def create_request(self, loop: asyncio.AbstractEventLoop, script: str, command: Optional[Dict[str, Any]] = None) -> tuple[int, asyncio.Future]:
        """
        Create a new pending request.
        
        Args:
            loop: The event loop to attach the future to
            script: The script being executed
            command: Optional metadata
            
        Returns:
            Tuple of (request_id, future)
        """
        future = loop.create_future()
        
        with self._lock:
            self._request_id += 1
            request_id = self._request_id
            
            self._pending[request_id] = PendingRequest(
                future=future,
                script=script,
                command=command
            )
            
        return request_id, future
        
    def complete_request(self, request_id: int, result: Any) -> bool:
        """
        Complete a pending request with a result.
        
        Returns:
            True if request was found and completed, False otherwise.
        """
        with self._lock:
            pending = self._pending.pop(request_id, None)
            
        if pending and not pending.future.done():
            pending.future.set_result(result)
            return True
        return False
        
    def fail_request(self, request_id: int, error: Exception) -> bool:
        """
        Fail a pending request with an exception.
        
        Returns:
            True if request was found and failed, False otherwise.
        """
        with self._lock:
            pending = self._pending.pop(request_id, None)
            
        if pending and not pending.future.done():
            pending.future.set_exception(error)
            return True
        return False
        
    def cancel_all(self, reason: str = "Cancelled"):
        """Cancel all pending requests."""
        with self._lock:
            requests = list(self._pending.items())
            self._pending.clear()
            
        for req_id, pending in requests:
            if not pending.future.done():
                pending.future.set_exception(ConnectionError(reason))
                logger.debug(f"Cancelled request {req_id}: {reason}")
                
    def get_pending(self, request_id: int) -> Optional[PendingRequest]:
        """Get a pending request by ID."""
        with self._lock:
            return self._pending.get(request_id)
