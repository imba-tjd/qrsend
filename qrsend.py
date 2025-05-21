from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer, HTTPStatus
import os
import socket
import sys
from shutil import make_archive
import argparse
from urllib.parse import quote, urlsplit, urlunsplit # Added urlsplit, urlunsplit
import shutil # For rmtree, just in case, though not planned for use
import atexit
import zipfile
import tempfile
import qrcode
import re # Added re
from datetime import datetime, timezone # Added datetime, timezone
from email.utils import parsedate_to_datetime # Added email.utils.parsedate_to_datetime
# Regex for parsing the Range header: bytes=<first>-<last>?
HTTP_BYTES_RANGE_HEADER = re.compile(r"bytes=(?P<first>\d+)-(?P<last>\d+)?$")


def is_supported_env():
    return sys.platform != 'win32' or 'WT_SESSION' in os.environ


def cursor(status: bool):
    """
    Enable or disable the cursor in the terminal
    """
    # If you dont understand how this one line if statement works, check out
    # this link: https://stackoverflow.com/a/2802748/9215267
    #
    # Hide cursor: \033[?25h
    # Enable cursor: \033[?25l
    if is_supported_env():
        print("\033[?25" + ("h" if status else "l"), end="")


def clean_before_exit():
    """
    These are some things that need to be done before exiting so that the user
    does have any problems after they have run qr-filetransfer
    """

    # Enable the cursor
    cursor(True)

    # Returning the cursor to home...
    print("\r", end="")

    # ...and printing "nothing" over it to hide ^C when
    # CTRL+C is pressed
    print("  ")


class FileTransferServerHandler(SimpleHTTPRequestHandler):
    def __init__(self, file_name: str, debug: bool = False, force_download: bool = True, *args, **kwargs):
        self.file_name = file_name # Quoted name for URL matching
        self.debug = debug
        self.force_download = force_download
        # The `directory` argument was added in Python 3.7.
        # SimpleHTTPRequestHandler uses os.getcwd() if directory is None when CWD is set before server init.
        # For clarity, explicitly pass the CWD set by start_download_server.
        # The CWD is set by start_download_server before handler is instantiated.
        super().__init__(*args, directory=os.getcwd(), **kwargs)

    def do_GET(self):
        """Serve a GET request with Range support."""
        f = self.send_head()
        if f:
            try:
                range_header = self.headers.get("Range")
                if range_header:
                    res = HTTP_BYTES_RANGE_HEADER.match(string=range_header)
                    if res: # Valid Range header
                        first_byte = int(res.group("first"))
                        # Determine last_byte based on whether it's specified in the Range header
                        # os.fstat(f.fileno()).st_size is used if last is not present.
                        # This logic is now inside send_head which sets Content-Length.
                        # Here we just need to send the appropriate part of the file.
                        # For sendfile, offset is first_byte.
                        # count is (last_byte - first_byte + 1), or None for "to the end".
                        # The Content-Length header calculated in send_head determines how much client expects.
                        
                        # Get file size to calculate count if last part of range is not specified
                        file_size = os.fstat(f.fileno()).st_size
                        if res.group("last"):
                            count = int(res.group("last")) - first_byte + 1
                        else:
                            count = file_size - first_byte
                        
                        # self.wfile._sock.sendfile is specific to sockets, might not work with BytesIO for tests
                        # but is efficient for real file transfers.
                        self.wfile._sock.sendfile(f, first_byte, count)
                else: # No Range header, send whole file
                    self.wfile._sock.sendfile(f)
            finally:
                f.close()

    def do_HEAD(self):
        """Serve a HEAD request by calling send_head and closing the file."""
        f = self.send_head()
        if f:
            f.close()
            
    def send_head(self):
        """Common code for GET and HEAD commands supporting Range requests.
        This sends the response code and MIME headers.
        Return value is either a file object (which has to be copied
        to the outputfile by the caller unless the command was HEAD,
        and must be closed by the caller under all circumstances), or
        None, in which case the caller has nothing further to do.
        """
        # CUSTOM CHECK FOR QRSEND: Ensure only the specified file is accessed
        # self.path starts with '/', self.file_name (URL component) does not.
        if self.path[1:] != self.file_name:
            self.send_error(HTTPStatus.FORBIDDEN, "Access denied: URL path does not match expected file name.")
            return None

        # translate_path uses os.getcwd() (set via directory in __init__) and self.path
        path = self.translate_path(self.path)
        # For qrsend, CWD is set to where the target file (file_name) resides.
        # translate_path unquotes self.path and joins with CWD.
        # This should correctly resolve to the target file.

        f = None
        # QRSend specific: we only serve files, not directories.
        if os.path.isdir(path):
            self.send_error(HTTPStatus.FORBIDDEN, "Directory listing is not allowed.")
            return None
        
        ctype = self.guess_type(path) # Uses our overridden guess_type for force_download

        # Original patch had check for path.endswith("/"), but os.path.isdir should handle it mostly.
        # If it's not a dir, and ends with /, it's likely a malformed request for a file.
        if path.endswith("/"):
            self.send_error(HTTPStatus.NOT_FOUND, "File not found (path ends with /)")
            return None
            
        try:
            f = open(path, 'rb')
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found (OSError opening file)")
            return None

        try:
            fs = os.fstat(f.fileno())
            file_size = fs.st_size
            # Cache control (If-Modified-Since)
            if ("If-Modified-Since" in self.headers
                    and "If-None-Match" not in self.headers):
                try:
                    ims = parsedate_to_datetime(self.headers["If-Modified-Since"])
                except (TypeError, IndexError, OverflowError, ValueError): pass # ignore ill-formed values
                else:
                    if ims.tzinfo is None: ims = ims.replace(tzinfo=timezone.utc)
                    if ims.tzinfo is timezone.utc:
                        last_modif = datetime.fromtimestamp(fs.st_mtime, timezone.utc)
                        last_modif = last_modif.replace(microsecond=0)
                        if last_modif <= ims:
                            self.send_response(HTTPStatus.NOT_MODIFIED)
                            self.end_headers()
                            f.close()
                            return None
            
            range_header = self.headers.get("Range")
            if range_header:
                res = HTTP_BYTES_RANGE_HEADER.match(string=range_header)
                if res is None: # Invalid Range header format
                    self.send_error(code=HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
                                    message="Range header is not a valid single part range.")
                    self.end_headers()
                    f.close()
                    return None
                
                first_byte = int(res.group("first"))
                last_byte_str = res.group("last")
                
                if last_byte_str is not None:
                    last_byte = int(last_byte_str)
                else: # No end byte specified, means to the end of the file
                    last_byte = file_size - 1
                
                # Validate range
                if first_byte >= file_size or last_byte >= file_size or first_byte > last_byte:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{file_size}")
                    self.send_header("Content-Length", "0") # No body for invalid range
                    self.end_headers()
                    f.close()
                    return None

                self.send_response(HTTPStatus.PARTIAL_CONTENT)
                self.send_header("Content-Range", f"bytes {first_byte}-{last_byte}/{file_size}")
                content_length = last_byte - first_byte + 1
                self.send_header("Content-Length", str(content_length))
            else: # No Range header
                self.send_response(HTTPStatus.OK)
                self.send_header("Accept-Ranges", "bytes") # Inform client that ranges are supported
                self.send_header("Content-Length", str(file_size))
            
            self.send_header("Content-type", ctype)
            self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
            self.end_headers()
            return f
        except Exception: # Catch all other errors during header sending
            f.close() # Ensure file is closed on error
            raise

    def guess_type(self, path):
        """Add ability to force download of files.

        Args:
            path: File path to serve.

        Returns:
            Content-Type as a string.
        """
        if self.force_download:
            return "application/octet-stream"

        return super().guess_type(path)

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError):
            pass

    def log_message(self, format, *args):
        if self.debug:
            super().log_message(format, *args)


