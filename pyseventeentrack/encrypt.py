"""This module handles the RSA encryption for the 17track API."""

import base64
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

PUBLIC_KEY_PEM = """
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0Y5iQN3VNofXPtZXYZe9
75ojD+Gb+yPBrlrKj2t4XvYHE+pYmFzGPTvDmB3t1OfHujdgBVc3VJBSFsHezm4kz
4iqIChHLKeFvuux+i/Uq+zo1QdC72qteUMHF925qPLe3xU/QJj6BFR9mA4VrUwXt8
eWI58ozizBH31PclxiPNT+yYYXRUV3QJvbZ+FJGL3gYUu1k44WILQzDZfBJMRf+My
LHZew6+XtYB8E2+PXc/R7TtLPcMDsPvARrAJMhu5b+yfwJM1zOFChAz3U1w0Zkj1y
VJQaa/aktmfd0KyFkU2M0xNpPIIcQkywUGCMZEmJkEIyyV/I+H/NvQ+qqU5llwIDAQAB
-----END PUBLIC KEY-----
"""


def rsa_encrypt(password: str) -> str:
    """
    Encrypts a string using the public key with PKCS1v15 padding.

    Args:
        password: The string to be encrypted.

    Returns:
        A base64 encoded string of the encrypted data.
    """
    public_key = serialization.load_pem_public_key(
        PUBLIC_KEY_PEM.encode(), backend=default_backend()
    )
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise TypeError("The public key is not a valid RSA key.")
    encrypted = public_key.encrypt(password.encode(), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()
