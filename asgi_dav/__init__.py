"""
    an ASGI application that handles WebDAV requests
"""

from asgiref.typing import (
    Scope,
    HTTPScope,
    HTTPRequestEvent,
    ASGIReceiveCallable,
    ASGISendCallable,
)
import datetime
import mimetypes
from urllib.parse import quote, unquote, urlparse
from fs.base import FS
from fs.info import Info
from jinja2 import Environment, PackageLoader
import humanize
import re
from xml.dom.minidom import parseString, Document
from hashlib import md5
import http.client  # for HTTP status codes constants
# ------------------------------------------------------------------------------
__version__ = "0.1.0"
__author__ = "Julien Rialland"


# ------------------------------------------------------------------------------
# The size of the chunks to read from the files
CHUNK_SIZE = 128 * 1024

# The maximum number of items to display in a directory listing
MAX_DIR_LISTING = 10000


# ------------------------------------------------------------------------------
class FileProps:
    """
    A class that wraps a FS Info object to provide the properties of a file
    objects of this class are used in Jinja templates to display file properties
    """

    def __init__(self, info: Info):
        self.info = info

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
    def lastmodified(self) -> float:
        dt = self.info.modified or datetime.datetime.min
        return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")

    @property
    def contenttype(self) -> str:
        mimetype, encoding = mimetypes.guess_type(self.info.name)
        if mimetype:
            content_type = mimetype
            if encoding:
                content_type += f"; charset={encoding}"
        else:
            content_type = "application/octet-stream"
        return content_type

    def __lt__(self, other: "FileProps") -> bool:
        if self.is_dir and not other.is_dir:
            return True
        elif not self.is_dir and other.is_dir:
            return False
        else:
            return self.name < other.name


# ------------------------------------------------------------------------------
def concat_uri(*parts: str) -> str:
    """
    Concatenate URL parts with a slash
    """
    is_absolute = parts[0].startswith("/")
    r = "/".join(map(lambda p: quote(p.strip("/")), parts))
    if is_absolute:
        if not r.startswith("/"):
            r = "/" + r
    else:
        if r.startswith("/"):
            r = r[1:]
    return r

# ------------------------------------------------------------------------------
def make_data_url(filename: str, mimetype: str) -> str:
    """
    Create a data URL for a file, used for embedding images in HTML
    """
    from pathlib import Path
    from base64 import b64encode
    path = Path(__file__).parent / "templates" / filename
    with path.open("rb") as f:
        data = f.read()
    return f"data:{mimetype};base64,{b64encode(data).decode()}"

