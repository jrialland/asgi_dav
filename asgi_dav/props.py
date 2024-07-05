from io import StringIO
import datetime
from typing import TextIO
from fs.info import Info
from xml.etree.ElementTree import Element, ElementTree
from .utils import concat_uri, to_rfc_1123
import mimetypes
from hashlib import md5


# ------------------------------------------------------------------------------
class FileProps:
    """
    A class that wraps a FS Info object to provide the properties of a file
    objects of this class are used in Jinja templates to display file properties
    """

    def __init__(self, info: Info, parent_href: str):
        self.info = info
        self.parent_href = parent_href
        self._etag = None
        self._contenttype = None

    @property
    def etag(self) -> str:
        if self._etag is None:
            digest = md5()
            digest.update(self.info.name.encode())
            digest.update(str(self.info.size).encode())
            digest.update(self.info.modified.strftime("%Y-%m-%d %H:%M:%S").encode())
            self._etag = digest.hexdigest()
        return self._etag

    @property
    def href(self) -> str:
        return concat_uri(self.parent_href, self.name)

    @property
    def name(self) -> str:
        return self.info.name

    @property
    def contentlength(self) -> int:
        return self.info.size

    @property
    def is_dir(self) -> bool:
        return self.info.is_dir

    @property
    def is_file(self) -> bool:
        return self.info.is_file

    @property
    def size(self) -> int:
        return self.info.size if self.info.is_file else 0

    @property
    def lastmodified(self) -> str:
        dt = self.info.modified or datetime.datetime.min
        return to_rfc_1123(dt)

    @property
    def creationdate(self) -> str:
        dt = self.info.created or datetime.datetime.min
        return to_rfc_1123(dt)

    @property
    def content_type(self) -> str:
        if self._contenttype is None:
            mimetype, encoding = mimetypes.guess_type(self.info.name)
            if mimetype:
                self._contenttype = mimetype
                if encoding:
                    self._contenttype += f"; charset={encoding}"
            else:
                self._contenttype = "application/octet-stream"
        return self._contenttype

    @property
    def props(self) -> dict[str, str]:
        props = {
            "D:displayname": self.name,
            "D:getcontentlength": str(self.contentlength),
            "D:getcontenttype": self.content_type,
            #"D:creationdate": self.creationdate,
            "D:getlastmodified": self.lastmodified,
        }
        if self.info.is_dir:
            props.update({
                "D:getcontentlength": "0",
                "D:getcontenttype": "httpd/unix-directory",
            })
        else:
            props.update({
                "D:getcontentlength": str(self.info.size),
                "D:getcontenttype": self.content_type
            })
        return props

    def __lt__(self, other: "FileProps") -> bool:
        if self.is_dir and not other.is_dir:
            return True
        elif not self.is_dir and other.is_dir:
            return False
        else:
            return self.name < other.name


# ------------------------------------------------------------------------------
class PropfindResponseBuilder:

    class Response:
        def __init__(self, href: str, properties: dict[str, str] | None = None):
            self.href = href
            self.properties = properties or {}
            self.status = "HTTP/1.1 200 OK"

        def add_property(self, name: str, value: str):
            self.properties[name] = value

        def to_element(self) -> Element:
            response = Element("D:response")
            href_element = Element("D:href")
            href_element.text = self.href
            response.append(href_element)
            propstat = Element("D:propstat")
            prop = Element("D:prop")
            for key, value in self.properties.items():
                prop_element = Element(key)
                prop_element.text = value
                prop.append(prop_element)
            status = Element("D:status")
            status.text = self.status
            propstat.append(status)
            propstat.append(prop)
            response.append(propstat)
            return response

    def __init__(self):
        self.namespaces = {"D": "DAV:"}
        self._responses: list["PropfindResponseBuilder.Response"] = []

    def add_response(self, href: str, properties: dict[str, str] | None = None):
        self._responses.append(PropfindResponseBuilder.Response(href, properties))

    def write(self, out: TextIO):
        multistatus = Element("D:multistatus")
        for key, value in self.namespaces.items():
            multistatus.set(f"xmlns:{key}", value)
        document = ElementTree(multistatus)
        for response in self._responses:
            document.getroot().append(response.to_element())
        document.write(out, encoding="unicode", xml_declaration=True)

    def to_xml(self) -> str:
        t = StringIO()
        self.write(t)
        return t.getvalue()
