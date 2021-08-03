# QR Send

This is a fork of https://github.com/sdushantha/qr-filetransfer.

* I don't need upload and auth
* I want a shorter exe name
* I want a smaller QR code pattern
* I don't need DEFLATED when making archives because it's inefficient
* I changed the code's filename so it makes no sense to keep upstream's commit history

## Usage

```cmd
pip install git+https://github.com/imba-tjd/qrsend  # pipx is preferred
qrsend file.txt/folder
```

## Won't fix

* Only one connection at a time when downlaoding
* In memory zip. The logic difference is too large. http.server works by reading local files. And according to the docs, ZipFile only accept path-like-obj now rather than file-like-obj in Py2, let alone make_archive.
* Accept-Ranges: bytes. http.server doesn't support yet，see https://bugs.python.org/issue42643

## TODO

* 把zip放到临时文件夹里。现在会放到目标文件的平行目录里
* 如果已经存在那个名字的zip，现在会自动删掉。在实现上面那个后自动解决
* 非正常退出不会删除临时zip。在实现上面那个后自动解决
