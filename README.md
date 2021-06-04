# QR Send

This is a fork of https://github.com/sdushantha/qr-filetransfer, based on 47e170e.

* I don't need upload and auth
* I want a shorter exe name
* I want a smaller QR code pattern

I changed the code's filename so it makes no sense to keep upstream's commit history.

## Usage

```cmd
pip install git+https://github.com/imba-tjd/qrsend  # pipx is preferred
qrsend file.txt
```

## TODO

* In memory zip：与现在的逻辑差别有点大，看情况实现
* 把zip放到临时文件夹里。现在会放到目标文件的平行目录里
