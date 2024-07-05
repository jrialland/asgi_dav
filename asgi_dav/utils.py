from urllib.parse import quote
from pathlib import Path
from base64 import b64encode
import datetime
import mimetypes
import re
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
def to_rfc_1123(dt: datetime.datetime) -> str:
    """
    Convert a datetime object to a string in RFC 1123 format
    """
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")

# ------------------------------------------------------------------------------
def guess_contenttype(filename: str, include_charset:bool=True) -> str:
    """
    Guess the content type of a file based on its extension
    """
    mimetype, encoding = mimetypes.guess_type(filename)
    if mimetype:
        contenttype = mimetype
        if encoding and include_charset:
            contenttype += f"; charset={encoding}"
    else:
        contenttype = "application/octet-stream"
    return contenttype

def make_data_url(filename: str) -> str:
    """
    Create a data URL for a file in the templates directory. Used for embedding images in html
    """
    path = Path(__file__).parent / "templates" / filename
    with path.open("rb") as f:
        return f"data:{guess_contenttype(filename, False)};base64,{b64encode(f.read()).decode()}"
    
def get_parent_href(href: str) -> str:
    """
    Get the parent href of a given href
    """
    return re.sub(r"[^/]+/?$", "", href)