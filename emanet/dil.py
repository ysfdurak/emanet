"""Türkçe sayı ekleri: "%67'sini", "8'i", "3'ünü", "40'ında".

Ek, sayının okunuşunun son sözcüğüne göre seçilir (67 → "altmış yedi" → "yedi" → 'sini').
"""
from __future__ import annotations

_BIRLER = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_ONLAR = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
_SERT = set("fstkçşhp")
_KALIN = set("aıou")


def _son_sozcuk(n: int) -> str:
    n = abs(int(n))
    if n == 0:
        return "sıfır"
    if n % 10:
        return _BIRLER[n % 10]
    if n % 100:
        return _ONLAR[(n % 100) // 10]
    if n % 1000:
        return "yüz"
    return "bin" if n % 1_000_000 else "milyon"


def ek(n: int, tur: str) -> str:
    """tur: 'i' (8'i), 'in' (%45'in), 'ini' (%67'sini), 'ine' (%40'ına), 'inde' (3'ünde), 'inden' (%60'ından), 'de' (5'te), 'e' (6'ya)."""
    s = _son_sozcuk(n)
    unlu = next(c for c in reversed(s) if c in "aeıioöuü")
    dort = {"a": "ı", "ı": "ı", "o": "u", "u": "u", "e": "i", "i": "i", "ö": "ü", "ü": "ü"}[unlu]
    iki = "a" if unlu in _KALIN else "e"
    unluyle = s[-1] in "aeıioöuü"
    if tur == "i":
        return ("y" if unluyle else "") + dort
    if tur == "in":
        return ("n" if unluyle else "") + dort + "n"
    if tur == "ini":
        return ("s" if unluyle else "") + dort + "n" + dort
    if tur == "ine":
        return ("s" if unluyle else "") + dort + "n" + iki
    if tur == "inde":
        return ("s" if unluyle else "") + dort + "nd" + iki
    if tur == "inden":
        return ("s" if unluyle else "") + dort + "nd" + iki + "n"
    if tur == "de":
        return ("t" if s[-1] in _SERT else "d") + iki
    if tur == "e":
        return ("y" if unluyle else "") + iki
    raise ValueError(tur)


def sayi(n: int, tur: str) -> str:
    """'8' + ek → "8'i"."""
    return f"{n}'{ek(n, tur)}"


def yuzde(oran: float, tur: str) -> str:
    """0,67 → "%67'sini"."""
    n = round(oran * 100)
    return f"%{n}'{ek(n, tur)}"
