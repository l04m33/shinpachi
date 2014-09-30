import aiohttp
import aiohttp.server
import aiohttp.websocket
import asyncio
import zmq
import socket
import collections
import re
from urllib import parse as urlparse
from .http_base import (HttpPathHandler, path)
from .user import (get_user, oauth_login, oauth2_code_cb)
from .user.errors import  (OAuth2StepError, OAuth2BadData)
from .network import getaddrinfo_async
from .io import aiohttp_read_all_into_bytearray
from .proxy import TopicMixin
from .log import logger
from .version import (__version__, SERVER_SOFTWARE)


class HttpResponse(aiohttp.Response):
    SERVER_SOFTWARE = SERVER_SOFTWARE


class ShinpachiAuthPathHandler(HttpPathHandler):
    @asyncio.coroutine
    def authenticated(self, cookie):
        if not self.kw['config']['http'].getboolean('need_auth'):
            return (True, None)

        if 'shinpachi_user_key' in cookie:
            try:
                user = yield from get_user(
                    cookie['shinpachi_user_key'].value, self.kw['config'])
                if user is None:
                    return (False, None)
                else:
                    return (True, user)
            except Exception as e:
                logger.error('Failed to get_user(...), e = %r', e)
                return (False, None)
        else:
            return (False, None)


@path('^/$')
class ConsoleHandler(ShinpachiAuthPathHandler):
    @asyncio.coroutine
    def do_handle(self, message, payload, user):
        response = self.start_response(200, message.version)
        response.add_header('Content-Type', 'text/html')
        response.send_headers()

        template = self.kw['tmpl_env'].get_template('console.jinja2')
        response.write(template.render(version=__version__,
                                       user=user).encode('utf8'))
        return response

    @asyncio.coroutine
    def handle(self, message, payload):
        try:
            response = yield from super().handle(message, payload)
            return response
        except aiohttp.HttpErrorException as exc:
            if exc.code == 403:
                return self.redirect_to('/intro?need_auth=✓', message)
            else:
                raise


@path('^/intro$')
class IntroHandler(ShinpachiAuthPathHandler):
    @asyncio.coroutine
    def authenticated(self, cookie):
        auth_result, user = yield from super().authenticated(cookie)
        return (True, user)

    @asyncio.coroutine
    def do_handle(self, message, payload, user):
        need_auth = False
        spath, qs = urlparse.splitquery(message.path)
        if qs is not None:
            qs = urlparse.parse_qs(qs, keep_blank_values=True)
            if 'need_auth' in qs:
                need_auth = True

        response = self.start_response(200, message.version)
        response.add_header('Content-Type', 'text/html')
        response.send_headers()

        template = self.kw['tmpl_env'].get_template('intro.jinja2')
        response.write(template.render(version=__version__,
                                       user=user,
                                       need_auth=need_auth).encode('utf8'))
        return response


@path('^/oauth$')
class OAuthHandler(HttpPathHandler):
    @asyncio.coroutine
    def do_handle(self, message, payload, user):
        data = yield from aiohttp_read_all_into_bytearray(payload)
        form_data = urlparse.parse_qs(data, keep_blank_values=True)
        logger.debug('form_data = %r', form_data)
        try:
            redirect_url = yield from oauth_login(
                form_data, self.kw['config'], self.kw['redis'])
            exc = None
        except Exception as e:
            redirect_url = None
            exc = e
        logger.debug('redirect_url = %r', redirect_url)

        if redirect_url is None:
            logger.debug(
                'redirect_url not found for form_data = %r, exc = %r',
                form_data, exc)
            response = self.start_response(500, message.version)
            response.send_headers()
            return response

        return self.redirect_to(redirect_url, message)


@path('^/oauth_logout$')
class OAuthLogoutHandler(HttpPathHandler):
    @asyncio.coroutine
    def do_handle(self, message, payload, user):
        return self.redirect_to('/intro', message,
                                clear_cookies=['shinpachi_user_key'])


@path('^/oauth2/code_cb/')
class OAuth2CodeCBHandler(HttpPathHandler):
    @asyncio.coroutine
    def do_handle(self, message, payload, user):
        if '?' in message.path:
            path, qs = urlparse.splitquery(message.path)
        else:
            path = message.path
            qs = yield from aiohttp_read_all_into_bytearray(payload)

        platform = path[len('/oauth2/code_cb/'):]

        code_data = urlparse.parse_qs(qs, keep_blank_values=True)

        logger.debug('code_data = %r', code_data)

        try:
            user = yield from oauth2_code_cb(
                platform, code_data, self.kw['config'], self.kw['redis'])
            exc = None
        except OAuth2StepError:
            return self.redirect_to('/', message)
        except OAuth2BadData:
            return self.redirect_to('/', message)
        except Exception as e:
            user = None
            exc = e

        logger.debug('user = %r', user)

        if user is None:
            logger.debug(
                'Cannot retrieve user info ' +
                'for platform = %r, code_data = %r, exc = %r',
                platform, code_data, exc)
            response = self.start_response(500, message.version)
            response.send_headers()
            return response

        cookie_content = [
            ('shinpachi_user_key', '{}:{}'.format(user.platform, user.key))
        ]
        return self.redirect_to('/', message, set_cookies=cookie_content)


