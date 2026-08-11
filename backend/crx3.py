"""Minimal CRX3 packer (see chromium /components/crx_file/crx3.proto).

Hand-rolls the tiny protobuf messages involved (SignedData, AsymmetricKeyProof,
CrxFileHeader) instead of depending on the `protobuf` package, since each
message only has 1-2 bytes fields.
"""
import hashlib
import io
import struct
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

SIGNATURE_CONTEXT = b"CRX3 SignedData\x00"

# Files copied into the browser profile; dev-only helper scripts are excluded.
PACKAGED_ENTRIES = [
    "manifest.json",
    "background.js",
    "content.js",
    "content.css",
    "popup.html",
    "popup.css",
    "popup.js",
]


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)


def _proto_bytes_field(field_number: int, value: bytes) -> bytes:
    tag = (field_number << 3) | 2  # wire type 2 = length-delimited
    return bytes([tag]) + _varint(len(value)) + value


def _zip_extension(extension_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in PACKAGED_ENTRIES:
            zf.write(extension_dir / entry, entry)
        icons_dir = extension_dir / "icons"
        for icon in sorted(icons_dir.glob("*.png")):
            zf.write(icon, f"icons/{icon.name}")
    return buffer.getvalue()


def compute_crx_id(private_key) -> bytes:
    """Raw 16-byte id (before the hex->a-p letter mapping used for the string id)."""
    pub_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(pub_der).digest()[:16]


def build_crx(extension_dir: Path, private_key, output_path: Path) -> None:
    zip_bytes = _zip_extension(extension_dir)

    pub_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    crx_id_raw = compute_crx_id(private_key)

    signed_header_data = _proto_bytes_field(1, crx_id_raw)  # SignedData.crx_id

    to_sign = SIGNATURE_CONTEXT + struct.pack("<I", len(signed_header_data)) + signed_header_data + zip_bytes
    signature = private_key.sign(to_sign, padding.PKCS1v15(), hashes.SHA256())

    proof = _proto_bytes_field(1, pub_der) + _proto_bytes_field(2, signature)  # AsymmetricKeyProof
    header = _proto_bytes_field(2, proof) + _proto_bytes_field(10, signed_header_data)  # CrxFileHeader

    crx = b"Cr24" + struct.pack("<II", 3, len(header)) + header + zip_bytes

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(crx)
