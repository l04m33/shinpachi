import multiprocessing
import asyncio
import pkg_resources
import zmq
import time
import jinja2
from .proxy import SocksServerProtocol
from .http_proxy import HttpProxyProtocol
from .http_base import (scan_handlers, StaticPathHandler)
from .http import HttpProtocol
from .io import (install_zmq_event_loop, get_redis_async_connection)
from .network import create_ssl_context
from .log import logger


def init_redis_connection(config):
    redis_host = config['redis']['host']
    redis_port = config['redis'].getint('port')
    redis_pool_size = config['redis'].getint('pool_size')
    return get_redis_async_connection(redis_host, redis_port, redis_pool_size)


def proxy_worker(listen_socks, config):
    me = multiprocessing.process.current_process()
    logger.info('Proxy worker %d started on sockets %r',
                me.pid, listen_socks)

    ctx = zmq.Context.instance()
    pub = ctx.socket(zmq.PUB)
    pub.connect(config['bridge']['xsub_address'])

    loop = asyncio.get_event_loop()

    def proto_factory():
        return SocksServerProtocol(pub=pub)

    for sock in listen_socks:
        server = loop.create_server(proto_factory, sock=sock)
        asyncio.Task(server)

    loop.run_forever()


def http_proxy_worker(listen_socks, config):
    me = multiprocessing.process.current_process()
    logger.info('HTTP proxy worker %d started on sockets %r',
                me.pid, listen_socks)

    loop = asyncio.get_event_loop()

    # ZeroMQ stuff
    ctx = zmq.Context.instance()
    pub = ctx.socket(zmq.PUB)
    pub.connect(config['bridge']['xsub_address'])

    # Redis stuff
    redis = init_redis_connection(config)

    def proto_factory():
        return HttpProxyProtocol(config, redis, pub)

    for sock in listen_socks:
        server = loop.create_server(proto_factory, sock=sock)
        asyncio.Task(server)

    loop.run_forever()


def http_worker(listen_socks, config):
    me = multiprocessing.process.current_process()
    logger.info('HTTP worker %d started on sockets %r',
                me.pid, listen_socks)

    sslcontext = create_ssl_context(config)

    install_zmq_event_loop()
    loop = asyncio.get_event_loop()

    # Jinja2 stuff
    tmpl_env = jinja2.Environment(
        loader=jinja2.PackageLoader('shinpachi', 'templates'))
    res_mgr = pkg_resources.ResourceManager()
    res_provider = pkg_resources.get_provider(__package__)

    # Handlers
    matcher = scan_handlers('shinpachi.http')
    matcher.add_handler('^/static/', StaticPathHandler,
                        url_path_prefix='/static/',
                        root_path='static/',
                        resource_provider=res_provider,
                        resource_mgr=res_mgr)

    # Redis stuff
    redis = init_redis_connection(config)

    def proto_factory():
        return HttpProtocol(
            matcher, tmpl_env, res_mgr, res_provider, redis, config)

    for sock in listen_socks:
        server = loop.create_server(proto_factory, sock=sock, ssl=sslcontext)
        asyncio.Task(server)

    loop.run_forever()


def bridge_worker(config):
    ctx = zmq.Context.instance()

    xsub_address = config['bridge']['xsub_address']
    xsub_sock = ctx.socket(zmq.XSUB)
    xsub_sock.bind(xsub_address)

    xpub_address = config['bridge']['xpub_address']
    xpub_sock = ctx.socket(zmq.XPUB)
    xpub_sock.bind(xpub_address)

    pub_address = config['bridge']['pub_address']
    pub_sock = ctx.socket(zmq.PUB)
    pub_sock.bind(pub_address)

    logger.debug('xsub_address = %r', xsub_address)
    logger.debug('xpub_address = %r', xpub_address)
    logger.debug('pub_address = %r', pub_address)

    zmq.proxy(xpub_sock, xsub_sock, pub_sock)


def spawn_workers(target, args, nr):
    workers = []
    for i in range(nr):
        p = multiprocessing.Process(target=target, args=args)
        workers.append(p)
        p.start()
    return workers


def monitor_workers(workers):
    def cleanup(w):
        try:
            w.join()
        except:
            pass

    while workers:
        time.sleep(1)

        for w in workers[:]:
            if not w.is_alive() and (w.exitcode is None or w.exitcode != 0):
                logger.warning('Worker %r exited with code %r, restarting',
                               w.pid, w.exitcode)

                workers.remove(w)
                cleanup(w)

                new_w = multiprocessing.Process(target=w._target, args=w._args)
                workers.append(new_w)
                new_w.start()
            elif not w.is_alive():
                workers.remove(w)
                cleanup(w)


PROCESS_WORKERS = {
    'proxy': proxy_worker,
    'http_proxy': http_proxy_worker,
    'http': http_worker,
    'bridge': bridge_worker,
}
