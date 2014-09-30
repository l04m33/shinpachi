import asyncio
import aiohttp
import asyncio_redis
import selectors
import zmq
import errno
import math
import fcntl
import os
import ctypes
import errno


__all__ = ['ZmqSelector', 'install_zmq_event_loop',
           'AsyncFileWrapper']


class ZmqSelector(selectors._BaseSelectorImpl):
    def __init__(self, poller=None):
        super().__init__()
        if poller is not None:
            if not isinstance(poller, zmq.Poller):
                raise TypeError('Only zmq.Poller can be used')
            self._zmq_poller = poller
        else:
            self._zmq_poller = zmq.Poller()

    def _fileobj_lookup(self, fileobj):
        if isinstance(fileobj, zmq.Socket):
            return fileobj
        else:
            return super()._fileobj_lookup(fileobj)

    def register(self, fileobj, events, data=None):
        key = super().register(fileobj, events, data)
        flags = 0
        if events & selectors.EVENT_READ:
            flags |= zmq.POLLIN
        if events & selectors.EVENT_WRITE:
            flags |= zmq.POLLOUT
        self._zmq_poller.register(fileobj, flags)
        return key

    def unregister(self, fileobj):
        key = super().unregister(fileobj)
        self._zmq_poller.unregister(fileobj)
        return key

    def select(self, timeout=None):
        if timeout is not None:
            poll_timeout = max(0, math.ceil(timeout * 1e3))
        else:
            poll_timeout = None

        select_ready = []
        try:
            zmq_events = self._zmq_poller.poll(poll_timeout)
        except zmq.ZMQError as e:
            if e.errno == errno.EINTR:
                return select_ready
            else:
                raise e

        for sock, ev in zmq_events:
            key = self._key_from_fd(sock)
            if key is not None:
                events = 0
                if ev & zmq.POLLIN:
                    events |= selectors.EVENT_READ
                if ev & zmq.POLLOUT:
                    events |= selectors.EVENT_WRITE
                if ev & zmq.POLLERR:
                    events = selectors.EVENT_READ | selectors.EVENT_WRITE
                select_ready.append((key, events & key.events))

        return select_ready


def install_zmq_event_loop():
    event_loop = asyncio.SelectorEventLoop(ZmqSelector())
    asyncio.set_event_loop(event_loop)


def get_redis_async_connection(host, port, pool_size):
    redis_connector = asyncio_redis.Pool.create(
        host=host, port=port, poolsize=pool_size)
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(redis_connector)


class AsyncFileWrapper(object):
    DEFAULT_BLOCK_SIZE = 8192

    def __init__(self, loop=None, filename=None,
                 fileobj=None, mode='rb'):
        if (filename is None and fileobj is None) or \
                (filename is not None and fileobj is not None):
            raise RuntimeError('Confilicting arguments')

        if filename is not None:
            if 'b' not in mode:
                raise RuntimeError('Only binary mode is supported')
            fileobj = open(filename, mode=mode)
        elif 'b' not in fileobj.mode:
            raise RuntimeError('Only binary mode is supported')

        fl = fcntl.fcntl(fileobj, fcntl.F_GETFL)
        if fcntl.fcntl(fileobj, fcntl.F_SETFL, fl | os.O_NONBLOCK) != 0:
            if filename is not None:
                fileobj.close()
            errcode = ctypes.get_errno()
            raise OSError((errcode, errno.errorcode[errcode]))

        self.fileobj = fileobj

        if loop is None:
            loop = asyncio.get_event_loop()
        self.loop = loop
        self.rbuffer = bytearray()

    def seek(self, offset, whence=None):
        if whence is None:
            return self.fileobj.seek(offset)
        else:
            return self.fileobj.seek(offset, whence)

    def read_ready(self, future, n, total):
        try:
            res = self.fileobj.read(n)
        except Exception as exc:
            future.set_exception(exc)
            return

        if res is None: # Blocked
            self.read_handle = self.loop.call_soon(self.read_ready, future, n, total)
            return

        if not res:     # EOF
            future.set_result(bytes(self.rbuffer))
            return

        self.rbuffer.extend(res)

        if total > 0:
            more_to_go = total - len(self.rbuffer)
            if more_to_go <= 0: # enough
                res, self.rbuffer = self.rbuffer[:n], self.rbuffer[n:]
                future.set_result(bytes(res))
            else:
                more_to_go = min(self.DEFAULT_BLOCK_SIZE, more_to_go)
                self.read_handle = self.loop.call_soon(self.read_ready, future, more_to_go, total)
        else:   # total < 0
            self.read_handle = self.loop.call_soon(self.read_ready, future, self.DEFAULT_BLOCK_SIZE, total)

    @asyncio.coroutine
    def read(self, n=-1):
        future = asyncio.Future(loop=self.loop)

        if n == 0:
            future.set_result(b'')
            return future
        elif n < 0:
            self.rbuffer.clear()
            self.read_handle = self.loop.call_soon(self.read_ready, future, self.DEFAULT_BLOCK_SIZE, n)
        else:
            self.rbuffer.clear()
            read_block_size = min(self.DEFAULT_BLOCK_SIZE, n)
            self.read_handle = self.loop.call_soon(self.read_ready, future, read_block_size, n)

        return future

    def write_ready(self, future, data, written):
        try:
            res = self.fileobj.write(data)
        except BlockingIOError:
            self.write_handle = self.loop.call_soon(self.write_ready, future, data, written)
            return
        except Exception as exc:
            future.set_exception(exc)
            return

        if res < len(data):
            data = data[res:]
            self.write_handle = self.loop.call_soon(self.write_ready, future, data, written + res)
        else:
            future.set_result(written + res)

    @asyncio.coroutine
    def write(self, data):
        future = asyncio.Future(loop=self.loop)

        if len(data) > 0:
            self.write_handle = self.loop.call_soon(self.write_ready, future, data, 0)
        else:
            future.set_result(0)

        return future

    @asyncio.coroutine
    def copy_to(self, dest, copy_len=-1):
        copied_size = 0
        while copy_len != 0:
            if copy_len >= 0:
                read_size = min(copy_len, self.DEFAULT_BLOCK_SIZE)
            else:
                read_size = self.DEFAULT_BLOCK_SIZE
            rcontent = yield from self.read(read_size)
            rlen = len(rcontent)

            if rlen <= 0:
                break

            write_res = dest.write(rcontent)
            if isinstance(write_res, asyncio.Future) \
                    or asyncio.iscoroutine(write_res):
                yield from write_res
            copied_size += rlen
            copy_len = copy_len - len(rcontent) if copy_len > 0 else copy_len

        return copied_size

    def close(self):
        self.fileobj.close()
        if hasattr(self, 'read_handle'):
            self.read_handle.cancel()
        if hasattr(self, 'write_handle'):
            self.write_handle.cancel()


STREAM_READ_BLOCK = 8192

@asyncio.coroutine
def aiohttp_read_all(stream, cb):
    c = yield from stream.read(STREAM_READ_BLOCK)
    while c:
        cb_res = cb(c)
        if isinstance(cb_res, asyncio.Future) \
                or asyncio.iscoroutine(cb_res):
            yield from cb_res
        c = yield from stream.read(8192)


@asyncio.coroutine
def aiohttp_read_all_into_bytearray(stream):
    content = bytearray()
    cb = lambda c: content.extend(c)
    yield from aiohttp_read_all(stream, cb)
    return content
