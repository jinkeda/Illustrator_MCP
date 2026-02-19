"""
Request registry for tracking pending WebSocket requests.
"""

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, AsyncIterator

logger = logging.getLogger(__name__)


@dataclass
class PendingRequest:
    """A pending request waiting for Illustrator response."""
    future: asyncio.Future
    script: str
    command: Optional[Dict[str, Any]] = None  # Command metadata for logging
    trace_id: Optional[str] = None  # Trace ID for request correlation


@dataclass
class StreamingRequest:
    """A streaming request that receives multiple updates before completion.
    
    Completion is signaled via a sentinel message {type: "complete"} in the queue.
    No separate `completed` flag — single-channel truth prevents race conditions.
    """
    queue: asyncio.Queue
    script: str
    command: Optional[Dict[str, Any]] = None
    trace_id: Optional[str] = None


class RequestRegistry:
    """
    Manages pending requests and their futures.
    Thread-safe implementation using a lock.
    Supports both single-response and streaming requests.
    """
    
    def __init__(self):
        self._pending: Dict[int, PendingRequest] = {}
        self._streaming: Dict[int, StreamingRequest] = {}
        self._request_id = 0
        self._lock = threading.Lock()
        
    def create_request(
        self,
        loop: asyncio.AbstractEventLoop,
        script: str,
        command: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None
    ) -> tuple[int, asyncio.Future]:
        """
        Create a new pending request.
        
        Args:
            loop: The event loop to attach the future to.
            script: The script being executed.
            command: Optional command metadata.
            trace_id: Optional trace ID for request correlation.
            
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
                command=command,
                trace_id=trace_id
            )
            
        return request_id, future
    
    def create_streaming_request(
        self,
        loop: asyncio.AbstractEventLoop,
        script: str,
        command: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None
    ) -> tuple[int, asyncio.Queue]:
        """
        Create a streaming request that receives multiple updates.
        
        Args:
            loop: The event loop for the queue.
            script: The script being executed.
            command: Optional command metadata.
            trace_id: Optional trace ID.
            
        Returns:
            Tuple of (request_id, queue for updates)
        """
        queue = asyncio.Queue(maxsize=1000)  # Prevent unbounded memory growth
        
        with self._lock:
            self._request_id += 1
            request_id = self._request_id
            
            self._streaming[request_id] = StreamingRequest(
                queue=queue,
                script=script,
                command=command,
                trace_id=trace_id
            )
            
        return request_id, queue
    
    def push_update(self, request_id: int, update: Dict[str, Any]) -> bool:
        """
        Push an update to a streaming request.
        
        Thread-safe: the lock protects both lookup and queue put.
        
        Args:
            request_id: The streaming request ID.
            update: Update data to push.
            
        Returns:
            True if update was pushed, False if request not found.
        """
        with self._lock:
            streaming = self._streaming.get(request_id)
            if streaming:
                try:
                    streaming.queue.put_nowait(update)
                    return True
                except asyncio.QueueFull:
                    logger.warning(f"Streaming queue full for request {request_id}")
        return False
    
    def complete_streaming(self, request_id: int, final_result: Dict[str, Any]) -> bool:
        """
        Complete a streaming request with final result.
        
        Thread-safe: sends a sentinel message {type: "complete"} through the queue.
        The consumer (stream_updates) detects the sentinel and cleans up.
        
        Does NOT remove from _streaming here — the queue reference must remain
        accessible for consumers that start after complete_streaming is called.
        Cleanup is handled by stream_updates (on consumption) and cancel_all
        (on disconnect).
        
        Args:
            request_id: The streaming request ID.
            final_result: Final result data.
            
        Returns:
            True if sentinel was sent, False if not found or already completed.
        """
        # Coerce request_id to int for safety — JSON may return str
        try:
            request_id = int(request_id)
        except (TypeError, ValueError):
            logger.warning(f"Non-integer request_id in streaming: {request_id!r}")
            return False

        with self._lock:
            streaming = self._streaming.get(request_id)
            if streaming:
                if getattr(streaming, '_completed', False):
                    return False
                final_result["type"] = "complete"
                try:
                    streaming.queue.put_nowait(final_result)
                    streaming._completed = True
                    return True
                except asyncio.QueueFull:
                    logger.warning(f"Streaming queue full on complete for request {request_id}")
        return False
    
    async def stream_updates(
        self, 
        request_id: int, 
        timeout: float = 300.0
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Async iterator for streaming request updates.
        
        Driven entirely by queue messages (single-channel truth).
        Exits when a sentinel {type: "complete"} is received.
        No flag checking — eliminates the race between flag set and queue read.
        
        Handles cleanup: removes the streaming request from _streaming when
        the consumer exits (normal completion, timeout, or error).
        
        Args:
            request_id: The streaming request ID.
            timeout: Timeout for each update.
            
        Yields:
            Update dictionaries until completion sentinel.
        """
        with self._lock:
            streaming = self._streaming.get(request_id)
            
        if not streaming:
            return
        
        try:
            while True:
                try:
                    update = await asyncio.wait_for(
                        streaming.queue.get(), 
                        timeout=timeout
                    )
                    yield update
                    
                    if update.get("type") == "complete":
                        break
                        
                except asyncio.TimeoutError:
                    yield {"type": "timeout", "error": f"No update received in {timeout}s"}
                    break
        finally:
            # Clean up streaming request
            with self._lock:
                self._streaming.pop(request_id, None)
        
    def complete_request(self, request_id: int, result: Any) -> bool:
        """
        Complete a pending request with a result.
        
        Always-pop semantics: the pending entry is removed under lock
        regardless of whether set_result succeeds. This prevents both
        pop-on-failure inconsistency and leak-on-failure.
        
        Validates response shape: must contain 'result' or 'error' key.
        Malformed responses are wrapped as C_PROTOCOL error.
        """
        # Coerce request_id to int for safety — JSON may return str
        try:
            request_id = int(request_id)
        except (TypeError, ValueError):
            logger.warning(f"Non-integer request_id: {request_id!r}")
            return False

        with self._lock:
            pending = self._pending.pop(request_id, None)

        if not pending:
            logger.warning(f"complete_request for unknown ID: {request_id}")
            return False

        if pending.future.done():
            logger.debug(f"Request {request_id} already resolved, ignoring late result")
            return False

        # Validate response shape
        if isinstance(result, dict) and not (
            "result" in result or "error" in result
        ):
            from illustrator_mcp.errors import ErrorCode, format_code
            logger.warning(
                format_code(ErrorCode.C_PROTOCOL,
                    f"Request {request_id}: missing 'result'/'error'. "
                    f"Keys: {list(result.keys())}"))
            result = {
                "error": format_code(ErrorCode.C_PROTOCOL,
                    f"Response missing required 'result' or 'error' key. "
                    f"Got: {list(result.keys())}")
            }

        try:
            pending.future.set_result(result)
            return True
        except Exception:
            logger.warning(f"Failed to set result for request {request_id}")
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
            
            # Also cancel streaming requests via sentinel
            for req_id, streaming in self._streaming.items():
                try:
                    streaming.queue.put_nowait({"type": "complete", "cancelled": True, "reason": reason})
                except asyncio.QueueFull:
                    pass
            self._streaming.clear()
            
        for req_id, pending in requests:
            if not pending.future.done():
                pending.future.set_exception(ConnectionError(reason))
                logger.debug(f"Cancelled request {req_id}: {reason}")
                
    def get_pending(self, request_id: int) -> Optional[PendingRequest]:
        """Get a pending request by ID."""
        with self._lock:
            return self._pending.get(request_id)
    
    def is_streaming(self, request_id: int) -> bool:
        """Check if a request ID is a streaming request."""
        with self._lock:
            return request_id in self._streaming

    @property
    def pending_count(self) -> int:
        """Number of pending (non-streaming) requests — for monitoring."""
        with self._lock:
            return len(self._pending)

    @property
    def streaming_count(self) -> int:
        """Number of active streaming requests — for monitoring."""
        with self._lock:
            return len(self._streaming)

