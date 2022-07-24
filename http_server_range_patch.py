'''Add Range support for http.server.
https://github.com/python/cpython/pull/24228
https://github.com/python/cpython/commit/fb427255614fc1f740e7785554c1da8ca39116c2 （because #24228 is made before this）
Me: modified HTTP_BYTES_RANGE_HEADER and res.group("last") to support `Range: bytes=<range-start>-`
'''
import http.server
del http.server.__all__
from http.server import *

__all__ = ['patch']

def patch():
    SimpleHTTPRequestHandler.do_GET = do_GET
    SimpleHTTPRequestHandler.send_head = send_head
    SimpleHTTPRequestHandler.copyfile = copyfile


import re

HTTP_BYTES_RANGE_HEADER = re.compile(r"bytes=(?P<first>\d+)-(?P<last>\d+)?$")


def do_GET(self):
    """Serve a GET request."""
    f = self.send_head()
    if f:
        try:
            if "Range" in self.headers:
                res = HTTP_BYTES_RANGE_HEADER.match(string=self.headers.get("Range"))
                if res:
                    # self.copyfile(f, self.wfile, int(res.group("first")), int(res.group("last"))+1 if res.group("last") else None)
                    self.wfile._sock.sendfile(f, int(res.group("first")), int(res["last"])+1 if res["last"] else None)
            else:
                # self.copyfile(f, self.wfile)
                self.wfile._sock.sendfile(f)
        finally:
            f.close()


def send_head(self):
    """Common code for GET and HEAD commands.
    This sends the response code and MIME headers.
    Return value is either a file object (which has to be copied
    to the outputfile by the caller unless the command was HEAD,
    and must be closed by the caller under all circumstances), or
    None, in which case the caller has nothing further to do.
    """
    path = self.translate_path(self.path)
    f = None
    if os.path.isdir(path):
        parts = urllib.parse.urlsplit(self.path)
        if not parts.path.endswith('/'):
            # redirect browser - doing basically what apache does
            self.send_response(HTTPStatus.MOVED_PERMANENTLY)
            new_parts = (parts[0], parts[1], parts[2] + '/',
                            parts[3], parts[4])
            new_url = urllib.parse.urlunsplit(new_parts)
            self.send_header("Location", new_url)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        for index in "index.html", "index.htm":
            index = os.path.join(path, index)
            if os.path.exists(index):
                path = index
                break
        else:
            return self.list_directory(path)
    ctype = self.guess_type(path)
    # check for trailing "/" which should return 404. See Issue17324
    # The test for this was added in test_httpserver.py
    # However, some OS platforms accept a trailingSlash as a filename
    # See discussion on python-dev and Issue34711 regarding
    # parseing and rejection of filenames with a trailing slash
    if path.endswith("/"):
        self.send_error(HTTPStatus.NOT_FOUND, "File not found")
        return None
    try:
        f = open(path, 'rb')
    except OSError:
        self.send_error(HTTPStatus.NOT_FOUND, "File not found")
        return None

    try:
        fs = os.fstat(f.fileno())
        # Use browser cache if possible
        if ("If-Modified-Since" in self.headers
                and "If-None-Match" not in self.headers):
            # compare If-Modified-Since and time of last file modification
            try:
                ims = email.utils.parsedate_to_datetime(
                    self.headers["If-Modified-Since"])
            except (TypeError, IndexError, OverflowError, ValueError):
                # ignore ill-formed values
                pass
            else:
                if ims.tzinfo is None:
                    # obsolete format with no timezone, cf.
                    # https://tools.ietf.org/html/rfc7231#section-7.1.1.1
                    ims = ims.replace(tzinfo=datetime.timezone.utc)
                if ims.tzinfo is datetime.timezone.utc:
                    # compare to UTC datetime of last modification
                    last_modif = datetime.datetime.fromtimestamp(
                        fs.st_mtime, datetime.timezone.utc)
                    # remove microseconds, like in If-Modified-Since
                    last_modif = last_modif.replace(microsecond=0)

                    if last_modif <= ims:
                        self.send_response(HTTPStatus.NOT_MODIFIED)
                        self.end_headers()
                        f.close()
                        return None
        if "Range" in self.headers:
            res = HTTP_BYTES_RANGE_HEADER.match(string=self.headers["Range"])
            if res is None:
                self.send_error(code=HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
                                message="Range header is not a valid single part ranges")
                self.end_headers()
                f.close()
                return None
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Range", f"{self.headers['Range']}/{fs[6]}".replace('-/', f'-{fs[6]-1}/'))
            self.send_header("Content-Length", (int(res.group("last"))+1 if res.group("last") else fs[6])-int(res.group("first")))
        else:
            self.send_response(HTTPStatus.OK)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(fs[6]))
        self.send_header("Content-type", ctype)
        self.send_header("Last-Modified",
            self.date_time_string(fs.st_mtime))
        self.end_headers()
        return f
    except:
        f.close()
        raise


def copyfile(self, source, outputfile, start_byte=None, end_byte=None):
    if start_byte:
        source.seek(start_byte)
    # if end_byte:
    #     source.truncate(end_byte-start_byte)
    #     outputfile.write(source.read(-1 if not end_byte else end_byte-start_byte))
    # else:
    shutil.copyfileobj(source, outputfile)
