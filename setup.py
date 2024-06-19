import setuptools

setuptools.setup(
    name='qrsend',
    version='2.6.19',
    py_modules=['qrsend', 'http_server_range_patch'],
    entry_points={'console_scripts': ['qrsend = qrsend:main']},
    install_requires=['qrcode'],
    extras_require={'extras': ['netifaces']}
)