@path('^/ws$')
class WebsocketHandler(ShinpachiAuthPathHandler):
    TOPIC_EP_RE = re.compile(b'^(([0-9]+(\\.[0-9]+){3})|\\[([:0-9a-fA-F]+)\\])(:([0-9]+))?$')

    @asyncio.coroutine
    def do_handle(self, message, payload, user):
        if ('UPGRADE' not in message.headers) or \
                ('websocket' not in message.headers['UPGRADE']):
            logger.debug('Invalid websocket request')
            raise aiohttp.HttpErrorException(400)

        evloop = asyncio.get_event_loop()

        zmq_ctx = zmq.Context.instance()
        zmq_sock = zmq_ctx.socket(zmq.SUB)
        xpub_addr = self.kw['config']['bridge']['xpub_address']
        yield from evloop.run_in_executor(None, zmq_sock.connect, xpub_addr)

        self.zmq_sock = zmq_sock
        self.sub_topics = set()
        self.sub_triggers = set()
        self.triggered_sub_topics = collections.defaultdict(list)

        status, headers, parser, writer = \
            aiohttp.websocket.do_handshake(
                message.method, message.headers,
                self.protocol.transport)
        response = self.start_response(status, message.version)
        response.add_headers(*headers)
        response.send_headers()

        dataqueue = self.protocol.reader.set_parser(parser)

        def zmq_read_ready():
            try:
                from_zmq = zmq_sock.recv(flags=zmq.NOBLOCK)
            except zmq.ZMQError as e:
                if e.errno == errno.EAGAIN:
                    from_zmq = None
                else:
                    raise e
            if from_zmq is not None:
                if len(self.sub_triggers) > 0:
                    decoded_topic = TopicMixin.decode_topic(from_zmq)
                    if decoded_topic is not None:
                        (src_ip, src_port), (dst_ip, dst_port) = decoded_topic
                        src_full = src_ip + b':' + src_port
                        dst_full = dst_ip + b':' + dst_port

                        do_trigger = None
                        if src_ip in self.sub_triggers:
                            do_trigger = src_ip
                        elif src_full in self.sub_triggers:
                            do_trigger = src_full

                        if do_trigger is not None \
                                and dst_full not in self.sub_topics:
                            self.add_triggered_subscription(dst_full, do_trigger)

                        do_trigger = None
                        if dst_ip in self.sub_triggers:
                            do_trigger = dst_ip
                        elif dst_full in self.sub_triggers:
                            do_trigger = dst_full

                        if do_trigger is not None \
                                and src_full not in self.sub_topics:
                            self.add_triggered_subscription(src_full, do_trigger)

                writer.send(from_zmq, binary=True)

        evloop.add_reader(zmq_sock, zmq_read_ready)

        while True:
            try:
                msg = yield from dataqueue.read()
            except aiohttp.EofStream:
                break

            if msg.tp == aiohttp.websocket.MSG_PING:
                writer.pong()
            elif msg.tp == aiohttp.websocket.MSG_CLOSE:
                logger.debug('MSG_CLOSE from client')
                break
            elif msg.tp == aiohttp.websocket.MSG_TEXT:
                # Command from the client
                self.handle_ws_cmd(msg.data)

    def close(self):
        zmq_sock = getattr(self, 'zmq_sock', None)
        if zmq_sock:
            logger.debug('Cleaning up zmq_sock')
            loop = asyncio.get_event_loop()
            loop.remove_reader(zmq_sock)
            zmq_sock.close()

        if hasattr(self, 'sub_topics') \
                and self.kw['config']['http_proxy'].getboolean('auth_ip') \
                and self.kw['redis'] is not None:
            for t in self.sub_topics:
                self.clear_ip_auth(self.get_ip_from_topic(t))

    def add_subscription(self, topic):
        logger.debug('Adding new topic: %r', topic)
        if topic not in self.sub_topics:
            ep_ip = self.get_ip_from_topic(topic)
            if ep_ip is None:
                logger.debug('Bad topic: %r', topic)
                return
            self.sub_topics.add(topic)
            self.zmq_sock.setsockopt(zmq.SUBSCRIBE, topic)
            self.set_ip_auth(ep_ip)

    def add_triggered_subscription(self, topic, trigger):
        logger.debug('Adding triggered new topic from %r: %r', trigger, topic)
        if topic not in self.sub_topics:
            self.triggered_sub_topics[trigger].append(topic)
            self.add_subscription(topic)

    def add_trigger(self, trigger):
        if trigger not in self.sub_triggers:
            logger.debug('Adding new trigger: %r', trigger)
            self.sub_triggers.add(trigger)
            self.add_subscription(trigger)

    def get_ip_from_topic(self, topic):
        ep_match = self.TOPIC_EP_RE.match(topic)
        if ep_match is None:
            return None
        match_groups = ep_match.groups()
        return match_groups[1] if match_groups[1] is not None \
                else match_groups[3]

    def set_ip_auth(self, ep_ip):
        if self.kw['config']['http_proxy'].getboolean('auth_ip') \
                and self.kw['redis'] is not None:
            asyncio.async(self.kw['redis'].incr(ep_ip.decode('utf8')))

    def clear_ip_auth(self, ep_ip):
        if self.kw['config']['http_proxy'].getboolean('auth_ip') \
                and self.kw['redis'] is not None:
            asyncio.async(self.kw['redis'].decr(ep_ip.decode('utf8')))

    def handle_ws_cmd(self, cmd_line):
        split_line = cmd_line.split(' ')
        cmd = split_line[0]
        args = map(lambda a: a.encode('utf8'), split_line[1:])

        if cmd == 'subscribe':
            for t in args:
                self.add_subscription(t)
        elif cmd == 'trigger':
            for t in args:
                self.add_trigger(t)
        elif cmd == 'unsubscribe':
            for t in args:
                self.unsubscribe(t)

    def unsubscribe(self, topic):
        logger.debug('Unsubscribe: %r', topic)
        if topic in self.sub_topics:
            self.zmq_sock.setsockopt(zmq.UNSUBSCRIBE, topic)
            self.sub_topics.remove(topic)
            self.clear_ip_auth(self.get_ip_from_topic(topic))
        if topic in self.sub_triggers:
            triggered = self.triggered_sub_topics[topic]
            logger.debug('Unsubscribe to triggered topics: %r', triggered)
            for tt in triggered:
                self.zmq_sock.setsockopt(zmq.UNSUBSCRIBE, tt)
                try:
                    self.sub_topics.remove(tt)
                    self.clear_ip_auth(self.get_ip_from_topic(tt))
                except KeyError:
                    pass
            self.triggered_sub_topics.pop(topic)
            self.sub_triggers.remove(topic)


