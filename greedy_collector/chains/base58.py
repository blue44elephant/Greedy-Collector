"""Small canonical base58 codec shared by account-family chain adapters."""

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BASE58_INDEX = {character: index for index, character in enumerate(BASE58_ALPHABET)}


def base58_decode(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("Invalid base58 value")
    number = 0
    for character in value:
        try:
            digit = BASE58_INDEX[character]
        except KeyError:
            raise ValueError("Invalid base58 value") from None
        number = number * 58 + digit
    payload = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\x00" * (len(value) - len(value.lstrip("1"))) + payload


def base58_encode(value: bytes) -> str:
    leading = len(value) - len(value.lstrip(b"\x00"))
    number = int.from_bytes(value, "big")
    encoded = ""
    while number:
        number, digit = divmod(number, 58)
        encoded = BASE58_ALPHABET[digit] + encoded
    return "1" * leading + encoded
