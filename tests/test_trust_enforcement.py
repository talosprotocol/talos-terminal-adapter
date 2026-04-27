import pytest
import json
from terminal_adapter.domain.classifier import PolicyManifest, RiskLevel
from terminal_adapter.domain.tga_client import TGAClient, ActionRequest
from terminal_adapter.domain.crypto import generate_keypair, sign_json, verify_json_signature


@pytest.fixture
def keys():
    """Generate a test keypair."""
    priv, pub = generate_keypair()
    return priv, pub


def test_crypto_jcs_signatures(keys):
    """Test that Ed25519 + JCS signatures work correctly."""
    priv, pub = keys
    data = {"a": 1, "b": [1, 2, 3], "c": {"d": "e"}}
    
    # Sign
    signature = sign_json(data, priv)
    assert len(signature) == 64
    
    # Verify
    assert verify_json_signature(data, signature, pub) is True
    
    # Tamper
    tampered_data = data.copy()
    tampered_data["a"] = 2
    assert verify_json_signature(tampered_data, signature, pub) is False


def test_policy_manifest_verification(keys):
    """Test PolicyManifest signature verification."""
    priv, pub = keys
    
    manifest_data = {
        "version": "1.0",
        "safe_commands": ["ls", "pwd"],
        "write_commands": ["mkdir", "touch"],
        "blocked_patterns": ["rm -rf /"]
    }
    
    # Generate signature for the manifest
    sig = sign_json(manifest_data, priv)
    
    manifest = PolicyManifest(
        version=manifest_data["version"],
        safe_commands=manifest_data["safe_commands"],
        write_commands=manifest_data["write_commands"],
        blocked_patterns=manifest_data["blocked_patterns"],
        signature=sig.hex()
    )
    
    # Should verify with correct public key
    assert manifest.verify_signature(pub) is True
    
    # Should fail with wrong key
    priv2, pub2 = generate_keypair()
    assert manifest.verify_signature(pub2) is False


def test_action_request_signing(keys):
    """Test that ActionRequest signs itself correctly."""
    priv, pub = keys
    
    req = ActionRequest(
        agent_id="did:key:test",
        risk_level=RiskLevel.HIGH_RISK,
        intent="Test command",
        resources=[{"type": "path", "value": "/tmp"}],
        proposal={"tool": "terminal:execute", "command": "rm", "args": ["-rf", "test"]}
    )
    
    # Sign it
    signature_hex = req.sign(priv)
    assert len(bytes.fromhex(signature_hex)) == 64
    assert req.signature == signature_hex
    
    # Verify the signature manually to ensure it's correct
    data = req.to_dict()
    sig_bytes = bytes.fromhex(data.pop("signature"))
    assert verify_json_signature(data, sig_bytes, pub) is True


@pytest.mark.asyncio
async def test_tga_client_capability_verification(keys):
    """Test TGAClient capability token verification."""
    priv, pub = keys
    
    client = TGAClient(supervisor_public_key=pub)
    
    # 1. Test HIGH_RISK without token (should fail)
    assert await client.check_capability("terminal:write", "rm", RiskLevel.HIGH_RISK) is False
    
    # 2. Test with valid signed token
    cap_inner_data = {
        "scope": "terminal:write",
        "agent_id": "did:key:test",
        "expires_at": "2030-01-01T00:00:00Z"
    }
    sig = sign_json(cap_inner_data, priv)
    
    capability_token = json.dumps({
        "data": cap_inner_data,
        "signature": sig.hex()
    })
    
    assert await client.check_capability(
        "terminal:write", 
        "rm", 
        RiskLevel.HIGH_RISK, 
        capability_token=capability_token
    ) is True
    
    # 3. Test with tampered token
    tampered_inner = cap_inner_data.copy()
    tampered_inner["scope"] = "admin:*"
    tampered_token = json.dumps({
        "data": tampered_inner,
        "signature": sig.hex()
    })
    
    assert await client.check_capability(
        "terminal:write", 
        "rm", 
        RiskLevel.HIGH_RISK, 
        capability_token=tampered_token
    ) is False


def test_action_request_digest():
    """Test that ActionRequest compute_digest uses JCS."""
    proposal = {"z": 1, "a": 2}
    
    req = ActionRequest(
        agent_id="test",
        risk_level=RiskLevel.READ,
        intent="test",
        resources=[],
        proposal=proposal
    )
    
    # Manual digest computation with JCS
    import rfc8785
    import hashlib
    expected_jcs = rfc8785.dumps(proposal)
    expected_digest = hashlib.sha256(expected_jcs).hexdigest()
    
    assert req.digest == expected_digest
