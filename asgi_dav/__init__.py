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

from urllib.parse import unquote, urlparse, parse_qs
from fs.base import FS
import fs.errors
from jinja2 import Environment, PackageLoader
import humanize
import re
from xml.dom.minidom import parseString, Document
from hashlib import md5
import http.client  # for HTTP status codes constants
from .utils import concat_uri, make_data_url, get_parent_href
from .props import FileProps, PropfindResponseBuilder
from .events import *

# ------------------------------------------------------------------------------
__version__ = "0.1.0"
__author__ = "Julien Rialland"


# ------------------------------------------------------------------------------
# The size of the chunks to read from the files
CHUNK_SIZE = 128 * 1024

# The maximum number of items to display in a directory listing
MAX_DIR_LISTING = 10000


# ------------------------------------------------------------------------------
class DAVApp(EventSupport):
    """
    An ASGI application that handles WebDAV requests
    """

    def __init__(self, fs: FS):
        """
        Create a new DAVApp instance
        :param fs: the filesystem to use
        """
        super().__init__()
        assert fs, "fs is required"
        self.fs = fs
        self.jinja_env = Environment(loader=PackageLoader(__name__, "templates"))
        self.jinja_env.globals["make_data_url"] = make_data_url
        self.jinja_env.globals["naturalsize"] = humanize.naturalsize
        self.jinja_env.globals["get_parent_href"] = get_parent_href
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

    def _get_path_and_href(self, scope: HTTPScope) -> tuple[str, str]:
        root_path = scope.get("root_path", "")
        path = scope["path"][len(root_path) :]
        if path == "":
            path = "/"
        return path, concat_uri(root_path, path)

    async def copy_or_move(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        is_copy = scope["method"] == "COPY"
        path, href = self._get_path_and_href(scope)
        destination = self.get_first_header(scope, "Destination")
        if destination is None:
            await self.respond(send, http.client.BAD_REQUEST, b"Bad Request")
            return

        # destination is an absolute URI, so we need to extract the path
        destination = unquote(urlparse(destination).path)
        root_path = scope.get("root_path", "")
        destination = destination[len(root_path) :]
        if destination == "":
            destination = "/"

        overwrite = self.get_first_header(scope, "Overwrite") == "T"
        evtname, evt = None, None
        try:
            if is_copy:
                if self.fs.isdir(path):
                    self.fs.copydir(path, destination, create=True)
                    evtname, evt = "directory.copied", DirectoryCopiedEvent(
                        path=path, dest_path=destination
                    )
                else:
                    self.fs.copy(path, destination, overwrite=overwrite)
                    evtname, evt = "file.copied", FileCopiedEvent(
                        path=path, dest_path=destination
                    )
            else:
                if self.fs.isdir(path):
                    self.fs.movedir(path, destination, create=True)
                    evtname, evt = "directory.moved", DirectoryMovedEvent(
                        path=path, dest_path=destination
                    )
                else:
                    self.fs.move(path, destination, overwrite=overwrite)
                    evtname, evt = "file.moved", FileRenamedEvent(
                        path=path, dest_path=destination
                    )

        except fs.errors.FileExpected:
            await self.respond(send, http.client.BAD_REQUEST, b"Bad Request")
            return
        except fs.errors.ResourceNotFound:
            await self.respond(send, http.client.NOT_FOUND, b"Not found")
            return
        except fs.errors.DestinationExists:
            await self.respond(send, http.client.CONFLICT, b"Conflict")
            return

        if is_copy:
            await self.emit(evtname, evt)
            await self.respond(send, http.client.CREATED, b"Created")
        else:

            await self.respond(send, http.client.NO_CONTENT)

    async def get_or_head(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        is_head = scope["method"] == "HEAD"
        path, href = self._get_path_and_href(scope)
        if not self.fs.exists(path):
            await self.respond(send, http.client.NOT_FOUND, b"Not found")
            return
        if self.fs.isdir(path):
            query = parse_qs(scope["query_string"].decode())
            if query.get("propfind"):
                await self.propfind(scope, receive, send)
            else:
                await self.send_dir_listing(send, path, href, is_head=is_head)
        else:

            await self.send_file(
                scope,
                send,
                path,
                FileProps(self.fs.getinfo(path, ["details"]), href),
                is_head=is_head,
            )

    async def put(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        path, href = self._get_path_and_href(scope)

        if self.fs.isdir(path):
            await self.respond(send, http.client.METHOD_NOT_ALLOWED)
            return

        remaining = int(self.get_first_header(scope, "Content-Length") or 0)

        with self.fs.open(path, "wb" if self.fs.isfile(path) else "xb") as f:
            while remaining > 0:
                message: HTTPRequestEvent = await receive()  # type: ignore
                if message["type"] == "http.disconnect":
                    break
                chunk = message["body"]
                f.write(chunk)
                remaining -= len(chunk)
            await self.emit("file.uploaded", FileUploadedEvent(path=path))
        await self.respond(send, http.client.CREATED)

    async def delete(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        path, href = self._get_path_and_href(scope)
        if not self.fs.exists(path):
            await self.respond(send, http.client.NOT_FOUND)
            return
        is_dir = self.fs.isdir(path)
        if is_dir:
            self.fs.removedir(path)
            await self.emit("directory.deleted", DirectoryDeletedEvent(path=path))
        else:
            self.fs.remove(path)
            await self.emit("file.deleted", FileDeletedEvent(path=path))
        await self.respond(send, http.client.NO_CONTENT)

    async def mkcol(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        path, href = self._get_path_and_href(scope)
        if self.fs.exists(path):
            await self.respond(send, 405, b"Method Not Allowed")
            return

        self.fs.makedirs(path)
        await self.respond(send, http.client.CREATED)
        await self.emit("directory.created", DirectoryCreatedEvent(path=path))

    async def propfind(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        path, href = self._get_path_and_href(scope)

        if not self.fs.exists(path):
            await self.respond(send, http.client.NOT_FOUND, b"Not found")
            return

        depth = self.get_first_header(scope, "Depth")
        if not depth:
            depth = "1"

        builder = PropfindResponseBuilder()
        if path == "/":
            builder.add_response(FileProps(self.fs.getinfo("/", ["details"]), href))
        else:
            builder.add_response(
                FileProps(self.fs.getinfo(path, ["details"]), get_parent_href(href))
            )

        if depth == "0":
            pass
        elif depth == "1" or depth is None:
            fprops = [
                FileProps(info, href)
                for info in self.fs.scandir(path, namespaces=["details"])
                if info.name[0] != "."
            ]
            fprops.sort()
            for fileprop in fprops:
                builder.add_response(fileprop)
        elif depth == "infinity":
            await self.respond(send, http.client.NOT_IMPLEMENTED, b"Not implemented")
            return
        else:
            await self.respond(send, http.client.BAD_REQUEST, b"Bad Request")
            return

        await self.respond(
            send,
            http.client.MULTI_STATUS,
            builder.to_xml(),
            {"Content-Type": "text/xml"},
        )

    async def proppatch(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        """
        Handle PROPPATCH requests : parse propstat xml, change props, and return a multistatus response
        """
        raw_path = scope["path"]
        path, href = self._get_path_and_href(scope)

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
                <{dav_ns}:href>{raw_path}</{dav_ns}:href>
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
        self, send: ASGISendCallable, path: str, href: str, is_head: bool = False
    ):
        template = self.jinja_env.get_template("dir_listing.html")
        listing = [
            FileProps(info, href)
            for info in self.fs.scandir(path, namespaces=["details"])
            if info.name[0] != "."
        ]
        listing.sort()
        body = template.render(path=path, href=href, listing=listing)
        await self.respond(
            send,
            http.client.OK,
            body if not is_head else b"",
            {"Content-Type": "text/html; charset=utf-8"},
        )

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
        send: ASGISendCallable,
        path: str,
        fp: FileProps,
        is_head: bool = False,
    ):
        if self.is_unmodified(scope, fp.etag):
            await self.respond(send, 304)
            return

        range = self.get_first_header(scope, "range")
        if range:
            start, end = self.parse_range(range)
            start = max(0, start)
            end = min(fp.size - 1, end)
            content_length = end - start + 1
            status = http.client.PARTIAL_CONTENT
            headers = [
                (b"Content-Range", f"bytes {start}-{end}/{fp.size}".encode()),
            ]
        else:
            start = 0
            end = fp.size - 1
            content_length = fp.size
            status = http.client.OK
            headers = []

        headers += [
            (b"Content-Type", fp.content_type.encode()),
            (b"ETag", b'"' + fp.etag.encode() + b'"'),
            (b"Content-Length", str(content_length).encode()),
            (
                b"Last-Modified",
                fp.lastmodified.encode(),
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

        await self.emit("file.downloaded", FileDownloadedEvent(path=path))

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
