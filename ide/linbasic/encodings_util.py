"""File encoding handling, mirroring Notepad++'s Encoding menu (45001-45068)."""
import codecs
import locale
import os

# Unicode modes
UNICODE = {
    45004: ("ansi", "ANSI"),
    45008: ("utf8", "UTF-8"),
    45005: ("utf8bom", "UTF-8-BOM"),
    45006: ("utf16be", "UTF-16 BE BOM"),
    45007: ("utf16le", "UTF-16 LE BOM"),
}
CONVERT = {45009: "ansi", 45010: "utf8", 45011: "utf8bom", 45012: "utf16be", 45013: "utf16le"}

# Character sets: menu id -> (python codec, status-bar name)
CHARSETS = {
    45034: ("iso8859_6", "ISO 8859-6"), 45045: ("cp720", "OEM 720"), 45026: ("cp1256", "Windows-1256"),
    45032: ("iso8859_4", "ISO 8859-4"), 45040: ("iso8859_13", "ISO 8859-13"), 45047: ("cp775", "OEM 775"),
    45027: ("cp1257", "Windows-1257"), 45041: ("iso8859_14", "ISO 8859-14"),
    45033: ("iso8859_5", "ISO 8859-5"), 45068: ("koi8_r", "KOI8-R"), 45067: ("koi8_u", "KOI8-U"),
    45066: ("mac_cyrillic", "Macintosh"), 45050: ("cp855", "OEM 855"), 45058: ("cp866", "OEM 866"),
    45021: ("cp1251", "Windows-1251"), 45049: ("cp852", "OEM 852"), 45020: ("cp1250", "Windows-1250"),
    45060: ("big5", "Big5 (Traditional)"), 45061: ("gb2312", "GB2312 (Simplified)"),
    45030: ("iso8859_2", "ISO 8859-2"), 45035: ("iso8859_7", "ISO 8859-7"), 45046: ("cp737", "OEM 737"),
    45059: ("cp869", "OEM 869"), 45023: ("cp1253", "Windows-1253"), 45036: ("iso8859_8", "ISO 8859-8"),
    45055: ("cp862", "OEM 862"), 45025: ("cp1255", "Windows-1255"), 45062: ("shift_jis", "Shift-JIS"),
    45063: ("cp949", "Windows 949"), 45064: ("euc_kr", "EUC-KR"), 45054: ("cp861", "OEM 861 : Icelandic"),
    45057: ("cp865", "OEM 865 : Nordic"), 45065: ("tis_620", "TIS-620"), 45031: ("iso8859_3", "ISO 8859-3"),
    45037: ("iso8859_9", "ISO 8859-9"), 45051: ("cp857", "OEM 857"), 45024: ("cp1254", "Windows-1254"),
    45029: ("latin_1", "ISO 8859-1"), 45042: ("iso8859_15", "ISO 8859-15"), 45048: ("cp850", "OEM 850"),
    45052: ("cp858", "OEM 858"), 45053: ("cp860", "OEM 860 : Portuguese"), 45056: ("cp863", "OEM 863 : French"),
    45044: ("cp437", "OEM-US"), 45022: ("cp1252", "Windows-1252"), 45028: ("cp1258", "Windows-1258"),
}
CODEC_TO_ID = {v[0]: k for k, v in CHARSETS.items()}

_LOCALE_ANSI = {
    "el": "cp1253", "ru": "cp1251", "uk": "cp1251", "bg": "cp1251", "be": "cp1251", "sr": "cp1251",
    "mk": "cp1251", "pl": "cp1250", "cs": "cp1250", "sk": "cp1250", "hu": "cp1250", "sl": "cp1250",
    "hr": "cp1250", "ro": "cp1250", "tr": "cp1254", "he": "cp1255", "ar": "cp1256", "fa": "cp1256",
    "lt": "cp1257", "lv": "cp1257", "et": "cp1257", "vi": "cp1258", "ja": "cp932", "ko": "cp949",
    "th": "cp874", "zh_TW": "big5", "zh_HK": "big5", "zh": "gbk",
}


