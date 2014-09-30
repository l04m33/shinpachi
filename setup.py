import os
import ast
from setuptools import setup


PACKAGE_NAME = 'shinpachi'


def load_description(fname):
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, fname)) as f:
        return f.read().strip()


def get_version(fname):
    with open(fname) as f:
        source = f.read()
    module = ast.parse(source)
    for e in module.body:
        if isinstance(e, ast.Assign) and \
                len(e.targets) == 1 and \
                e.targets[0].id == '__version__' and \
                isinstance(e.value, ast.Str):
            return e.value.s
    raise RuntimeError('__version__ not found')


setup(
    name=PACKAGE_NAME,
    version=get_version('{}/version.py'.format(PACKAGE_NAME)),
    description='HTTP proxy and network protocol debugger',
    long_description=load_description('readme.rst'),
    classifiers=[
        'Programming Language :: Python :: 3.4',
        'License :: OSI Approved :: MIT License',
    ],
    keywords='http proxy networking protocol debugger',
    author='Kay Zheng',
    author_email='l04m33@gmail.com',
    license='MIT',
    zip_safe=False,
    install_requires=[
        'pyzmq >= 14.3.1',
        'aiohttp >= 0.9.0',
        'jinja2 >= 2.7.3',
        'rauth >= 0.7.0',
        'asyncio-redis >= 0.13.3',
    ],
    extras_require={
        'dev': []
    },
    entry_points='''
    [console_scripts]
    {0} = {0}:main
    '''.format(PACKAGE_NAME),
)
