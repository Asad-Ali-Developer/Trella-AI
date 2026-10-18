import pytest

from app.core.security.encryption import TokenEncryption


def test_encryption_roundtrip() -> None:
    enc = TokenEncryption()
    secret = "my_super_secret_trello_token_12345"
    ciphertext = enc.encrypt(secret)
    assert ciphertext != secret
    decrypted = enc.decrypt(ciphertext)
    assert decrypted == secret


def test_encryption_invalid_token() -> None:
    enc = TokenEncryption()
    with pytest.raises(ValueError, match="Decryption failed"):
        enc.decrypt("invalid_token_xyz")


def test_encryption_key_rotation() -> None:
    old_key = "old_secret_key_rotation_test_1"
    new_key = "new_secret_key_rotation_test_2"

    enc_old = TokenEncryption(primary_key=old_key)
    ciphertext_old = enc_old.encrypt("rotate_me_please")

    # New encryption instance with new primary key and old key as fallback
    enc_new = TokenEncryption(primary_key=new_key, fallback_keys=[old_key])
    # Can decrypt old ciphertext
    assert enc_new.decrypt(ciphertext_old) == "rotate_me_please"

    # Rotate ciphertext to new key
    ciphertext_new = enc_new.rotate(ciphertext_old)
    assert ciphertext_new != ciphertext_old
    assert enc_new.decrypt(ciphertext_new) == "rotate_me_please"
