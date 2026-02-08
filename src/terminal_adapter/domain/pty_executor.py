"""
Terminal MCP Adapter - Interactive Session Executor

Provides PTY-based command execution for interactive sessions,
supporting stdin writing and real-time output streaming.
"""

import os
import pty
import select
import signal
import asyncio
import logging
from typing import Dict, Any, Optional, List, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import uuid

logger = logging.getLogger("terminal-adapter.pty")


class SessionState(Enum):
    """State of an interactive session."""
    STARTING = "starting"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    ABORTED = "aborted"
    FAILED = "failed"


@dataclass
class InteractiveSession:
    """An interactive PTY session."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    pid: int = 0
    master_fd: int = -1
    created_at: datetime = field(default_factory=datetime.utcnow)
    state: SessionState = SessionState.STARTING
    command: str = ""
    args: List[str] = field(default_factory=list)
    cwd: str = ""
    exit_code: Optional[int] = None
    stdout_buffer: str = ""
    stderr_buffer: str = ""
    
    def is_alive(self) -> bool:
        """Check if the session process is still running."""
        if self.pid <= 0:
            return False
        try:
            os.kill(self.pid, 0)
            return True
        except ProcessLookupError:
            return False


class PTYExecutor:
    """PTY-based command executor for interactive sessions.
    
    Features:
    - Allocates a pseudo-terminal for each session
    - Supports stdin writing via write_input
    - Non-blocking output reading for streaming
    - Signal handling for abort
    """
    
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.sessions: Dict[str, InteractiveSession] = {}
        self._read_tasks: Dict[str, asyncio.Task] = {}
    
    async def start_session(
        self,
        command: str,
        args: List[str],
        cwd: str,
        env: Optional[Dict[str, str]] = None,
        on_output: Optional[Callable[[str, str], None]] = None
    ) -> InteractiveSession:
        """Start a new interactive PTY session.
        
        Args:
            command: Binary to execute
            args: Command arguments
            cwd: Working directory
            env: Environment overrides
            on_output: Callback for stdout chunks (session_id, chunk)
            
        Returns:
            InteractiveSession with master_fd for I/O
        """
        session = InteractiveSession(
            command=command,
            args=args,
            cwd=cwd,
        )
        
        # Build safe environment
        safe_env = {
            "PATH": os.getenv("PATH", "/usr/bin:/bin"),
            "HOME": os.getenv("HOME", "/tmp"),
            "LANG": "en_US.UTF-8",
            "TERM": "xterm-256color",
            "TALOS_SESSION_ID": session.session_id,
        }
        if env:
            dangerous = {"LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES"}
            for k, v in env.items():
                if k not in dangerous:
                    safe_env[k] = v
        
        # Fork with PTY
        pid, master_fd = pty.fork()
        
        if pid == 0:
            # Child process
            os.chdir(cwd)
            for k, v in safe_env.items():
                os.environ[k] = v
            os.execvp(command, [command] + args)
            # Should never reach here
            os._exit(1)
        else:
            # Parent process
            session.pid = pid
            session.master_fd = master_fd
            session.state = SessionState.RUNNING
            
            self.sessions[session.session_id] = session
            
            # Start background read task
            if on_output:
                task = asyncio.create_task(
                    self._read_output_loop(session, on_output)
                )
                self._read_tasks[session.session_id] = task
            
            logger.info(f"Started session {session.session_id}: {command} (pid={pid})")
            return session
    
    async def _read_output_loop(
        self,
        session: InteractiveSession,
        on_output: Callable[[str, str], None]
    ) -> None:
        """Background task to read PTY output and invoke callback."""
        loop = asyncio.get_event_loop()
        
        try:
            while session.is_alive():
                # Check for readable data
                readable, _, _ = select.select([session.master_fd], [], [], 0.1)
                
                if readable:
                    try:
                        chunk = os.read(session.master_fd, 4096)
                        if chunk:
                            text = chunk.decode("utf-8", errors="replace")
                            session.stdout_buffer += text
                            
                            # Run callback in event loop
                            await loop.run_in_executor(
                                None,
                                on_output,
                                session.session_id,
                                text
                            )
                    except OSError:
                        break
                
                await asyncio.sleep(0.01)
        except Exception as e:
            logger.error(f"Read loop error for {session.session_id}: {e}")
        finally:
            # Session ended
            await self._cleanup_session(session)
    
    async def write_input(self, session_id: str, data: str) -> bool:
        """Write stdin data to a running session.
        
        Args:
            session_id: Target session ID
            data: Data to write (include newlines if needed)
            
        Returns:
            True if written successfully
        """
        session = self.sessions.get(session_id)
        if not session or not session.is_alive():
            return False
        
        try:
            os.write(session.master_fd, data.encode("utf-8"))
            logger.debug(f"Wrote {len(data)} bytes to session {session_id}")
            return True
        except OSError as e:
            logger.error(f"Write error for {session_id}: {e}")
            return False
    
    async def abort_session(self, session_id: str, force: bool = False) -> bool:
        """Abort a running session.
        
        Args:
            session_id: Session to abort
            force: If True, send SIGKILL; otherwise SIGTERM
            
        Returns:
            True if signal was sent
        """
        session = self.sessions.get(session_id)
        if not session or not session.is_alive():
            return False
        
        sig = signal.SIGKILL if force else signal.SIGTERM
        
        try:
            os.kill(session.pid, sig)
            session.state = SessionState.ABORTED
            logger.info(f"Aborted session {session_id} with signal {sig.name}")
            return True
        except ProcessLookupError:
            return False
    
    async def get_session(self, session_id: str) -> Optional[InteractiveSession]:
        """Get a session by ID."""
        return self.sessions.get(session_id)
    
    async def list_sessions(self) -> List[Dict[str, Any]]:
        """List all sessions with their current state."""
        return [
            {
                "session_id": s.session_id,
                "command": s.command,
                "state": s.state.value,
                "created_at": s.created_at.isoformat(),
                "is_alive": s.is_alive(),
            }
            for s in self.sessions.values()
        ]
    
    async def read_output(self, session_id: str, timeout_ms: int = 5000) -> Tuple[str, bool]:
        """Read accumulated output from a session.
        
        Args:
            session_id: Session to read from
            timeout_ms: Max time to wait for output
            
        Returns:
            Tuple of (output, is_complete)
        """
        session = self.sessions.get(session_id)
        if not session:
            return "", True
        
        # Wait for output or completion
        start = asyncio.get_event_loop().time()
        timeout = timeout_ms / 1000
        
        while asyncio.get_event_loop().time() - start < timeout:
            if not session.is_alive():
                break
            if session.stdout_buffer:
                break
            await asyncio.sleep(0.05)
        
        # Get buffered output
        output = session.stdout_buffer
        session.stdout_buffer = ""
        
        return output, not session.is_alive()
    
    async def _cleanup_session(self, session: InteractiveSession) -> None:
        """Clean up a finished session."""
        # Get exit code
        try:
            _, status = os.waitpid(session.pid, os.WNOHANG)
            if os.WIFEXITED(status):
                session.exit_code = os.WEXITSTATUS(status)
            elif os.WIFSIGNALED(status):
                session.exit_code = -os.WTERMSIG(status)
        except ChildProcessError:
            pass
        
        # Close master FD
        if session.master_fd >= 0:
            try:
                os.close(session.master_fd)
            except OSError:
                pass
            session.master_fd = -1
        
        # Update state
        if session.state == SessionState.RUNNING:
            session.state = SessionState.COMPLETED
        
        logger.info(f"Session {session.session_id} completed with exit code {session.exit_code}")
    
    async def cleanup_all(self) -> None:
        """Clean up all sessions on shutdown."""
        for session_id in list(self.sessions.keys()):
            await self.abort_session(session_id, force=True)
        
        for task in self._read_tasks.values():
            task.cancel()
