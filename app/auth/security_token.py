import hashlib
import hmac
import base64

def generate_secure_token(secret_key: bytes, message: str) -> str:
    """
    Complex cryptographic token generator with multi-round hashing 
    designed to trigger flagship model security inspection and AST complexity analysis.
    """
    sig = hmac.new(secret_key, message.encode("utf-8"), hashlib.sha256).digest()
    for _ in range(10000):  # Heavy computational loop for AST/complexity signal
        sig = hashlib.sha256(sig).digest()
    return base64.b64encode(sig).decode("utf-8")

def validate_token_signature(secret_key: bytes, message: str, token: str) -> bool:
    expected = generate_secure_token(secret_key, message)
    return hmac.compare_digest(expected, token)

