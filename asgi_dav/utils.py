from urllib.parse import quote
from pathlib import Path
from base64 import b64encode
import datetime


# ------------------------------------------------------------------------------
def concat_uri(*parts: str) -> str:
    """
    Concatenate URL parts with a slash
    """
    starts_with_slash = parts[0].startswith("/")
    stripped_parts = [p.strip("/") for p in parts]
    filtered_parts = [quote(p) for p in stripped_parts if p]
    return f"{'/' if starts_with_slash else ''}{'/'.join(filtered_parts)}"


# ------------------------------------------------------------------------------
def make_data_url(filename: str, mimetype: str) -> str:
    """
    Create a data URL for a file, used for embedding images in HTML
    """
    path = Path(__file__).parent / "templates" / filename
    with path.open("rb") as f:
        data = f.read()
    return f"data:{mimetype};base64,{b64encode(data).decode()}"


# ------------------------------------------------------------------------------
def to_rfc_1123(dt: datetime.datetime) -> str:
    """
    Convert a datetime object to a string in RFC 1123 format
    """
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
