"""
Terminal MCP Adapter - TGA Client

Client for communicating with the Talos Governance Agent (TGA) for
HIGH_RISK command escalation and Supervisor approval flow.
"""

import os
import json
import hashlib
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum
from dataclasses import dataclass, asdict
import logging

import httpx

logger = logging.getLogger("terminal-adapter.tga")


class RiskLevel(str, Enum):
    """Risk classification matching TGA domain."""
    READ = "READ"
    WRITE = "WRITE"
    HIGH_RISK = "HIGH_RISK"


class SupervisorDecision(str, Enum):
    """Possible Supervisor decisions."""
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATE = "escalate"


@dataclass
class ActionRequest:
    """ActionRequest for TGA Supervisor approval.
    
    Based on talos-contracts/schemas/tga/v1/terminal_action_request.json
    """
    agent_id: str
    risk_level: RiskLevel
    intent: str
    resources: List[Dict[str, str]]
    proposal: Dict[str, Any]
    
    # Auto-generated
    trace_id: str = ""
    plan_id: str = ""
    action_request_id: str = ""
    ts: str = ""
    digest: str = ""
    signature: str = ""
    
    def __post_init__(self):
        if not self.action_request_id:
            self.action_request_id = str(uuid.uuid4())
        if not self.trace_id:
            self.trace_id = str(uuid.uuid4())
        if not self.plan_id:
            self.plan_id = str(uuid.uuid4())
        if not self.ts:
            self.ts = datetime.utcnow().isoformat() + "Z"
        if not self.digest:
            self.digest = self._compute_digest()
    
    def _compute_digest(self) -> str:
        """Compute SHA-256 digest of the proposal."""
        proposal_json = json.dumps(self.proposal, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(proposal_json.encode()).hexdigest()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "agent_id": self.agent_id,
            "trace_id": self.trace_id,
            "plan_id": self.plan_id,
            "action_request_id": self.action_request_id,
            "ts": self.ts,
            "risk_level": self.risk_level.value,
            "intent": self.intent,
            "resources": self.resources,
            "proposal": self.proposal,
            "digest": self.digest,
            "signature": self.signature,
        }


@dataclass
class SupervisorResponse:
    """Response from TGA Supervisor."""
    decision: SupervisorDecision
    action_request_id: str
    rationale: Optional[str] = None
    minted_capability: Optional[str] = None


class TGAClient:
    """Client for communicating with the Talos Governance Agent.
    
    Handles:
    - Building ActionRequests for terminal operations
    - Submitting HIGH_RISK commands for Supervisor approval
    - Processing Supervisor decisions
    """
    
    def __init__(
        self,
        tga_url: Optional[str] = None,
        agent_id: Optional[str] = None,
        timeout_seconds: int = 30
    ):
        self.tga_url = tga_url or os.getenv("TALOS_TGA_URL", "http://localhost:8080")
        self.agent_id = agent_id or os.getenv("TALOS_AGENT_ID", "did:key:anonymous")
        self.timeout = timeout_seconds
        self._client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()
    
    def build_action_request(
        self,
        command: str,
        args: List[str],
        cwd: str,
        risk_level: RiskLevel,
        intent: Optional[str] = None
    ) -> ActionRequest:
        """Build an ActionRequest for a terminal command.
        
        Args:
            command: Binary to execute
            args: Command arguments
            cwd: Working directory
            risk_level: Risk classification
            intent: Human-readable description (auto-generated if not provided)
            
        Returns:
            ActionRequest ready for Supervisor submission
        """
        # Auto-generate intent if not provided
        if not intent:
            full_cmd = f"{command} {' '.join(args)}".strip()
            intent = f"Execute terminal command: {full_cmd[:100]}"
        
        # Extract resources from command context
        resources = []
        resources.append({"type": "path", "value": cwd})
        
        # Check for file arguments that look like paths
        for arg in args:
            if arg.startswith("/") or arg.startswith("./"):
                resources.append({"type": "path", "value": arg})
        
        # Build proposal
        proposal = {
            "tool": "terminal:execute",
            "command": command,
            "args": args,
            "cwd": cwd,
        }
        
        return ActionRequest(
            agent_id=self.agent_id,
            risk_level=risk_level,
            intent=intent,
            resources=resources,
            proposal=proposal,
        )
    
    async def request_approval(self, action_request: ActionRequest) -> SupervisorResponse:
        """Submit an ActionRequest to TGA for Supervisor approval.
        
        This is a BLOCKING call that waits for Supervisor decision.
        For HIGH_RISK commands, the Supervisor may require human approval.
        
        Args:
            action_request: The action to approve
            
        Returns:
            SupervisorResponse with decision and optional capability
            
        Raises:
            TGAError: If communication with TGA fails
            TimeoutError: If Supervisor doesn't respond in time
        """
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        
        try:
            response = await self._client.post(
                f"{self.tga_url}/action-requests",
                json=action_request.to_dict(),
                headers={
                    "Content-Type": "application/json",
                    "X-Talos-Principal": self.agent_id,
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return SupervisorResponse(
                    decision=SupervisorDecision(data.get("decision", "rejected")),
                    action_request_id=action_request.action_request_id,
                    rationale=data.get("rationale"),
                    minted_capability=data.get("minted_capability"),
                )
            elif response.status_code == 403:
                return SupervisorResponse(
                    decision=SupervisorDecision.REJECTED,
                    action_request_id=action_request.action_request_id,
                    rationale=response.json().get("detail", "Rejected by policy"),
                )
            else:
                raise TGAError(f"TGA returned {response.status_code}: {response.text}")
                
        except httpx.TimeoutException:
            raise TimeoutError("Supervisor approval timed out")
        except httpx.RequestError as e:
            raise TGAError(f"Failed to communicate with TGA: {e}")
    
    async def check_capability(
        self,
        scope: str,
        command: str,
        risk_level: RiskLevel
    ) -> bool:
        """Check if the agent has a valid capability for the operation.
        
        Args:
            scope: Required capability scope (e.g., "terminal:write")
            command: Command being executed
            risk_level: Risk level of the command
            
        Returns:
            True if capability is valid, False otherwise
        """
        # For READ operations, allow without capability check in dev mode
        if risk_level == RiskLevel.READ:
            return True
        
        # In dev mode, allow all operations
        if os.getenv("TALOS_ENV") == "dev":
            logger.debug(f"Dev mode: bypassing capability check for {scope}")
            return True
        
        # TODO: Implement full capability validation against TGA
        # For now, return False for HIGH_RISK (requires escalation)
        return risk_level != RiskLevel.HIGH_RISK


class TGAError(Exception):
    """Error communicating with TGA."""
    pass
