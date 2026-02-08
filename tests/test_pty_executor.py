"""
Tests for PTYExecutor.
"""

import os
import pytest
import asyncio
from unittest.mock import MagicMock, patch
from terminal_adapter.domain.pty_executor import PTYExecutor, SessionState

@pytest.mark.asyncio
async def test_start_session():
    """Test starting a session."""
    executor = PTYExecutor(project_root="/tmp")
    
    # We can't easily test real PTYs in all environments, so we'll mock pty.fork
    with patch("pty.fork", return_value=(0, 1)):  # Child process
        with patch("os.execvp") as mock_exec:
            # This would be the child process path, but pty.fork returns 0 for child
            # In the test we actually want to test the parent path mostly
            pass

    # Let's test the parent path behaviors
    with patch("pty.fork", return_value=(12345, 10)):  # Parent process, pid 12345, fd 10
        session = await executor.start_session(
            command="echo",
            args=["hello"],
            cwd="/tmp"
        )
        
        assert session.pid == 12345
        assert session.master_fd == 10
        assert session.state == SessionState.RUNNING
        assert session.session_id in executor.sessions

@pytest.mark.asyncio
async def test_write_input():
    """Test writing input to a session."""
    executor = PTYExecutor(project_root="/tmp")
    
    # Mock session
    with patch("pty.fork", return_value=(12345, 10)):
        session = await executor.start_session("cat", [], "/tmp")
    
    with patch("os.write") as mock_write:
        await executor.write_input(session.session_id, "hello\n")
        mock_write.assert_called_with(10, b"hello\n")

@pytest.mark.asyncio
async def test_read_output():
    """Test reading output from a session."""
    executor = PTYExecutor(project_root="/tmp")
    
    # Mock session
    with patch("pty.fork", return_value=(12345, 10)):
        session = await executor.start_session("echo", ["hi"], "/tmp")
    
    # Simulate output
    session.stdout_buffer = "hello world\n"
    
    output, is_complete = await executor.read_output(session.session_id)
    assert output == "hello world\n"
    assert not is_complete  # It's still "alive" in our mock

@pytest.mark.asyncio
async def test_abort_session():
    """Test aborting a session."""
    executor = PTYExecutor(project_root="/tmp")
    
    with patch("pty.fork", return_value=(12345, 10)):
        session = await executor.start_session("sleep", ["100"], "/tmp")
        
    with patch("os.kill") as mock_kill:
        await executor.abort_session(session.session_id)
        mock_kill.assert_called()
        assert session.state == SessionState.ABORTED
