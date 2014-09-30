import asyncio
import aiohttp
import aiohttp.server
import aiohttp.client
import re
import urllib.parse
from .proxy import (ProxyClientProtocol, ProxyPipe,
                    ProxyPipeEpMixin, TopicMixin)
from .proxy import (new_proxy_connection, get_peername_bytes)
from .http import HttpResponse
from .io import (aiohttp_read_all, aiohttp_read_all_into_bytearray)
from .network import getaddrinfo_async
from .log import logger


def cleanup_headers(headers):
    hd_to_remove = {
        'CONNECTION',
        'KEEP-ALIVE',
        'PROXY-AUTHENTICATE',
        'PROXY-AUTHORIZATION',
        'PROXY-CONNECTION',
        'TE',
        'TRAILERS',
        'TRANSFER-ENCODING',
        'UPGRADE',
        'CONTENT-ENCODING',
        'CONTENT-LENGTH',
        'ACCEPT-ENCODING',
    }

    for hname, hval in headers:
        hval = hval.encode('ascii', 'surrogateescape').decode('utf8')
        logger.debug('header - %r: %r', hname, hval)
        if hname in hd_to_remove:
            if hname == 'CONNECTION' or hname == 'PROXY-CONNECTION':
                rhd = hval.split(',')
                for hd in rhd:
                    hd_to_remove.add(hd.strip().upper())
            continue
        yield (hname, hval)


def restore_headers(message, head_line, buf=None):
    if buf is None:
        buf = bytearray()

    buf.extend(head_line)

    # headers
    headers = list(cleanup_headers(message.headers.items(getall=True)))
    for hname, hval in headers:
        buf.extend('{}: {}\r\n'.format(hname, hval).encode('utf8'))

    if 'CONTENT-ENCODING' not in message.headers \
            or 'identity' in message.headers['CONTENT-ENCODING'].lower():
        if 'CONTENT-LENGTH' in message.headers:
            cl = message.headers['CONTENT-LENGTH']
            headers.append(('CONTENT-LENGTH', cl))
            buf.extend('{}: {}\r\n'.format('CONTENT-LENGTH', cl).encode('utf8'))

    buf.extend(b'\r\n')

    return (buf, headers)


class ProxyRequest(aiohttp.client.ClientRequest):
    def update_path(self, params, data):
        _scheme, _netloc, path, query, fragment = \
            urllib.parse.urlsplit(self.url)
        if not path:
            path = '/'
        self.path = urllib.parse.urlunsplit(('', '', path, query, fragment))


