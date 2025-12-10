# QR Send

This is a fork of https://github.com/sdushantha/qr-filetransfer.

* I don't need upload and auth
* I want a shorter exe name
* I want a smaller QR code pattern
* I don't need DEFLATED when make_archive because it's inefficient
* I changed the code's filename so it makes no sense to keep upstream's commit history
* When `make_archive()`, it's stored into the temp dir. So that it won't overwrite files that have the same name, and it's OK to shutdown ungracefully
* Added a `create_sendto()` function to add *qrsend.bat* to *SendTo* context menu, though won't work when selecting muiltiple files
* Added a monkey-patch to make `http.server` support `Accept-Ranges: bytes`
* Added a read(shared) lock on file so that it won't be deleted while qrsend is open

## Usage

```cmd
pip install git+https://github.com/imba-tjd/qrsend  # pipx is preferred
qrsend file.txt/folder
```

## Won't fix

* In memory zip. The logic difference is too large. http.server works by reading local files. And according to the docs, ZipFile only accept path-like-obj now, rather than file-like-obj in Py2, let alone make_archive.
* Incorrect range sent by bad client, for example the requested end_bytes is larger than the actual file size.

## Details about ranges support

Originally proposed by https://bugs.python.org/issue42643 and https://github.com/python/cpython/pull/24228 but it has some fatal errors.

* not support *no `<range-end>`*
* reads all remaining content into memory in a single call
* logic error when computing the range of bytes

These has been fixed in my patch.

1. I started by ignoring `end_byte` and let the client to guarantee not to excessive read. Tested that curl and FF works.
2. I tried to use `source.truncate()`. But it turns out an `io.UnsupportedOperation`. The reason is that *truncate* will modify the actual file on disk, and mode 'r' protects that.
3. `wfile._sock.sendfile()` is the perfect solution, except `_sock` isn't public.\
    According to https://github.com/python/cpython/blob/main/Lib/socketserver.py, wfile is a *file obj* determined by *wbufsize*. When it == 0, wfile is `_SocketWriter` (added in https://bugs.python.org/issue26721), otherwise it's created by `socket.makefile()`. I think HTTPServer is not likely to change wbufsize, so it's ok to use `_sock`.
4. On windows, the sendfile isn't actually the zero-copy syscall. Windows has another API that needs to be adopted via https://github.com/python/cpython/pull/112337. I managed to invoke it via ctypes.

In the future, https://github.com/python/cpython/pull/118949 is more likely to be merged.
