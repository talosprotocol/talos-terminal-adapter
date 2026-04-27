"""
Terminal MCP Adapter - Cryptographic Utilities

Provides Ed25519 signing and verification using RFC 8785 JSON Canonicalization Scheme (JCS).
Used for securing communications with the Talos Governance Agent (TGA).
"""

from typing import Any, Dict, Union
import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def canonical_json(data: Dict[str, Any]) -> bytes:
    """Serialize a dictionary to canonical JSON (RFC 8785)."""
    return rfc8785.dumps(data)


def sign_json(data: Dict[str, Any], private_key: Union[bytes, Ed25519PrivateKey]) -> bytes:
    """Sign a dictionary using Ed25519 and RFC 8785 JCS.
    
    Args:
        data: The dictionary to sign (will be canonicalized)
        private_key: Ed25519 private key (bytes or object)
        
    Returns:
        64-byte Ed25519 signature
    """
    if isinstance(private_key, bytes):
        key = Ed25519PrivateKey.from_private_bytes(private_key)
    else:
        key = private_key
        
    message = canonical_json(data)
    return key.sign(message)


def verify_json_signature(
    data: Dict[str, Any], 
    signature: bytes, 
    public_key: Union[bytes, Ed25519PublicKey]
) -> bool:
    """Verify an Ed25519 signature for a canonicalized dictionary.
    
    Args:
        data: The dictionary that was signed
        signature: The 64-byte signature to verify
        public_key: Ed25519 public key (bytes or object)
        
    Returns:
        True if signature is valid, False otherwise
    """
    try:
        if isinstance(public_key, bytes):
            key = Ed25519PublicKey.from_public_bytes(public_key)
        else:
            key = public_key
            
        message = canonical_json(data)
        key.verify(signature, message)
        return True
    except Exception:
        return False


def generate_keypair() -> tuple[bytes, bytes]:
    """Generate a new Ed25519 key pair.
    
    Returns:
        tuple of (private_key_bytes, public_key_bytes)
    """
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    
    private_bytes = private_key.private_bytes(
        encoding=serialization_encoding_raw(),
        format=serialization_private_format_raw(),
        encryption_algorithm=serialization_no_encryption()
    )
    public_bytes = public_key.public_bytes(
        encoding=serialization_encoding_raw(),
        format=serialization_public_format_raw()
    )
    
    return private_bytes, public_bytes


# Helper imports for generation (to avoid pulling in too much by default)
def serialization_encoding_raw():
    from cryptography.hazmat.primitives import serialization
    return serialization.Encoding.Raw

def serialization_private_format_raw():
    from cryptography.hazmat.primitives import serialization
    return serialization.PrivateFormat.Raw

def serialization_public_format_raw():
    from cryptography.hazmat.primitives import serialization
    return serialization.PublicFormat.Raw

def serialization_no_encryption():
    from cryptography.hazmat.primitives import serialization
    return serialization.NoEncryption()
