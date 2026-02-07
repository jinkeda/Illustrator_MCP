"""
Request logging for Illustrator MCP.

Provides structured JSON-lines logging for debugging, analysis, and replay.
Logs are stored in the user's home directory under .illustrator-mcp/logs/.
"""

import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class RequestLog:
    """
    Structured request logger for MCP operations.
    
    Writes JSON-lines format for easy parsing:
    - One JSON object per line
    - Each entry includes timestamp, trace_id, script hash, result summary
    - Script content saved to separate file (on error or when verbose)
    """
    
    def __init__(self, log_dir: Optional[Path] = None, enabled: bool = True):
        """
        Initialize request logger.
        
        Args:
            log_dir: Directory for log files. Defaults to ~/.illustrator-mcp/logs/
            enabled: Whether logging is enabled
        """
        self.enabled = enabled
        self.log_dir = log_dir or Path.home() / ".illustrator-mcp" / "logs"
        self.scripts_dir = self.log_dir / "scripts"
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_file: Optional[Path] = None
        self.request_count = 0
        
        if self.enabled:
            self._init_session()
    
    def _init_session(self):
        """Create log directory and session file."""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self.scripts_dir.mkdir(parents=True, exist_ok=True)
            self.session_file = self.log_dir / f"session_{self.session_id}.jsonl"
            logger.info(f"Request logging enabled: {self.session_file}")
        except Exception as e:
            logger.warning(f"Failed to initialize request logging: {e}")
            self.enabled = False
    
    def log_request(
        self,
        trace_id: str,
        script: str,
        includes: Optional[List[str]] = None,
        result: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[float] = None,
        save_script: bool = False
    ) -> Optional[str]:
        """
        Log a request execution.
        
        Args:
            trace_id: Unique identifier for this request
            script: The JavaScript code executed
            includes: List of library includes
            result: Execution result dictionary
            duration_ms: Execution time in milliseconds
            save_script: Force save script content to file
            
        Returns:
            Entry ID if logged, None otherwise
        """
        if not self.enabled or not self.session_file:
            return None
        
        self.request_count += 1
        entry_id = f"{self.session_id}_{self.request_count:04d}"
        
        # Determine if we should save the script
        is_error = result and not result.get("ok", True)
        should_save_script = save_script or is_error
        
        # Compute script hash for deduplication/lookup
        script_hash = hashlib.md5(script.encode()).hexdigest()[:12]
        
        entry = {
            "entry_id": entry_id,
            "timestamp": datetime.now().isoformat(),
            "trace_id": trace_id,
            "script_hash": script_hash,
            "script_len": len(script),
            "includes": includes or [],
            "ok": result.get("ok") if result else None,
            "duration_ms": duration_ms,
        }
        
        # Add error info if failed
        if is_error:
            entry["error"] = {
                "code": result.get("error", {}).get("code") if isinstance(result.get("error"), dict) else None,
                "message": str(result.get("error", ""))[:500]  # Truncate long errors
            }
        
        # Add stats summary if available
        if result and "stats" in result:
            entry["stats"] = result["stats"]
        
        # Save script to file if needed
        if should_save_script:
            script_file = self.scripts_dir / f"{entry_id}_{script_hash}.jsx"
            try:
                script_file.write_text(script, encoding="utf-8")
                entry["script_file"] = script_file.name
            except Exception as e:
                logger.debug(f"Failed to save script: {e}")
        
        # Write entry to log file
        try:
            with open(self.session_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            return entry_id
        except Exception as e:
            logger.warning(f"Failed to write request log: {e}")
            return None
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get statistics for the current session."""
        return {
            "session_id": self.session_id,
            "request_count": self.request_count,
            "log_file": str(self.session_file) if self.session_file else None,
            "enabled": self.enabled
        }
    
    @classmethod
    def load_session(cls, session_file: Path) -> List[Dict[str, Any]]:
        """
        Load entries from a session log file.
        
        Args:
            session_file: Path to .jsonl session file
            
        Returns:
            List of log entries
        """
        entries = []
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries
    
    @classmethod
    def list_sessions(cls, log_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
        """
        List available session log files.
        
        Returns:
            List of session info dictionaries
        """
        log_dir = log_dir or Path.home() / ".illustrator-mcp" / "logs"
        sessions = []
        
        if not log_dir.exists():
            return sessions
        
        for f in sorted(log_dir.glob("session_*.jsonl"), reverse=True):
            stat = f.stat()
            sessions.append({
                "file": f.name,
                "path": str(f),
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
        
        return sessions


# Global logger instance
_request_log: Optional[RequestLog] = None


def get_request_log() -> RequestLog:
    """Get the global request log instance."""
    global _request_log
    if _request_log is None:
        _request_log = RequestLog()
    return _request_log


def log_request(
    trace_id: str,
    script: str,
    includes: Optional[List[str]] = None,
    result: Optional[Dict[str, Any]] = None,
    duration_ms: Optional[float] = None
) -> Optional[str]:
    """Convenience function to log a request."""
    return get_request_log().log_request(
        trace_id=trace_id,
        script=script,
        includes=includes,
        result=result,
        duration_ms=duration_ms
    )
