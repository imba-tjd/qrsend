# QR Send

This is a fork of https://github.com/sdushantha/qr-filetransfer.

* I don't need upload and auth
* I want a shorter exe name
* I want a smaller QR code pattern
* I don't need DEFLATED when make_archive because it's inefficient
* I changed the code's filename so it makes no sense to keep upstream's commit history
* When `make_archive()`, it's stored into the temp dir. So that it won't overwrite files that have the same name, and it's OK to shutdown ungracefully
* Implemented a function(`create_sendto()`) to add *qrsend.bat* to *SendTo* context menu, though won't work when selecting muiltiple files

## Usage

```cmd
pip install git+https://github.com/imba-tjd/qrsend  # pipx is preferred
qrsend file.txt/folder
```

## Won't fix

* In memory zip. The logic difference is too large. http.server works by reading local files. And according to the docs, ZipFile only accept path-like-obj now rather than file-like-obj in Py2, let alone make_archive.
