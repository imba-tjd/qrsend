import setuptools

setuptools.setup(
    name='qrsend',
    version='2.6.1',
    py_modules=['qrsend'],
    entry_points={'console_scripts': ['qrsend = qrsend:main']},
    install_requires=['qrcode'],
    extras_require={'extras': ['netifaces']}
)
