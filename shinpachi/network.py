import socket
import asyncio
try:
    import ssl
except ImportError:
    pass
from .config import get_abs_path
from .log import logger


def getaddrinfo(host, port, flags=0):
    if host == '*':
        host = None

    addr_infos = socket.getaddrinfo(host=host, port=port,
                                    family=socket.AF_UNSPEC,
                                    type=socket.SOCK_STREAM,
                                    proto=socket.IPPROTO_TCP,
                                    flags=flags)
    return addr_infos


@asyncio.coroutine
def getaddrinfo_async(loop, host, port, flags=0):
    if host == '*':
        host = None

    addr_infos = yield from \
        loop.getaddrinfo(host=host, port=port,
                         family=socket.AF_UNSPEC,
                         type=socket.SOCK_STREAM,
                         proto=socket.IPPROTO_TCP,
                         flags=flags)
    return addr_infos


def create_listen_sockets(host, port, backlog):
    # Most of these code ripped from
    # asyncio.base_events.BaseEventLoop.create_server

    addr_infos = getaddrinfo(host, port, socket.AI_PASSIVE)
    if not addr_infos:
        raise OSError('getaddrinfo(...) returned empty list')

    listen_socks = []
    for info in addr_infos:
        af, socktype, proto, canonname, sockaddr = info
        try:
            listen_sock = socket.socket(family=af, type=socktype, proto=proto)
        except socket.error:
            logger.debug(
                'Failed to create socket with af=%r, socktype=%r, proto=%r',
                af, socktype, proto)
            continue
        listen_socks.append(listen_sock)

        listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
        if af == socket.AF_INET6 and hasattr(socket, 'IPPROTO_IPV6'):
            listen_sock.setsockopt(
                socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, True)

        listen_sock.bind(sockaddr)
        listen_sock.listen(backlog)

    return listen_socks


def create_ssl_context(config):
    # Default is False, so config_file cannot be None
    if config['http'].getboolean('ssl'):
        certfile = get_abs_path(config, config['http']['ssl_cert'])
        keyfile = get_abs_path(config, config['http']['ssl_key'])
        logger.debug('Using certfile = %r, keyfile = %r',
                     certfile, keyfile)
        sslcontext = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        sslcontext.load_cert_chain(certfile, keyfile)
    else:
        sslcontext = None

    return sslcontext
