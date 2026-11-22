"""Bangla helpers: Unicode normalisation, digit conversion, language detection."""
import unicodedata

BN_DIGITS = "০১২৩৪৫৬৭৮৯"
_TO_ASCII = str.maketrans(BN_DIGITS, "0123456789")
_TO_BN = str.maketrans("0123456789", BN_DIGITS)


def normalize(text: str) -> str:
    """NFC first: য় / ড় / ঢ় can be typed as one or two code points depending on the keyboard."""
    return unicodedata.normalize("NFC", text).translate(_TO_ASCII).strip()


def is_bangla(text: str) -> bool:
    letters = [c for c in text if not c.isspace()]
    bn = sum(1 for c in letters if "ঀ" <= c <= "৿")
    return bool(letters) and bn / len(letters) > 0.3


def bn_digits(s: str) -> str:
    return s.translate(_TO_BN)