# ------------------------------------------------------------------------------
class DAVApp:
    """
    An ASGI application that handles WebDAV requests
    """

    def __init__(self, fs: FS, path_prefix: str = ""):
        """
        Create a new DAVApp instance
        :param fs: the filesystem to use
        """
        assert fs, "fs is required"
        assert path_prefix == "" or path_prefix.startswith("/"), "path_prefix must start with a slash"


        self.fs = fs
        self.path_prefix = path_prefix[:-1] if path_prefix.endswith("/") else path_prefix
        self.jinja_env = Environment(loader=PackageLoader(__name__, "templates"))
        self.jinja_env.globals["concat_uri"] = concat_uri
        self.jinja_env.globals["make_data_url"] = make_data_url
        self.jinja_env.globals["naturalsize"] = humanize.naturalsize
        self.handlers = {
            "HEAD": self.get_or_head,
            "GET": self.get_or_head,
            "PUT": self.put,
            "DELETE": self.delete,
            "MKCOL": self.mkcol,
            "PROPFIND": self.propfind,
            "OPTIONS": self.options,
            "PROPPATCH": self.proppatch,
            "COPY": self.copy_or_move,
            "MOVE": self.copy_or_move,
        }

    async def __call__(
        self, scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await self.startup()
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await self.shutdown()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        elif scope["type"] == "http":
            handler = self.handlers.get(scope["method"], self.not_implemented)
            await handler(scope, receive, send)
        else:
            raise ValueError(f"Unsupported scope type {scope['type']}")

    async def startup(self): ...

    async def shutdown(self): ...

    async def options(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        methods = list(self.handlers.keys())
        methods.sort()
        headers = {
            "DAV": "1,2",
            "Allow": ", ".join(methods),
            "MS-Author-Via": "DAV",
            "Accept-Ranges": "bytes",
        }
        await self.respond(send, http.client.OK, b"OK", headers)

    def _get_path(self, scope: HTTPScope) -> str:
        path = scope["path"]
        if path.startswith(self.path_prefix):
            path = path[len(self.path_prefix) :]
        return path

    async def copy_or_move(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        is_copy = scope["method"] == "COPY"
        path = self._get_path(scope)
        destination = self.get_first_header(scope, "Destination")
        if destination is None:
            await self.respond(send, http.client.BAD_REQUEST, b"Bad Request")
            return

        # destination is an absolute URI, so we need to extract the path
        destination = unquote(urlparse(destination).path)

        overwrite = self.get_first_header(scope, "Overwrite") == "T"
        if self.fs.exists(destination):
            await self.respond(send, http.client.FORBIDDEN, b"Forbidden")
            return

        if is_copy:
            if self.fs.isdir(path):
                self.fs.copydir(path, destination, create=True)
            else:
                self.fs.copy(path, destination, overwrite=overwrite)
        else:
            if self.fs.isdir(path):
                self.fs.movedir(path, destination, create=True)
            else:
                self.fs.move(path, destination, overwrite=overwrite)

        await self.respond(send, http.client.CREATED, b"Created")

    async def get_or_head(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        is_head = scope["method"] == "HEAD"
        path = self._get_path(scope)
        if not self.fs.exists(path):
            await self.respond(send, http.client.NOT_FOUND, b"Not found")
            return
        if self.fs.isdir(path):
            await self.send_dir_listing(send, path, is_head=is_head)
        else:
            await self.send_file(scope, receive, send, path, is_head=is_head)

    async def put(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        path = self._get_path(scope)

        if self.fs.isdir(path):
            await self.respond(send, http.client.METHOD_NOT_ALLOWED)
            return

        # if self.get_first_header(scope, "Expect") == "100-continue":
        #     await send({"type": "http.response.start", "status": 100, "headers": []})

        remaining = int(self.get_first_header(scope, "Content-Length") or 0)
        if remaining == 0:
            await self.respond(send, http.client.LENGTH_REQUIRED)
            return

        with self.fs.open(path, "wb" if self.fs.isfile(path) else "xb") as f:
            while remaining > 0:
                message: HTTPRequestEvent = await receive()  # type: ignore
                if message["type"] == "http.disconnect":
                    break
                chunk = message["body"]
                f.write(chunk)
                remaining -= len(chunk)
        await self.respond(send, http.client.CREATED)

    async def delete(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        path = self._get_path(scope)
        if not self.fs.exists(path):
            await self.respond(send, http.client.NOT_FOUND)
            return

        self.fs.remove(path)
        await self.respond(send, http.client.NO_CONTENT)

    async def mkcol(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        path = self._get_path(scope)
        if self.fs.exists(path):
            await self.respond(send, 405, b"Method Not Allowed")
            return

        self.fs.makedirs(path)
        await self.respond(send, http.client.CREATED)

    async def propfind(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        path = self._get_path(scope)

        if not self.fs.exists(path):
            await self.respond(send, http.client.NOT_FOUND, b"Not found")
            return

        depth = self.get_first_header(scope, "Depth")

        if depth == "0":
            await self.send_propfind(
                send, path, [FileProps(self.fs.getinfo(path))], depth
            )

        elif depth == "1" or depth is None:
            listing = [FileProps(self.fs.getinfo(path))] + [
                FileProps(info)
                for info in self.fs.scandir(path, namespaces=["details"])
                if info.name[0] != "."
            ]
            listing.sort()
            # depth 1 : get infos about the requested resource and its children
            await self.send_propfind(
                send,
                path,
                listing,
                depth,
            )

        elif depth == "infinity":
            await self.respond(send, http.client.NOT_IMPLEMENTED, b"Not implemented")
        else:
            await self.respond(send, http.client.BAD_REQUEST, b"Bad Request")

    async def proppatch(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        """
        Handle PROPPATCH requests : parse propstat xml, change props, and return a multistatus response
        """
        path = self._get_path(scope)

        if not self.fs.exists(path):
            await self.respond(send, http.client.NOT_FOUND, b"Not found")
            return

        props = {}
        document = parseString(await self.read_request_body(scope, receive))

        def get_namespaces(document: Document) -> dict[str, str]:
            namespaces = {}
            for node in document.getElementsByTagName("*"):
                if node.namespaceURI:
                    namespaces[node.namespaceURI] = node.prefix
            return namespaces

        namespaces = get_namespaces(document)
        ns_to_prefix = lambda ns: namespaces[ns] if ns in namespaces else ""
        for propstat in document.getElementsByTagName(
            f"{ns_to_prefix('DAV:')}:propertyupdate"
        ):
            for prop in propstat.getElementsByTagName(f"{ns_to_prefix('DAV:')}:prop"):
                props[prop.firstChild.tagName] = str(
                    prop.firstChild.firstChild.nodeValue
                )
        xmlns = " ".join([f'xmlns:{ns_to_prefix(ns)}="{ns}"' for ns in namespaces])
        dav_ns = ns_to_prefix("DAV:")
        output = f"""<?xml version="1.0" encoding="utf-8" ?>
        <{dav_ns}:multistatus {xmlns}>
            <{dav_ns}:response>
                <{dav_ns}:href>{path}</{dav_ns}:href>
                <{dav_ns}:propstat>
                    <{dav_ns}:prop>
                        {''.join([f'<{k}>{v}</{k}>' for k, v in props.items()])}
                    </{dav_ns}:prop>
                    <{dav_ns}:status>HTTP/1.1 http.client.OK OK</{dav_ns}:status>
                </{dav_ns}:propstat>
            </{dav_ns}:response>
        </{dav_ns}:multistatus>
        """
        await self.respond(
            send, http.client.MULTI_STATUS, output, {"Content-Type": "text/xml"}
        )

    async def send_propfind(
        self, send: ASGISendCallable, path: str, listing: list[FileProps], depth: str
    ):
        template = self.jinja_env.get_template("propfind.xml")
        body = template.render(path=path, listing=listing, depth=depth)
        await self.respond(
            send, http.client.MULTI_STATUS, body, {"Content-Type": "text/xml"}
        )

    async def not_implemented(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        await self.respond(send, http.client.NOT_IMPLEMENTED, b"Not implemented")

    async def read_request_body(
        self, scope: HTTPScope, receive: ASGIReceiveCallable
    ) -> bytes:
        content_length = int(self.get_first_header(scope, "Content-Length") or 0)
        body = b""
        if content_length > 0:
            remaining = content_length
            while remaining > 0:
                message = await receive()
                remaining -= len(message["body"])
                body += message["body"]
        return body

    async def respond(
        self,
        send: ASGISendCallable,
        status: int,
        body: bytes | str | None = None,
        headers: dict[str, str] | None = None,
    ):
        body = b"" if body is None else body
        if isinstance(body, str):
            body = body.encode()
        headers = headers or {}
        if body:
            headers["Content-Length"] = str(len(body))
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
            }
        )

        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )

    async def send_dir_listing(
        self, send: ASGISendCallable, path: str, is_head: bool = False
    ):
        template = self.jinja_env.get_template("dir_listing.html")
        listing = [
            FileProps(info)
            for info in self.fs.scandir(path, namespaces=["details"])
            if info.name[0] != "."
        ]
        listing.sort()
        body = template.render(path=path, listing=listing)
        await self.respond(
            send,
            http.client.OK,
            body if not is_head else b"",
            {"Content-Type": "text/html; charset=utf-8"},
        )

    def compute_etag(self, info: Info) -> str:
        digest = md5()
        digest.update(info.name.encode())
        digest.update(str(info.size).encode())
        digest.update(info.modified.strftime("%Y-%m-%d %H:%M:%S").encode())
        return digest.hexdigest()

    def is_unmodified(self, scope: HTTPScope, etag: str) -> bool:
        if_none_match = self.get_first_header(scope, "If-None-Match")
        if if_none_match:
            for value in if_none_match.split(","):
                if value.strip() == "*" or value.strip() == etag:
                    return True
        else:
            return False

    async def send_file(
        self,
        scope: HTTPScope,
        receive: ASGIReceiveCallable,
        send: ASGISendCallable,
        path: str,
        is_head: bool = False,
    ):
        info: Info = self.fs.getinfo(path, ["details"])

        etag = self.compute_etag(info)

        if self.is_unmodified(scope, etag):
            await self.respond(send, 304)
            return

        mimetype, encoding = mimetypes.guess_type(path)
        if mimetype:
            content_type = mimetype
            if encoding:
                content_type += f"; charset={encoding}"
        else:
            content_type = "application/octet-stream"
        range = self.get_first_header(scope, "range")
        if range:
            start, end = self.parse_range(range)
            start = max(0, start)
            end = min(info.size - 1, end)
            content_length = end - start + 1
            status = http.client.PARTIAL_CONTENT
            headers = [
                (b"Content-Range", f"bytes {start}-{end}/{info.size}".encode()),
            ]
        else:
            start = 0
            end = info.size - 1
            content_length = info.size
            status = http.client.OK
            headers = []

        headers += [
            (b"Content-Type", content_type.encode()),
            (b"ETag", b'"' + etag.encode() + b'"'),
            (b"Content-Length", str(content_length).encode()),
            (
                b"Last-Modified",
                info.modified.strftime("%a, %d %b %Y %H:%M:%S GMT").encode(),
            ),
            (b"Accept-Ranges", b"bytes"),
        ]

        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": headers,
            }
        )

        if not is_head:

            with self.fs.open(path, "rb") as f:
                f.seek(start)
                remaining = content_length
                while remaining > 0:
                    chunk = f.read(min(remaining, CHUNK_SIZE))
                    remaining -= len(chunk)
                    await send(
                        {
                            "type": "http.response.body",
                            "body": chunk,
                            "more_body": True,
                        }
                    )

        await send(
            {
                "type": "http.response.body",
                "body": b"",
            }
        )

    def get_first_header(self, scope: HTTPScope, name: str) -> str | None:
        headers = scope.get("headers", [])
        for key, value in headers:
            if key.decode().lower() == name.lower():
                return str(value, "utf-8")
        return None

    def get_header(self, scope: HTTPScope, name: str) -> list[str]:
        headers = scope.get("headers", [])
        return [
            str(value, "utf-8")
            for key, value in headers
            if key.decode().lower() == name.lower()
        ]

    def parse_range(self, range: str) -> tuple[int, int]:
        match = re.match(r"bytes=(\d+)-(\d+)", range)
        assert match, f"Invalid range {range}"
        start, end = map(int, match.groups())
        return start, end


__all__ = ["DAVApp"]