class HttpProxyProtocol(aiohttp.server.ServerHttpProtocol,
                        ProxyPipeEpMixin, TopicMixin):
    DEFAULT_HTTP_VERSION = (1, 1)
    SCHEME_RE = re.compile('^[a-zA-Z]+[a-zA-Z0-9]*:(//){0,1}')
    CONNECT_DST_RE = re.compile('([\-a-zA-Z0-9.]+):([0-9]+)')

    def __init__(self, config, redis=None, pub=None):
        if config['log']['level'].strip().upper() == 'DEBUG':
            debug = True
        else:
            debug = False
        super().__init__(debug=debug, keep_alive=75)
        self.pub = pub
        self.redis = redis
        self.config = config
        self.streaming = False

    @asyncio.coroutine
    def handle_request(self, message, payload):
        if self.config['http_proxy'].getboolean('auth_ip') \
                and self.redis is not None:
            ip_to_auth = self.peername[0]
            auth_result = yield from self.redis.get(ip_to_auth)
        else:
            auth_result = '1'

        if auth_result is None or int(auth_result) <= 0:
            yield from self.handle_ip_auth_failure(message, payload)
            return

        if message.method == 'CONNECT':
            yield from self.handle_method_connect(message, payload)
        else:
            yield from self.handle_method_all(message, payload)

    @asyncio.coroutine
    def handle_method_connect(self, message, payload):
        match = self.CONNECT_DST_RE.match(message.path)
        if not match:
            raise aiohttp.HttpErrorException(400)
        host = match.group(1)
        port = int(match.group(2))

        is_loop = yield from self.check_proxy_ip_loop(host, port)
        if is_loop:
            yield from self.handle_loop_detected(message, payload)
            return

        self.cleanup_parser(payload)

        try:
            client_transport, client_proto = \
                yield from new_proxy_connection(host, port, ProxyClientProtocol)
            exc = None
        except Exception as e:
            exc = e
            client_transport, client_proto = None, None

        if client_transport is not None \
                and client_proto is not None:
            response = self.start_response(200, message)
            response.send_headers()
            p_pipe = ProxyPipe(client_proto, self, pub=self.pub)
            self.streaming = True
            if self._request_handler is not None:
                self._request_handler.cancel()
                self._request_handler = None
        else:
            logger.debug('new_proxy_connection failed, exc = %r', exc)
            response = self.start_response(500, message)
            response.send_headers()
            yield from response.write_eof()
            #if response.keep_alive():
            #    self.keep_alive(True)
            self.keep_alive(False)

        logger.debug('Done handling CONNECT')

    @asyncio.coroutine
    def handle_method_all(self, message, payload):
        url = self.build_url(message.headers, message.path)
        logger.debug('url = %r', url)

        data = yield from aiohttp_read_all_into_bytearray(payload)

        pub_buf, req_headers = \
            restore_headers(message,
                            '{} {} HTTP/{}.{}\r\n'.format(
                                message.method, message.path,
                                message.version[0],
                                message.version[1]).encode('utf8'))
        pub_buf.extend(data)

        logger.debug('Sending http request to %r', url)
        client_res = yield from aiohttp.request(message.method, url,
                                                headers=req_headers,
                                                data=data,
                                                version=self.DEFAULT_HTTP_VERSION,
                                                allow_redirects=False,
                                                request_class=ProxyRequest)
        logger.debug('Sent http request to %r', url)

        res_peername = client_res.connection._transport.get_extra_info('peername')
        res_peername_bytes = get_peername_bytes(res_peername)

        topic_data = self.add_topic(pub_buf, dst=res_peername_bytes)
        self.pub.send(topic_data)
        pub_eof = self.add_topic(b'', dst=res_peername_bytes)
        self.pub.send(pub_eof)

        response = self.start_response(client_res.status, message)

        pub_buf, res_headers = \
            restore_headers(client_res.message,
                            response.status_line.encode('utf8'))

        response.add_headers(*res_headers)
        response.send_headers()

        topic_data = self.add_topic(pub_buf, src=res_peername_bytes)
        self.pub.send(topic_data)

        orig_stream = client_res.content

        def cb(c):
            yield from response.write(c)
            topic_data = self.add_topic(c, src=res_peername_bytes)
            self.pub.send(topic_data)
        yield from aiohttp_read_all(orig_stream, cb)

        client_res.close()
        pub_eof = self.add_topic(b'', src=res_peername_bytes)
        self.pub.send(pub_eof)

        yield from response.write_eof()
        #if response.keep_alive():
        #    self.keep_alive(True)
        #    self.cleanup_topics()
        self.keep_alive(False)

    @asyncio.coroutine
    def handle_ip_auth_failure(self, message, payload):
        raise aiohttp.HttpErrorException(403)

    @asyncio.coroutine
    def handle_loop_detected(self, message, payload):
        raise aiohttp.HttpErrorException(502)

    def connection_made(self, transport):
        self.peername = transport.get_extra_info('peername')
        self.peername_bytes = get_peername_bytes(self.peername)
        logger.debug('New connection %r', self.peername)
        super().connection_made(transport)

    def connection_lost(self, exc):
        super().connection_lost(exc)
        p_pipe = self.get_pipe()
        if p_pipe is not None:
            p_pipe.close()
        else:
            self.close_transport()

    def data_received(self, data):
        if self.streaming:
            self.pipe.send_from(self, data)
        else:
            super().data_received(data)

    def close_transport(self):
        super().close_transport()
        if self._request_handler is not None:
            self._request_handler.cancel()
            self._request_handler = None

    def start_response(self, status_code, message):
        response = HttpResponse(
            self.writer, status_code,
            http_version=message.version)
        return response

    def cleanup_parser(self, payload):
        self.reader.unset_parser()
        extra_content = yield from aiohttp_read_all_into_bytearray(payload)
        if extra_content:
            logger.warning('extra_content = %r', extra_content)
        return extra_content

    def build_url(self, headers, orig_path):
        if self.SCHEME_RE.match(orig_path):
            return orig_path
        else:
            host = headers.get('HOST', None)
            host = host.lower() if host else host
            if not host:
                raise aiohttp.HttpErrorException(400)
            if not orig_path.startswith('/'):
                path = '/' + orig_path
            else:
                path = orig_path
            return 'http://{}{}'.format(host, path)

    @asyncio.coroutine
    def check_proxy_ip_loop(self, host, port):
        host = host.strip().lower()
        if host.startswith('127.') \
                or host == self.config['http_proxy']['host'].lower():
            return True

        addrinfo_list = yield from getaddrinfo_async(
            asyncio.get_event_loop(), host, port)
        local_ips = self.config['http_proxy']['loop_detection_ip'].split(' ')
        for ai in addrinfo_list:
            _af, _socktype, _proto, _canonname, sockaddr = ai
            for lip in local_ips:
                if sockaddr[0].lower() == lip.strip().lower():
                    return True
        return False
