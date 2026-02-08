"""Terminal Adapter Domain Package."""

from .classifier import (
    RiskLevel,
    PolicyManifest,
    CommandClassifier,
    ClassificationResult,
    TerminalAction,
    TerminalSession,
    COMMAND_RISK_MAP,
    COMMAND_BLOCKLIST,
)

from .session_manager import (
    SessionManager,
    WriteAheadLog,
    WALEntry,
)

from .tga_client import (
    TGAClient,
    ActionRequest,
    SupervisorResponse,
    SupervisorDecision,
    TGAError,
)

__all__ = [
    "RiskLevel",
    "PolicyManifest",
    "CommandClassifier",
    "ClassificationResult",
    "TerminalAction",
    "TerminalSession",
    "SessionManager",
    "WriteAheadLog",
    "WALEntry",
    "TGAClient",
    "ActionRequest",
    "SupervisorResponse",
    "SupervisorDecision",
    "TGAError",
    "COMMAND_RISK_MAP",
    "COMMAND_BLOCKLIST",
]
