import re

RE_GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
RE_HEX = re.compile(r"\b0x[0-9a-fA-F]+\b")
RE_NUM = re.compile(r"\b\d+\b")
RE_QUOTED = re.compile(r"(['\"]).*?\1")
RE_PATH = re.compile(r"([A-Za-z]:\\|/)[\w\-/\\\.]+")
RE_MULTI_WS = re.compile(r"\s+")
RE_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
RE_EMAIL = re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b")
RE_BRACKETS = re.compile(r"\[[^\]]*\]|\([^\)]*\)|\{[^\}]*\}")

def normalize_message_for_cluster(msg: str) -> str:
    """
    Turn a message into a stable-ish cluster key by removing variable parts.
    """
    s = msg.strip()
    s = RE_QUOTED.sub("<str>", s)
    s = RE_GUID.sub("<guid>", s)
    s = RE_HEX.sub("<hex>", s)
    s = RE_IP.sub("<ip>", s)
    s = RE_EMAIL.sub("<email>", s)
    s = RE_PATH.sub("<path>", s)
    s = RE_NUM.sub("<num>", s)
    s = RE_BRACKETS.sub(" ", s)  # gets rid of noisy bracket blobs
    s = RE_MULTI_WS.sub(" ", s).strip()
    # Keep it short to avoid monstrous keys
    if len(s) > 180:
        s = s[:180] + "…"
    return s