def system_ansi(settings=None):
    """The code page Notepad++ would call ANSI on a Windows box with this locale."""
    if settings is not None and settings.get("ansi_codepage"):
        return settings.get("ansi_codepage")
    loc = os.environ.get("LC_ALL") or os.environ.get("LC_CTYPE") or os.environ.get("LANG") or ""
    if not loc:
        try:
            loc = locale.getlocale()[0] or ""
        except ValueError:
            loc = ""
    loc = loc.split(".")[0]
    if loc in _LOCALE_ANSI:
        return _LOCALE_ANSI[loc]
    return _LOCALE_ANSI.get(loc.split("_")[0], "cp1252")


def display_name(enc):
    if enc in ("ansi", "utf8", "utf8bom", "utf16be", "utf16le"):
        return {"ansi": "ANSI", "utf8": "UTF-8", "utf8bom": "UTF-8-BOM",
                "utf16be": "UTF-16 BE BOM", "utf16le": "UTF-16 LE BOM"}[enc]
    cid = CODEC_TO_ID.get(enc)
    return CHARSETS[cid][1] if cid else enc


def menu_id(enc):
    for k, v in UNICODE.items():
        if v[0] == enc:
            return k
    return CODEC_TO_ID.get(enc)


def _looks_utf8(data):
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError as e:
        # tolerate a multi-byte sequence cut at the very end of a sample
        return e.start >= len(data) - 3 and len(data) > 3


def detect(data, settings=None):
    """Return (encoding_key, text). BOMs first, then UTF-8 validation, then a
    UTF-16 heuristic for BOM-less files, then the ANSI code page."""
    if data.startswith(codecs.BOM_UTF8):
        return "utf8bom", data[3:].decode("utf-8", errors="replace")
    if data.startswith(codecs.BOM_UTF16_LE):
        return "utf16le", data[2:].decode("utf-16-le", errors="replace")
    if data.startswith(codecs.BOM_UTF16_BE):
        return "utf16be", data[2:].decode("utf-16-be", errors="replace")
    if _looks_utf8(data):
        return "utf8", data.decode("utf-8", errors="replace")
    sample = data[:4096]
    if len(sample) >= 4:
        evens = sample[0::2].count(0)
        odds = sample[1::2].count(0)
        half = len(sample) // 2
        if odds > half * 0.4 and evens < half * 0.05:
            return "utf16le", data.decode("utf-16-le", errors="replace")
        if evens > half * 0.4 and odds < half * 0.05:
            return "utf16be", data.decode("utf-16-be", errors="replace")
    cp = system_ansi(settings)
    return "ansi", data.decode(cp, errors="replace")


def decode(data, enc, settings=None):
    if enc == "utf8bom":
        if data.startswith(codecs.BOM_UTF8):
            data = data[3:]
        return data.decode("utf-8", errors="replace")
    if enc == "utf8":
        return data.decode("utf-8", errors="replace")
    if enc == "utf16le":
        if data.startswith(codecs.BOM_UTF16_LE):
            data = data[2:]
        return data.decode("utf-16-le", errors="replace")
    if enc == "utf16be":
        if data.startswith(codecs.BOM_UTF16_BE):
            data = data[2:]
        return data.decode("utf-16-be", errors="replace")
    if enc == "ansi":
        return data.decode(system_ansi(settings), errors="replace")
    return data.decode(enc, errors="replace")


def encode(text, enc, settings=None, strict=False):
    errors = "strict" if strict else "replace"
    if enc == "utf8bom":
        return codecs.BOM_UTF8 + text.encode("utf-8", errors="surrogatepass")
    if enc == "utf8":
        return text.encode("utf-8", errors="surrogatepass")
    if enc == "utf16le":
        return codecs.BOM_UTF16_LE + text.encode("utf-16-le", errors="surrogatepass")
    if enc == "utf16be":
        return codecs.BOM_UTF16_BE + text.encode("utf-16-be", errors="surrogatepass")
    if enc == "ansi":
        return text.encode(system_ansi(settings), errors=errors)
    return text.encode(enc, errors=errors)


def can_encode(text, enc, settings=None):
    try:
        encode(text, enc, settings, strict=True)
        return True
    except (UnicodeEncodeError, LookupError):
        return False
