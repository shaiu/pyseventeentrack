"""Define tests for encryption utilities."""

import pytest

from pyseventeentrack import encrypt


def test_rsa_encrypt_invalid_key(monkeypatch):
    """Test rsa_encrypt raises when key is not RSA."""

    class DummyKey:
        """Non-RSA key placeholder."""

    def fake_load_pem_public_key(*_args, **_kwargs):
        return DummyKey()

    monkeypatch.setattr(
        encrypt.serialization, "load_pem_public_key", fake_load_pem_public_key
    )

    with pytest.raises(TypeError):
        encrypt.rsa_encrypt("password")
