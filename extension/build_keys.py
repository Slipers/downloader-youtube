"""One-off script: generates the extension's signing keypair, gives it a stable
Chrome extension ID (via manifest.json's "key" field), and prints the ID so it
can be wired into backend/link_server.py for CORS.

The private key never goes inside extension/ (that folder is copied verbatim
into installed browsers) -- it lives in backend/keys/, used only by
backend/extension_installer.py to sign the .crx served for auto-install.
"""
import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parent.parent
KEY_PATH = ROOT / "backend" / "keys" / "extension_signing_key.pem"
MANIFEST_PATH = Path(__file__).resolve().parent / "manifest.json"


def crx_id_from_public_der(pub_der: bytes) -> str:
    digest = hashlib.sha256(pub_der).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def main():
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)

    if KEY_PATH.exists():
        private_key = serialization.load_pem_private_key(KEY_PATH.read_bytes(), password=None)
        print(f"Using existing key at {KEY_PATH}")
    else:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        KEY_PATH.write_bytes(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        print(f"Generated new key at {KEY_PATH}")

    public_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_b64 = base64.b64encode(public_der).decode("ascii")
    ext_id = crx_id_from_public_der(public_der)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["key"] = key_b64
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Extension ID: {ext_id}")
    print("manifest.json updated with stable 'key'.")


if __name__ == "__main__":
    main()
