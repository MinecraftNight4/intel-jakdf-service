# cogs/squad/codec.py
"""Codigo compartible de una build (``/squad share`` y ``/squad editor``).

El bot no guarda nada: todo lo que hace falta para mostrar o editar la build va dentro del codigo.

Bytes: [cabecera][creador: 8][cuenta de referencia: 8, opcional][uuid de cada casilla]
       [largo: 2 + descripcion comprimida con zlib, opcional][crc: 2]  →  base64 url-safe sin '='
  cabecera = version<<4 | 1 si son 16 casillas | 2 si algun uuid pasa de 255 (2 bytes por uuid, si no 1)
                        | 4 si usa la cuenta de otro usuario | 8 si tiene descripcion
  uuid 0 = casilla vacia. Sin descripcion un codigo de 16 casillas mide unos 40 caracteres.
"""
import base64
import zlib
from typing import List, NamedTuple, Optional

VERSION = 1
MAX_DESCRIPTION = 240
MAX_NEWLINES = 10             # saltos de linea que admite la descripcion
SLOT_COUNTS = (4, 16)
_F_WIDE16, _F_WIDE_UUID, _F_ACCOUNT, _F_DESC = 1, 2, 4, 8


class Build(NamedTuple):
    creator_id: int
    account_id: Optional[int]       # None = se armo con todo el roster
    slots: List[int]                # uuids, 0 = vacio
    description: str


class CodeError(ValueError):
    pass


def count_newlines(text: str) -> int:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").count("\n")


def fit_description(text: str) -> str:
    """Limpia la descripcion: sin \\r, sin espacios en los bordes, maximo MAX_DESCRIPTION caracteres
    y MAX_NEWLINES saltos (los que sobran pasan a ser espacios)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()[:MAX_DESCRIPTION]
    head, *rest = text.split("\n")
    lines = [head]
    for i, line in enumerate(rest):
        if i < MAX_NEWLINES:
            lines.append(line)
        else:
            lines[-1] = f"{lines[-1]} {line}".strip()
    return "\n".join(lines)


def _checksum(body: bytes) -> bytes:
    return (zlib.crc32(body) & 0xFFFF).to_bytes(2, "big")


def encode(creator_id: int, slots: List[int], account_id: Optional[int] = None, description: str = "") -> str:
    if len(slots) not in SLOT_COUNTS:
        raise ValueError("a build has 4 or 16 slots")
    description = fit_description(description)
    wide = any(uuid > 255 for uuid in slots)
    head = (VERSION << 4) | (_F_WIDE16 if len(slots) == 16 else 0) | (_F_WIDE_UUID if wide else 0) \
        | (_F_ACCOUNT if account_id else 0) | (_F_DESC if description else 0)
    body = bytes([head]) + creator_id.to_bytes(8, "big")
    if account_id:
        body += account_id.to_bytes(8, "big")
    body += b"".join(u.to_bytes(2 if wide else 1, "big") for u in slots)
    if description:
        packed = zlib.compress(description.encode("utf-8"), 9)
        body += len(packed).to_bytes(2, "big") + packed
    return base64.urlsafe_b64encode(body + _checksum(body)).rstrip(b"=").decode()


def decode(code: str) -> Build:
    """``CodeError`` si el codigo esta mal copiado o incompleto."""
    text = "".join((code or "").replace("`", "").split())
    if text.lower().startswith("squadcode:"):
        text = text[len("squadcode:"):]
    damaged = CodeError("the code is damaged (was it copied completely?)")
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except Exception:
        raise CodeError("that doesn't look like a squad code")
    if len(raw) < 13 or raw[0] >> 4 != VERSION:
        raise CodeError("that doesn't look like a squad code")
    body, crc = raw[:-2], raw[-2:]
    if _checksum(body) != crc:
        raise damaged
    flags = raw[0]
    count, width = (16 if flags & _F_WIDE16 else 4), (2 if flags & _F_WIDE_UUID else 1)
    pos = 1
    creator = int.from_bytes(body[pos:pos + 8], "big")
    pos += 8
    account = None
    if flags & _F_ACCOUNT:
        account = int.from_bytes(body[pos:pos + 8], "big")
        pos += 8
    end = pos + count * width
    if end > len(body):
        raise damaged
    slots = [int.from_bytes(body[pos + i * width:pos + (i + 1) * width], "big") for i in range(count)]
    pos = end
    description = ""
    if flags & _F_DESC:
        if pos + 2 > len(body):
            raise damaged
        size = int.from_bytes(body[pos:pos + 2], "big")
        chunk = body[pos + 2:pos + 2 + size]
        if len(chunk) != size:
            raise damaged
        try:                                       # tope de tamaño: no se descomprime una bomba
            reader = zlib.decompressobj()
            description = reader.decompress(chunk, 4 * MAX_DESCRIPTION * 2).decode("utf-8")
            description = fit_description(description)
        except Exception:
            raise damaged
        pos += 2 + size
    if pos != len(body):
        raise damaged
    return Build(creator, account, slots, description)