def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 80))
            return s.getsockname()[0]
    except OSError:
        print("Network is unreachable")
        sys.exit(1)


def get_local_ips_available():
    """Get a list of all local IPv4 addresses except localhost"""
    try:
        import netifaces
        ips = []
        for iface in netifaces.interfaces():
            ips.extend([x["addr"] for x in netifaces.ifaddresses(iface).get(netifaces.AF_INET, []) if x and "addr" in x])

        return [x for x in sorted(ips) if not x.startswith('127.')]

    except ModuleNotFoundError:
        print("Warning: 'netifaces' module not found. IP address choice list will be empty.", file=sys.stderr)
        print("Consider installing 'netifaces' (e.g., 'pip install netifaces') to see available IP addresses, or specify an IP manually.", file=sys.stderr)
        return []


def print_qr_code(address):
    qr = qrcode.QRCode(border=2, error_correction=qrcode.ERROR_CORRECT_L)
    qr.add_data(address)
    qr.make(True)

    # print_tty() shows a better looking QR code. 但太大了
    qr.print_ascii(invert=True)


def create_zip_with_stored_compression(base_name: str, root_dir: str) -> str:
    """
    Creates a zip file in tempfile.gettempdir() with ZIP_STORED compression.
    Args:
        base_name: The desired name of the zip file (e.g., "myarchive_dir").
                   The actual filename will be base_name + ".zip".
        root_dir: The directory to be zipped (e.g., "/path/to/myarchive_dir").
    Returns:
        The full path to the created zip file.
    """
    zip_name = base_name + ".zip"
    zip_path = os.path.join(tempfile.gettempdir(), zip_name)

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zf:
        for foldername, subfolders, filenames in os.walk(root_dir):
            for filename in filenames:
                absolute_path = os.path.join(foldername, filename)
                # arcname should be relative to the root_dir being zipped
                arcname = os.path.relpath(absolute_path, root_dir)
                zf.write(absolute_path, arcname)
    return zip_path


