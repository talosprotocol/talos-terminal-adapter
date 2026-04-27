import pytest
import os
import json
from unittest.mock import MagicMock, patch, AsyncMock

from terminal_adapter.main import app, state, load_supervisor_key
from terminal_adapter.domain import (
    RiskLevel, 
    PolicyManifest, 
    TGAClient
)
from terminal_adapter.domain.crypto import sign_json, generate_keypair
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

@pytest.fixture
def keys():
    private_bytes, public_bytes = generate_keypair()
    return private_bytes, public_bytes

@pytest.fixture
def pem_public_key(keys):
    _, public_bytes = keys
    pub_key = ed25519.Ed25519PublicKey.from_public_bytes(public_bytes)
    return pub_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()

def test_load_supervisor_key(pem_public_key, keys):
    _, public_bytes = keys
    with patch.dict(os.environ, {"TGA_SUPERVISOR_PUBLIC_KEY": pem_public_key}):
        loaded_key = load_supervisor_key()
        assert loaded_key == public_bytes

def test_policy_manifest_verification(keys):
    private_key, public_key = keys
    
    manifest_data = {
        "version": "1.0",
        "safe_commands": ["ls", "pwd"],
        "write_commands": ["touch"],
        "blocked_patterns": ["rm -rf /"],
    }
    
    signature = sign_json(manifest_data, private_key).hex()
    
    manifest = PolicyManifest(
        version=manifest_data["version"],
        safe_commands=manifest_data["safe_commands"],
        write_commands=manifest_data["write_commands"],
        blocked_patterns=manifest_data["blocked_patterns"],
        signature=signature
    )
    
    # Success case
    assert manifest.verify_signature(public_key) is True
    
    # Failure case (wrong key)
    _, other_public = generate_keypair()
    assert manifest.verify_signature(other_public) is False
    
    # Failure case (tampered data)
    manifest.safe_commands.append("rm")
    assert manifest.verify_signature(public_key) is False

@pytest.mark.asyncio
async def test_check_capability_hardening(keys):
    _, public_key = keys
    client = TGAClient(supervisor_public_key=public_key)
    
    # READ should always pass
    assert await client.check_capability("scope", "ls", RiskLevel.READ) is True
    
    # WRITE/HIGH_RISK without token should fail
    assert await client.check_capability("scope", "touch", RiskLevel.WRITE) is False
    assert await client.check_capability("scope", "rm", RiskLevel.HIGH_RISK) is False
    
    # WRITE with valid token should pass
    capability_data = {"scope": "terminal:write", "command": "touch"}
    private_key, _ = keys
    sig = sign_json(capability_data, private_key).hex()
    token = json.dumps({"data": capability_data, "signature": sig})
    
    assert await client.check_capability("scope", "touch", RiskLevel.WRITE, token) is True

@pytest.mark.asyncio
async def test_anchor_to_audit(keys):
    # Mocking httpx.AsyncClient.post
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = MagicMock(status_code=201)
        
        # We need to trigger the anchor_to_audit callback.
        # It's defined inside lifespan in main.py, but we can test it by
        # manually calling it if we can access it, or by triggering it through session manager.
        
        from terminal_adapter.main import lifespan
        
        # Setup state
        state.supervisor_public_key = keys[1]
        
        async with lifespan(app):
            # Trigger anchoring through session manager
            session_id = "test-session"
            merkle_root = "test-root-hash"
            
            # Manually call the callback if we can't easily trigger it
            # The callback is passed to SessionManager in lifespan
            callback = state.session_manager.anchor_callback
            await callback(session_id, merkle_root)
            
            assert mock_post.called
            args, kwargs = mock_post.call_args
            assert "/events" in args[0]
            payload = kwargs["json"]
            assert payload["schema_id"] == "talos.audit_event"
            assert payload["meta"]["session_id"] == session_id
            assert payload["hashes"]["merkle_root"] == merkle_root
            assert "event_hash" in payload

def test_paranoid_mode_activation(pem_public_key, keys):
    private_key, public_key = keys
    
    # Create an invalid manifest (no signature)
    manifest_path = "test_manifest.json"
    manifest_data = {
        "version": "1.0",
        "safe_commands": ["ls"],
        "write_commands": [],
        "blocked_patterns": [],
        "signature": "invalid"
    }
    with open(manifest_path, "w") as f:
        json.dump(manifest_data, f)
        
    try:
        with patch.dict(os.environ, {
            "TGA_SUPERVISOR_PUBLIC_KEY": pem_public_key,
            "TALOS_POLICY_MANIFEST": manifest_path
        }):
            # We can't easily restart the app in the same process with different lifespan
            # But we can test the logic inside lifespan
            state.supervisor_public_key = load_supervisor_key()
            state.paranoid_mode = False
            
            manifest = PolicyManifest.load(manifest_path)
            if not manifest.verify_signature(state.supervisor_public_key):
                state.paranoid_mode = True
                
            assert state.paranoid_mode is True
    finally:
        if os.path.exists(manifest_path):
            os.remove(manifest_path)
