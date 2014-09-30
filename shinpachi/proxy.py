import itertools
import asyncio
import errno
import socket
import re
import zmq
from .log import logger


# TODO:
#   * Write tests
#   * Move protocol parsing code to another module


def get_peername_bytes(peername):
    if len(peername) == 2:      # IPv4
        peername_bytes = '{}:{}'.format(
            peername[0], peername[1]).encode('utf8')
    else:                       # IPv6
        peername_bytes = '[{}]:{}'.format(
            peername[0], peername[1]).encode('utf8')
    return peername_bytes


class ProtocolError(Exception):
    pass


class ProxyPipe(object):
    def __init__(self, *eps, pub=None):
        for ep in eps:
            if ep.get_pipe() is not None:
                raise RuntimeError('Endpoint already configured')
            ep.set_pipe(self)
        self.endpoints = eps
        self.pub = pub
        self.ep_topics = {}

    def get_ep_topics(self, ep):
        for dst_ep in self.endpoints[:]:
            if dst_ep is ep:
                continue
            yield ep.gen_topic(dst=dst_ep.peername_bytes)

    def publish_from(self, ep, data):
        if self.pub is not None:
            ep_topics = self.get_ep_topics(ep)
            topic_data = b':'.join(itertools.chain(ep_topics, [b'\r\n' + data]))
            try:
                self.pub.send(topic_data, flags=zmq.NOBLOCK)
            except zmq.ZMQError as e:
                if e.errno != errno.EAGAIN:
                    raise e
                else:
                    # TODO: do something?
                    logger.warning('PUB queue overflow')

    def send_from(self, ep, data):
        for dst_ep in self.endpoints:
            if dst_ep is ep:
                continue
            dst_ep.to_me(data)

        self.publish_from(ep, data)

    def close(self):
        for ep in self.endpoints:
            closed = getattr(ep, 'closed', False)
            if not closed:
                ep.closed = True
                ep.close_transport()
                # Send EOF to the console
                self.publish_from(ep, b'')


class ProxyPipeEpMixin(object):
    def set_pipe(self, p_pipe):
        self.pipe = p_pipe

    def get_pipe(self):
        return getattr(self, 'pipe', None)

    def to_me(self, data):
        self.transport.write(data)

    def close_transport(self):
        transport = getattr(self, 'transport', None)
        if transport is None:
            return
        transport.close()


class TopicMixin(object):
    TOPIC_RE = re.compile(
        b'^(([0-9]+(\\.[0-9]+){3})|\\[([:0-9a-fA-F]+)\\]):([0-9]+)-(([0-9]+(\\.[0-9]+){3})|\\[([:0-9a-fA-F]+)\\]):([0-9]+):\r\n')

    def gen_topic(self, src=None, dst=None):
        if src is not None:
            return self._gen_topic('downlink_topic', src, self.peername_bytes)
        elif dst is not None:
            return self._gen_topic('uplink_topic', self.peername_bytes, dst)
        else:
            raise RuntimeError('Both src and dst is None')

    @classmethod
    def decode_topic(cls, msg):
        m = cls.TOPIC_RE.match(msg)
        if m is None:
            return None
        src_ip, _, _, _, src_port, dst_ip, _, _, _, dst_port = m.groups()
        return ((src_ip, src_port), (dst_ip, dst_port))

    def _gen_topic(self, name, src, dst):
        topic = getattr(self, name, None)
        if topic is None:
            topic = b''.join([src, b'-', dst])
            setattr(self, name, topic)
        return topic

    def cleanup_topics(self):
        self.uplink_topic = None
        self.downlink_topic = None

    def add_topic(self, data, src=None, dst=None):
        topic = self.gen_topic(src=src, dst=dst)
        topic_data = b''.join([topic, b':\r\n', data])
        return topic_data


class BaseProtocol(asyncio.Protocol, ProxyPipeEpMixin):
    def connection_made(self, transport):
        self.transport = transport
        self.peername = transport.get_extra_info('peername')
        self.peername_bytes = get_peername_bytes(self.peername)
        logger.debug('New connection %r', self.peername)

    def connection_lost(self, exc):
        logger.debug('Connection %r lost, exc = %r',
                     self.peername, exc)
        p_pipe = self.get_pipe()
        if p_pipe is not None:
            p_pipe.close()
        else:
            self.close_transport()