def start_download_server(file_path: str, **kwargs):
    """Start the download web server.

    This function will display a QR code to the terminal that directs a user's
    cell phone to browse to this web server.  Once connected, the web browser
    will download the file, or display the file in the browser depending on the
    options set.

    Args:
        file_path: The file path to serve.

    Keyword Arguments:
        custom_port (str): String indicating which custom port the user wants to use.
        ip_addr (str): The IP address to bind web server to.
        no_force_download (bool): Allow web browser to handle the file served
            instead of forcing the browser to download it.
    """
    # kwargs里有custom_port，只不过值为None，不能用.get(xx,xx)，那样就取到None了
    PORT = int(kwargs["custom_port"]) if kwargs.get("custom_port") else 0
    LOCAL_IP = kwargs.get("ip_addr") or get_local_ip()

    if not os.path.exists(file_path):
        print("No such file or directory")
        sys.exit(1)

    abs_path = os.path.normpath(os.path.abspath(file_path))
    full_path_of_file_to_serve: str
    serving_directory: str
    file_name: str # Name of the file as it appears in the URL and on disk in serving_directory

    if os.path.isdir(abs_path):
        try:
            base_name_of_dir = os.path.basename(abs_path)
            # Create the zip file in the system's temporary directory
            path_to_zip = create_zip_with_stored_compression(base_name_of_dir, abs_path)
            
            file_name = os.path.basename(path_to_zip)
            serving_directory = tempfile.gettempdir()
            full_path_of_file_to_serve = path_to_zip # This is the absolute path to the zip
            
            # Register the full path of the zip file for deletion at exit
            atexit.register(os.remove, full_path_of_file_to_serve)
        except PermissionError:
            print("Permission denied to create or access zip file.")
            sys.exit(1)
        except Exception as e:
            print(f"Error creating zip file: {e}")
            sys.exit(1)
    else: # It's a file
        file_name = os.path.basename(abs_path)
        serving_directory = os.path.dirname(abs_path)
        full_path_of_file_to_serve = abs_path

    # Change to the directory from which the file will be served.
    # SimpleHTTPRequestHandler serves files relative to the current working directory.
    try:
        os.chdir(serving_directory)
    except FileNotFoundError:
        print(f"Error: Serving directory not found: {serving_directory}")
        sys.exit(1)
    except Exception as e:
        print(f"Error changing to serving directory '{serving_directory}': {e}")
        sys.exit(1)
        
    # Ensure the file (now in CWD or it's the zip file name in CWD) exists and is readable.
    # The actual file opening/closing for serving is handled by the HTTP server handler.
    if not os.path.isfile(file_name) or not os.access(file_name, os.R_OK):
        print(f"Error: File not found or not readable in serving directory: {file_name}")
        sys.exit(1)

    # Tweaking file_name to make a perfect url
    # file_name = file_name.replace(" ", "%20")
    file_name = quote(file_name)

    # Define the arguments for the handler
    handler_file_name = file_name
    handler_debug = kwargs.get('debug', False)
    handler_force_download = not kwargs.get("no_force_download", False)

    # Create the handler factory function
    def handler_factory(*args, **factory_kwargs):
        return FileTransferServerHandler(handler_file_name, handler_debug, handler_force_download, *args, **factory_kwargs)

    httpd = ThreadingHTTPServer(("", PORT), handler_factory)

    # This is the url to be encoded into the QR code
    address = f"http://{str(LOCAL_IP)}:{str(httpd.server_port)}/{file_name}"

    print(address)
    print_qr_code(address)

    with httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass

    sys.exit()


def create_sendto():
    '''Add qrsend.bat to *SendTo* context menu'''
    with open(os.path.expandvars('%AppData%') + '\\Microsoft\\Windows\\SendTo\\qrsend.bat', 'x') as f:
        f.write('@echo off\nqrsend %*')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('file_path', help="path that you want to transfer.")
    parser.add_argument('--debug', '-d', action="store_true", help="show the encoded url.")
    parser.add_argument('--port', '-p', help="use a custom port")
    parser.add_argument('--ip_addr', choices=get_local_ips_available(), help="specify IP address")
    parser.add_argument("--no-force-download", '--nfd', action="store_true",
        help="Allow browser to handle the file processing instead of forcing it to download."
    )
    args = parser.parse_args()

    # We are disabling the cursor so that the output looks cleaner
    cursor(False)
    atexit.register(clean_before_exit)

    # import http_server_range_patch # Removed
    # http_server_range_patch.patch() # Removed

    start_download_server(
        args.file_path,
        debug=args.debug,
        custom_port=args.port,
        ip_addr=args.ip_addr,
        no_force_download=args.no_force_download
    )


if __name__ == "__main__":
    main()
