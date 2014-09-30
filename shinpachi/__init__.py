import logging
import sys
from .processes import PROCESS_WORKERS
from .processes import bridge_worker
from .processes import spawn_workers
from .processes import monitor_workers
from .config import init_config
from .network import create_listen_sockets
from .log import logger
from . import version


__all__ = ['main']
__version__ = version.__version__


def create_workers(name, worker_funs, config):
    enabled = config[name].getboolean('enabled')
    if not enabled:
        return []

    host = config[name]['host']
    port = config[name].getint('port')
    backlog = config[name].getint('backlog')

    logger.info('%s server serving at %s:%d', name, host, port)

    listen_socks = create_listen_sockets(host, port, backlog)

    process_nr = config['proxy'].getint('processes')
    workers = spawn_workers(worker_funs[name],
                            (listen_socks, config),
                            process_nr)
    return workers


def main():
    if len(sys.argv) < 2:
        config_file = None
    else:
        config_file = sys.argv[1]
    config = init_config(config_file)

    logging.basicConfig(level=config['log']['level'])

    if config_file is None:
        logger.warning('No config file specified, using defaults')
    logger.info('log level = %s', config['log']['level'])

    proxy_workers = create_workers('proxy', PROCESS_WORKERS, config)
    http_proxy_workers = create_workers('http_proxy', PROCESS_WORKERS, config)
    http_workers = create_workers('http', PROCESS_WORKERS, config)
    bridge_workers = spawn_workers(bridge_worker, (config,), 1)

    # --------- all done ---------

    workers = proxy_workers + http_proxy_workers \
        + http_workers + bridge_workers
    monitor_workers(workers)