class ProxyClientProtocol(BaseProtocol, TopicMixin):
    def data_received(self, data):
        # SocksServerProtocol.proxy_connection_done(...) should
        # have been called at this point, so `pipe`
        # must exist. No need to sync with the socks server.
        self.pipe.send_from(self, data)


@asyncio.coroutine
def new_proxy_connection(host, port, proto_factory):
    logger.debug('Proxy client connecting to %s:%d', host, port)
    loop = asyncio.get_event_loop()
    client_transport, client_proto = yield from \
        loop.create_connection(proto_factory,
                               host=host,
                               port=port)
    if client_transport and client_proto:
        logger.debug('Connection made to %s:%d', host, port)
    return client_transport, client_proto


class SocksServerProtocol(BaseProtocol, TopicMixin):
    def __init__(self, pub=None):
        super().__init__()
        self.pub = pub
        self.recv_buf = bytearray()
        self.set_current_handler(self.handle_noop)

    def connection_made(self, transport):
        super().connection_made(transport)
        self.set_current_handler(self.handle_method_request)

    def data_received(self, data):
        self.current_handler(data)

    def connection_lost(self, exc):
        connect_task = getattr(self, 'connect_task', None)
        if connect_task is not None:
            connect_task.cancel()
        super().connection_lost(exc)

    def proxy_connection_done(self, future):
        try:
            client_transport, client_proto = future.result()
            exc = None
        except asyncio.CancelledError:
            client_transport, client_proto = None, None
            exc = None
        except Exception as e:
            exc = e
            client_transport, client_proto = None, None

        if client_transport is not None \
                and client_proto is not None:
            p_pipe = ProxyPipe(client_proto, self, pub=self.pub)
            self.transport.write(b'\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00')
            self.set_current_handler(self.handle_data_stream)
        elif exc is None:
            logger.debug('Task cancelled: %r', future)
        else:
            logger.debug('Failed to connect to remote host: %r', exc)
            self.close_transport()

    def check_protocol_version(self, data):
        return data[0] == 0x05

    def set_current_handler(self, handler):
        self.current_handler = handler
        if len(self.recv_buf) > 0:
            self.current_handler(b'')

    def handle_noop(self, data):
        logger.warning('Connection %r hit `handle_noop`',
                       self.peername)

    def handle_method_request(self, data):
        self.recv_buf.extend(data)
        data = self.recv_buf
        if not self.check_protocol_version(data):
            logger.debug('Version %d mismatch', data[0])
            self.transport.write(b'\x05\xff')
            self.close_transport()
            return

        if len(data) < 2:
            self.recv_buf = data
        elif len(data) < data[1] + 2:
            self.recv_buf = data
        else:
            self.transport.write(b'\x05\x00')      # no authentication
            self.recv_buf = data[(data[1] + 2):]
            self.set_current_handler(self.handle_connect_request)

    def handle_connect_request(self, data):
        self.recv_buf.extend(data)
        data = self.recv_buf
        if not self.check_protocol_version(data):
            raise ProtocolError('Version {} mismatch'.format(data[0]))

        if len(data) < 5:
            self.recv_buf = data
        else:
            command = data[1]
            if command != 0x01:
                # TODO: Should tell the client
                raise ProtocolError('Commands other than CONNECT are not supported')

            address_type = data[3]
            if address_type == 0x01:    # IPv4
                address_len = 4
            elif address_type == 0x03:  # domain name
                address_len = data[4]
                address_len += 1
            else:
                # TODO: tell the client
                raise ProtocolError('Address type {} not supported'.format(address_type))

            if len(data) < address_len + 6:
                self.recv_buf = data
            else:
                if address_type == 0x01:        # IPv4
                    address = '{}.{}.{}.{}'.format(
                        data[4], data[5], data[6], data[7])
                else:       # domain name
                    address = data[5:5+address_len-1].decode('utf8')

                dst_port = data[4+address_len:]
                dst_port = (dst_port[0] << 8) + dst_port[1]

                self.recv_buf = data[(address_len + 6):]

                self.connect_task = asyncio.Task(
                    new_proxy_connection(address, dst_port, ProxyClientProtocol))
                self.connect_task.add_done_callback(self.proxy_connection_done)

    def handle_data_stream(self, data):
        self.pipe.send_from(self, data)


