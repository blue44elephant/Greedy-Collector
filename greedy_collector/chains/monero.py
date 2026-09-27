"""Offline validation for Monero mainnet CryptoNote addresses."""
from __future__ import annotations

import re

from Cryptodome.Hash import keccak

from .base import ChainAdapter

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
INDEX = {character: index for index, character in enumerate(ALPHABET)}
BLOCK_BYTES_BY_CHARS = {2: 1, 3: 2, 5: 3, 6: 4, 7: 5, 9: 6, 10: 7, 11: 8}
CHARS_BY_BLOCK_BYTES = {value: key for key, value in BLOCK_BYTES_BY_CHARS.items()}
MAINNET_PREFIXES = {18: "standard", 19: "integrated", 42: "subaddress"}
ED25519_FIELD = (1 << 255) - 19
ED25519_D = (-121665 * pow(121666, ED25519_FIELD - 2, ED25519_FIELD)) % ED25519_FIELD


def _encode_block(value: bytes) -> str:
    number = int.from_bytes(value, "big")
    encoded = ""
    while number:
        number, digit = divmod(number, 58)
        encoded = ALPHABET[digit] + encoded
    return encoded.rjust(CHARS_BY_BLOCK_BYTES[len(value)], "1")


def cryptonote_base58_decode(value: str) -> bytes:
    """Decode Monero's fixed-width 8-byte CryptoNote Base58 blocks."""
    if not isinstance(value, str) or not value:
        raise ValueError("Invalid Monero address format")
    result = bytearray()
    chunks = [value[index:index + 11] for index in range(0, len(value), 11)]
    if any(len(chunk) != 11 for chunk in chunks[:-1]):
        raise ValueError("Invalid Monero address format")
    for chunk in chunks:
        size = BLOCK_BYTES_BY_CHARS.get(len(chunk))
        if size is None:
            raise ValueError("Invalid Monero address format")
        number = 0
        for character in chunk:
            try:
                digit = INDEX[character]
            except KeyError:
                raise ValueError("Invalid Monero address format") from None
            number = number * 58 + digit
        if number >= 1 << (8 * size):
            raise ValueError("Invalid Monero address format")
        block = number.to_bytes(size, "big")
        if _encode_block(block) != chunk:
            raise ValueError("Invalid Monero address format")
        result.extend(block)
    return bytes(result)


def keccak_256(value: bytes) -> bytes:
    digest = keccak.new(digest_bits=256)
    digest.update(value)
    return digest.digest()


def _valid_public_key(value: bytes) -> bool:
    """Match Monero's compressed Edwards-point check for each public key."""
    if len(value) != 32:
        return False
    encoded = int.from_bytes(value, "little")
    sign = encoded >> 255
    y = encoded & ((1 << 255) - 1)
    if y >= ED25519_FIELD:
        return False
    y_squared = y * y % ED25519_FIELD
    denominator = (ED25519_D * y_squared + 1) % ED25519_FIELD
    if denominator == 0:
        return False
    x_squared = (y_squared - 1) * pow(denominator, ED25519_FIELD - 2, ED25519_FIELD) % ED25519_FIELD
    x = pow(x_squared, (ED25519_FIELD + 3) // 8, ED25519_FIELD)
    if x * x % ED25519_FIELD != x_squared:
        x = x * pow(2, (ED25519_FIELD - 1) // 4, ED25519_FIELD) % ED25519_FIELD
    if x * x % ED25519_FIELD != x_squared or (x == 0 and sign):
        return False
    return True


def validate_monero_address(value: str) -> tuple[str, str]:
    """Validate a standard address, subaddress, or integrated address locally."""
    if not isinstance(value, str):
        raise ValueError("Invalid Monero address format")
    candidate = value.strip()
    if len(candidate) not in (95, 106):
        raise ValueError("Invalid Monero address format")
    decoded = cryptonote_base58_decode(candidate)
    if len(candidate) == 95:
        if len(decoded) != 69:
            raise ValueError("Invalid Monero address format")
        kind = MAINNET_PREFIXES.get(decoded[0])
        if kind not in ("standard", "subaddress"):
            raise ValueError("Invalid Monero mainnet address prefix")
    else:
        if len(decoded) != 77 or decoded[0] != 19:
            raise ValueError("Invalid Monero mainnet address prefix")
        kind = "integrated"
    if decoded[-4:] != keccak_256(decoded[:-4])[:4]:
        raise ValueError("Invalid Monero address checksum")
    if not _valid_public_key(decoded[1:33]) or not _valid_public_key(decoded[33:65]):
        raise ValueError("Invalid Monero public key encoding")
    return candidate, kind


class MoneroAdapter(ChainAdapter):
    chain = "monero"
    address_pattern = re.compile(r"[1-9A-HJ-NP-Za-km-z]{95}|[1-9A-HJ-NP-Za-km-z]{106}")
    address_case = "sensitive"
    behavioral_risk = False

    def validate_address(self, address: str) -> str:
        candidate, _kind = validate_monero_address(address)
        return candidate
