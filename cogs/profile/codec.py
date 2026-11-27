# cogs/profile/codec.py
"""Un perfil ({uuid: dupes}) como UN solo texto corto: lo que se guarda en la base de datos.

Formato (base64url sin relleno):
    byte 0     version (1)
    resto      un numero entero little-endian con 3 bits por personaje:
               bits [3*(uuid-1), 3*(uuid-1)+3)  →  0 = no lo tiene, 1..7 = dupes 0..6 (dupes + 1)
               los ceros del final no se guardan

Con 64 personajes son 25 bytes (34 caracteres). Un personaje nuevo solo añade bits al final,
asi que los perfiles viejos siguen leyendose igual. Un perfil vacio es el texto vacio ``""``.

Version equivalente en JS (para la Activity): leer cada trio de bits con ``(n >> (3n * (uuid-1))) & 7n`` usando BigInt.
"""
import base64
from typing import Dict

VERSION = 1
BITS = 3
MAX_DUPES = 6                       # 3 bits: 0 = vacio + 7 valores (0..6 dupes)


def pack(owned: Dict[int, int]) -> str:
    n = 0
    for uuid, dupes in owned.items():
        if uuid < 1:
            raise ValueError(f"uuid invalido: {uuid}")
        n |= (max(0, min(MAX_DUPES, int(dupes))) + 1) << (BITS * (uuid - 1))
    if not n:
        return ""
    raw = bytes([VERSION]) + n.to_bytes((n.bit_length() + 7) // 8, "little")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def unpack(text: str) -> Dict[int, int]:
    if not text:
        return {}
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except Exception as err:
        raise ValueError("perfil ilegible") from err
    if not raw or raw[0] != VERSION:
        raise ValueError("version de perfil desconocida")
    n = int.from_bytes(raw[1:], "little")
    owned, uuid = {}, 1
    while n:
        value = n & 0b111
        if value:
            owned[uuid] = value - 1
        n >>= BITS
        uuid += 1
    return owned
