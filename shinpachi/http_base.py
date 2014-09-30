import asyncio
import aiohttp
import os
import mimetypes
import importlib
import inspect
import re
import functools
from http import cookies
from urllib import parse as urlparse
from .io import AsyncFileWrapper


__all__ = ['HttpPathHandler', 'StaticPathHandler', 'PathMatcher',
           'path', 'scan_handlers']


class HttpPathHandler(object):
    def __init__(self, protocol, response_cls=aiohttp.Response, **kw_args):
        self.protocol = protocol
        self.response_cls = response_cls
        self.kw = kw_args

    def extract_cookies(self, message):
        ck = cookies.SimpleCookie()
        ck_strs = message.headers.getall('COOKIE', ())
        for cs in ck_strs:
            ck.load(cs)
        return ck

    def set_cookies(self, response, cookies_to_set, max_age):
        cookie = cookies.SimpleCookie()
        for k, v in cookies_to_set:
            cookie[k] = v

        key_cookie_str = '{}; path=/; max-age={}'.format(
            cookie.output(header='', sep=';').strip(), max_age)

        response.add_header('Set-Cookie', key_cookie_str)

    def clear_cookies(self, response, cookies_to_clear):
        cookie = cookies.SimpleCookie()
        for c in cookies_to_clear:
            cookie[c] = ''

        key_cookie_str = '{}; path=/; max-age={}'.format(
            cookie.output(header='', sep=';').strip(), 0)

        response.add_header('Set-Cookie', key_cookie_str)

    @asyncio.coroutine
    def handle(self, message, payload):
        cookie = self.extract_cookies(message)
        auth_result, user = yield from self.authenticated(cookie)
        if auth_result:
            response = yield from self.do_handle(message, payload, user)
            return response
        else:
            raise aiohttp.HttpErrorException(403)

    @asyncio.coroutine
    def do_handle(self, message, payload, user):
        response = self.start_response(204, message.version)
        response.send_headers()
        return response

    def redirect_to(self, path, message, set_cookies=None, clear_cookies=None):
        response = self.start_response(302, message.version)
        if set_cookies is not None:
            self.set_cookies(response, set_cookies, 60*60*24*7)
        if clear_cookies is not None:
            self.clear_cookies(response, clear_cookies)
        response.add_header('Location', path)
        response.send_headers()
        return response

    def start_response(self, status, version):
        response = self.response_cls(self.protocol.writer,
                                     status, http_version=version)
        return response

    @asyncio.coroutine
    def authenticated(self, cookie):
        future = asyncio.Future()
        future.set_result((True, None))
        return future

    def close(self):
        pass


class StaticPathHandler(HttpPathHandler):
    @asyncio.coroutine
    def do_handle(self, message, payload, user):
        url_path_prefix = self.kw['url_path_prefix']
        root_path = self.kw['root_path']

        path, qs = urlparse.splitquery(message.path[len(url_path_prefix):])
        path = root_path + path
        if not self.kw['resource_provider'].has_resource(path):
            raise aiohttp.HttpErrorException(404)

        try:
            fstream = self.kw['resource_provider'].get_resource_stream(
                self.kw['resource_mgr'], path)
        except IsADirectoryError:
            raise aiohttp.HttpErrorException(404)

        try:
            file_size = os.path.getsize(
                self.kw['resource_provider'].get_resource_filename(
                    self.kw['resource_mgr'], path))
            content_range = self.get_req_range(
                message.headers.getall('RANGE', ()), file_size)
            content_length = content_range[1] - content_range[0] + 1
            if content_range[0] == 0 and content_length >= file_size:
                content_range = None
        except FileNotFoundError:
            file_size = None
            content_length = None
            content_range = None

        if content_range is None:
            response = self.start_response(200, message.version)
        else:
            response = self.start_response(206, message.version)
            response.add_header('Content-Range',
                                'bytes {}-{}/{}'
                                .format(content_range[0],
                                        content_range[1],
                                        file_size))

        content_type, encoding = mimetypes.guess_type(path)
        if content_type is None:
            content_type = 'application/octet-stream'
        response.add_header('Content-Type', content_type)

        if content_length is not None:
            response.add_header('Content-Length', str(content_length))

        response.send_headers()

        async_stream = AsyncFileWrapper(fileobj=fstream)
        if content_range is not None and content_range[0] > 0:
            async_stream.seek(content_range[0])
        self.static_fstream = async_stream
        if content_range is not None:
            yield from async_stream.copy_to(response, content_range[1] - content_range[0] + 1)
        else:
            yield from async_stream.copy_to(response)
        async_stream.close()
        del self.static_fstream

        return response

    def close(self):
        if hasattr(self, 'static_fstream'):
            self.static_fstream.close()

    def get_req_range(self, range_vals, file_size):
        ranges = []
        for v in range_vals:
            ranges += self.parse_ranges(v, file_size)
        first = file_size - 1
        last = 0
        for f, l in ranges:
            first = f if f < first else first
            last = l if l > last else last
        if first >= 0 and first <= last and last < file_size:
            return (first, last)
        else:
            return (0, file_size - 1)

    def parse_ranges(self, range_spec, file_size):
        try:
            range_unit, ranges = range_spec.split('=')
        except ValueError:
            return []
        if range_unit.strip().lower() != 'bytes':
            return []

        rlist = ranges.strip().split(',')
        parsed_ranges = []
        for r in rlist:
            try:
                first, last = r.strip().split('-')
            except ValueError:
                continue
            if first == '' and last.isdigit():
                suffix_len = int(last)
                parsed_ranges.append((file_size - suffix_len, file_size - 1))
            elif first.isdigit() and last == '':
                start_index = int(first)
                parsed_ranges.append((start_index, file_size - 1))
            elif first.isdigit() and last.isdigit():
                parsed_ranges.append((int(first), int(last)))
        return parsed_ranges


class PathMatcher(object):
    def __init__(self, handlers):
        self.handlers = handlers

    def match(self, path):
        spath, qs = urlparse.splitquery(path)
        for cre, klass, args in self.handlers:
            m = cre.match(spath)
            if m is not None:
                return functools.partial(klass, **args)
        return None

    def add_handler(self, pattern, klass, **kw_args):
        cre = re.compile(pattern)
        self.handlers.append((cre, klass, kw_args))


def path(path_pattern, **kw_args):
    def wrapper(cls):
        if not hasattr(cls, '_paths'):
            cls._paths = []
        cre = re.compile(path_pattern)
        cls._paths.insert(0, (cre, kw_args))
        return cls
    return wrapper


def scan_handlers(module_name):
    handlers = []
    mod = importlib.import_module(module_name)
    for name, klass in inspect.getmembers(mod):
        if inspect.isclass(klass) and issubclass(klass, HttpPathHandler) \
                and hasattr(klass, '_paths'):
            for cre, args in klass._paths:
                handlers.append((cre, klass, args))

    return PathMatcher(handlers)
