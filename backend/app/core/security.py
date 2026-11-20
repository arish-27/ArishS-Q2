from datetime import datetime, timedelta, timezone
from typing import Optional, Union, Any
from jose import jwt, JWTError
import bcrypt
from cryptography.fernet import Fernet
import base64
import hashlib
from app.core.config import settings

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies plaintext password against bcrypt hash directly."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8")[:72],
            hashed_password.encode("utf-8")
        )
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    """Computes bcrypt hash of plaintext password directly."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8")[:72], salt).decode("utf-8")

def create_access_token(subject: Union[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Generates signed JWT access token with expiration."""
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "iat": datetime.now(timezone.utc)
    }
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def decode_access_token(token: str) -> Optional[dict]:
    """Decodes and validates JWT token signature and expiry."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        return None

def _get_fernet() -> Fernet:
    """
    Derives deterministic 32-byte Fernet key from configured secret string.
    Ensures safe initialization even if string is arbitrary length.
    """
    key_bytes = settings.ENCRYPTION_SECRET_KEY.encode()
    digest = hashlib.sha256(key_bytes).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    return Fernet(fernet_key)

def encrypt_secret(plain_text: str) -> str:
    """Encrypts raw secret string using AES-256 Fernet."""
    if not plain_text:
        return ""
    f = _get_fernet()
    return f.encrypt(plain_text.encode("utf-8")).decode("utf-8")

def decrypt_secret(cipher_text: str) -> str:
    """Decrypts Fernet ciphertext to raw plaintext string."""
    if not cipher_text:
        return ""
    f = _get_fernet()
    return f.decrypt(cipher_text.encode("utf-8")).decode("utf-8")

def mask_secret(secret: str) -> str:
    """
    Returns masked representation for safe display (e.g. sk-•••••••••••••1a2b).
    Never exposes full key to client.
    """
    if not secret:
        return ""
    if len(secret) <= 8:
        return "••••" + secret[-2:]
    return secret[:4] + "••••••••••••" + secret[-4:]
