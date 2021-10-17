#!/usr/bin/env python3

from http.server import SimpleHTTPRequestHandler, HTTPServer
import random
import os
import socket
import sys
from shutil import make_archive
import argparse
import qrcode
from urllib.parse import quote
import atexit
import zipfile
import tempfile


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
    file_name: str
    debug: bool = False
    force_download: bool = True

    def do_GET(self):
        # the self.path will start by '/', we truncate it.
        if self.path[1:] != self.file_name:
            self.send_error(403) # access denied
        else:
            try:
                super().do_GET()
            except (ConnectionResetError, ConnectionAbortedError):
                pass

    def do_HEAD(self):
        if self.path[1:] != self.file_name:
            self.send_error(403)
        else:
            return super().do_HEAD()

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

    def log_message(self, format, *args):
        if self.debug:
            super().log_message(format, *args)

    @staticmethod
    def create(file_name, debug=False, force_download=True):
        # 类的__dict__无法赋值或update；super的init又是严格的，不允许含有未知的kwargs
        clazz = FileTransferServerHandler
        clazz.file_name = file_name
        clazz.debug = debug
        clazz.force_download = force_download
        return clazz


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
        return None


def print_qr_code(address):
    qr = qrcode.QRCode(border=2, error_correction=qrcode.ERROR_CORRECT_L)
    qr.add_data(address)
    qr.make(True)

    # print_tty() shows a better looking QR code. 但太大了
    qr.print_ascii(invert=True)


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
    PORT = int(kwargs["custom_port"]) if kwargs.get("custom_port") else random.randint(1024, 65535)
    LOCAL_IP = kwargs.get("ip_addr") or get_local_ip()

    if not os.path.exists(file_path):
        print("No such file or directory")
        sys.exit(1)

    # Variable to mark zip for deletion, if the user uses a folder as an argument
    abs_path = os.path.normpath(os.path.abspath(file_path))
    file_dir = os.path.dirname(abs_path)
    file_name = os.path.basename(abs_path)

    # change to directory which contains file
    os.chdir(file_dir)

    # Checking if given file name or path is a directory
    if os.path.isdir(file_name):
        try:
            # Zips the directory to tempdir
            os.chdir(tempfile.gettempdir())
            path_to_zip = make_archive(file_name, "zip", abs_path)
            file_name = os.path.basename(path_to_zip)
            atexit.register(lambda x: os.remove(x), file_name)
        except PermissionError:
            print("Permission denied")
            sys.exit(1)

    # Tweaking file_name to make a perfect url
    # file_name = file_name.replace(" ", "%20")
    file_name = quote(file_name)

    handler = FileTransferServerHandler.create(
        file_name,
        debug=kwargs.get('debug', False),
        force_download=not kwargs.get("no_force_download", False)
    )
    httpd = HTTPServer(("", PORT), handler)

    # This is the url to be encoded into the QR code
    address = "http://" + str(LOCAL_IP) + ":" + str(PORT) + "/" + file_name

    print(address)
    print_qr_code(address)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()

    sys.exit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('file_path', help="path that you want to transfer.")
    parser.add_argument('--debug', '-d', action="store_true", default=False, help="show the encoded url.")
    parser.add_argument('--port', '-p', dest="port", help="use a custom port")
    parser.add_argument('--ip_addr', dest="ip_addr", choices=get_local_ips_available(), help="specify IP address")
    parser.add_argument("--no-force-download", '--nfd', default=False, action="store_true",
        help="Allow browser to handle the file processing instead of forcing it to download."
    )
    args = parser.parse_args()

    # We are disabling the cursor so that the output looks cleaner
    cursor(False)
    atexit.register(clean_before_exit)

    # shutil.make_archive()默认会用DEFLATED算法，不需要
    zipfileinit = zipfile.ZipFile.__init__
    def zipfileinit_stub(*args, **kwargs): zipfileinit(*args, **kwargs | {'compression': zipfile.ZIP_STORED})
    zipfile.ZipFile.__init__ = zipfileinit_stub

    start_download_server(
        args.file_path,
        debug=args.debug,
        custom_port=args.port,
        ip_addr=args.ip_addr,
        no_force_download=args.no_force_download
    )


if __name__ == "__main__":
    main()
    # start_download_server('.venv', custom_port=8000)