@path('^/proxy.json$',
      template_name='pac_json.jinja2',
      content_type='application/json')
@path('^/proxy.pac$',
      template_name='pac.jinja2',
      content_type='application/x-javascript-config')
class PACHandler(HttpPathHandler):
    @asyncio.coroutine
    def do_handle(self, message, payload, user):
        response = self.start_response(200, message.version)
        response.add_header('Content-Type', self.kw['content_type'])
        response.send_headers()

        host = message.headers.get('HOST', None)
        if host is not None:
            host = host.split(':')[0]
            http_addr_infos = [(host, self.kw['config']['http_proxy'].getint('port'))]
        else:
            http_addr_infos = yield from getaddrinfo_async(
                asyncio.get_event_loop(),
                self.kw['config']['http_proxy']['host'],
                self.kw['config']['http_proxy'].getint('port'))
            http_addr_infos = map(lambda info: info[4],
                                  filter(lambda info: info[0] == socket.AF_INET, http_addr_infos))

        template = self.kw['tmpl_env'].get_template(self.kw['template_name'])

        # TODO: cache the result
        res = template.render(http_addr_infos=http_addr_infos).encode('utf8')
        response.write(res)
        return response


class HttpProtocol(aiohttp.server.ServerHttpProtocol):
    def __init__(self, matcher, tmpl_env, res_mgr, res_provider, redis, config):
        if config['log']['level'].strip().upper() == 'DEBUG':
            debug = True
        else:
            debug = False
        super().__init__(debug=debug, keep_alive=75)
        self.matcher = matcher
        self.tmpl_env = tmpl_env
        self.config = config
        self.redis = redis
        self.resource_mgr = res_mgr
        self.resource_provider = res_provider
        self.need_auth = config['http'].getboolean('need_auth')

    @asyncio.coroutine
    def handle_request(self, message, payload):
        path_handler = self.matcher.match(message.path)

        if path_handler is None:
            raise aiohttp.HttpErrorException(404)

        path_handler = path_handler(self,
                                    response_cls=HttpResponse,
                                    config=self.config,
                                    redis=self.redis,
                                    tmpl_env=self.tmpl_env)

        logger.debug('message = %r, payload = %r', message, payload)

        self.path_handler = path_handler
        response = yield from path_handler.handle(message, payload)
        self.path_handler.close()
        del self.path_handler

        if asyncio.iscoroutine(response):
            response = yield from response
        if response is not None:
            yield from response.write_eof()
            if response.keep_alive():
                self.keep_alive(True)

    def connection_lost(self, exc):
        logger.debug('HTTP connection lost, exc = %r', exc)
        super().connection_lost(exc)
        if hasattr(self, 'path_handler'):
            self.path_handler.close()
