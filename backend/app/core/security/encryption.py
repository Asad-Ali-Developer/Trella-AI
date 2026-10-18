import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import settings


class TokenEncryption:
    """Fernet authenticated encryption with MultiFernet key rotation."""

    def __init__(
        self,
        primary_key: str | None = None,
        fallback_keys: list[str] | None = None,
    ) -> None:
        key_str = primary_key or settings.ENCRYPTION_KEY
        primary_fernet = self._create_fernet(key_str)
        all_fernets = [primary_fernet]

        resolved_fallbacks = (
            fallback_keys if fallback_keys is not None else settings.encryption_fallback_keys
        )
        for fb_key in resolved_fallbacks:
            all_fernets.append(self._create_fernet(fb_key))

        self.cipher = MultiFernet(all_fernets)

    @staticmethod
    def _create_fernet(key: str) -> Fernet:
        """Validate or derive a valid 32-byte urlsafe base64 Fernet key."""
        key_bytes = key.encode("utf-8")
        try:
            return Fernet(key_bytes)
        except Exception:
            derived_32 = hashlib.sha256(key_bytes).digest()
            urlsafe_key = base64.urlsafe_b64encode(derived_32)
            return Fernet(urlsafe_key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext into URL-safe base64 ciphertext."""
        return self.cipher.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt ciphertext back into plaintext string."""
        try:
            return self.cipher.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Decryption failed: invalid or corrupt token.") from exc

    def rotate(self, ciphertext: str) -> str:
        """Re-encrypt ciphertext with the latest primary key."""
        return self.cipher.rotate(ciphertext.encode("utf-8")).decode("utf-8")


encryption = TokenEncryption()
