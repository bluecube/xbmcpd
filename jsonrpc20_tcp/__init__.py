import socket
import threading
import logging
import json
import time
import codecs

from iterator_json import JsonParser

__all__ = ['JsonRPC', 'JsonRPCException']

class JsonRPCException(Exception):
    def __init__(self, err):
        self.code = err["code"]
        self.message = err["message"]
        self.data = err.get("data", None)

    def __str__(self):
        return "{} (code: {}, data: {})".format(
            self.message, self.code, repr(self.data))

def socket_iterator(s):
    decoder = codecs.lookup(JsonRPC.ENCODING).incrementaldecoder(errors='ignore')
    while True:
        data = s.recv(4096)

        if not data:
            decoder.decode('')
            return

        for c in decoder.decode(data):
            yield c

class ReadThread(threading.Thread):
    def __init__(self, jsonrpc, host, port):
        super(ReadThread, self).__init__(name="JsonRPC read thread")
        self.daemon = True
        self._jsonrpc = jsonrpc

    def run(self):
        parser = JsonParser(socket_iterator(self._jsonrpc._socket))
        for msg in parser:
            #TODO: We're not checking that the message is well formed.
            self._jsonrpc._msg_received(msg)
            

class NotificationProxy(object):
    def __init__(self, jsonrpc, method = ""):
        self._method = method
        self._jsonrpc = jsonrpc

    def __getattr__(self, name):
        if self._method != "":
            name = self._method + "." + name
        return Proxy(method=name, jsonrpc=self._jsonrpc)

    def _make_query_dict(self, args, kwargs):
        if len(args) and len(kwargs):
            raise Exception("You can't have both named and positional parameters")
        elif len(kwargs):
            params = kwargs
        else:
            params = args

        return {
            "jsonrpc": "2.0",
            "method": self._method,
            "params": params,
            }

    def __call__(self, *args, **kwargs):
        obj = self._make_query_dict(args, kwargs)
        self._jsonrpc._socket.sendall(json.dumps(obj))

    def _reply_received():
        self._lock.release()

class Proxy(NotificationProxy):
    def __call__(self, *args, **kwargs):
        obj = self._make_query_dict(args, kwargs)
        obj['id'] = self._jsonrpc._acquire_id(self)

        self._lock = threading.Lock()

        try:
            self._lock.acquire()

            self._jsonrpc._socket.sendall(json.dumps(obj))

            # the code for acquiring the lock with timeouts
            # is (almost) copied from threading.py in python standard library
            endtime = time.time() + self._jsonrpc.RESPONSE_TIMEOUT
            delay = 0.0005
            while True:
                gotit = self._lock.acquire(False)
                if gotit:
                    break
                remaining = endtime - time.time()
                if remaining <= 0:
                    raise Exception("Waiting for method reply timed out.")

                delay = min(2 * delay, remaining, 0.1)
                time.sleep(delay)
        finally:
            self._jsonrpc._release_id(obj['id'])
            try:
                self._lock.release()
            except threading.ThreadError:
                pass

        if 'error' in self._reply:
            raise JsonRPCException(self._reply['error'])

        return self._reply['result']

    def _reply_received(self, msg):
        self._reply = msg
        try:
            self._lock.release()
        except threading.ThreadError:
            pass


class JsonRPC(object):
    RESPONSE_TIMEOUT = 60
    ENCODING = 'utf-8'

    def __init__(self, host, port, handlers={}, default_handler=None):
        self._socket = socket.create_connection((host, port))
        self._lock = threading.Lock()

        self._thread = ReadThread(self, host, port)

        self._handlers = handlers
        
        if callable(default_handler):
            self._default_handler = default_handler

        self._waiting_for_reply = {}
        self._id = 0

        self._thread.start()

    @property
    def notification_proxy(self, method=''):
        return NotificationProxy(self, method)
    
    @property
    def call_proxy(self, method=''):
        return Proxy(self, method)

    def _default_handler(self, method, params):
        logging.warning('unhandled notification "{}"'.format(method))

    def _acquire_id(self, proxy):
        with self._lock:
            while self._id in self._waiting_for_reply:
                self._id = (self._id + 1) % 2**32
            
            self._waiting_for_reply[self._id] = proxy

            return self._id

    def _release_id(self, identifier):
        with self._lock:
            return self._waiting_for_reply.pop(identifier)
            
    def _msg_received(self, msg):
        if 'method' in msg:
            method = msg['method']
            params = msg['params']

            handler = self._handlers.get(method, self._default_handler)

            handler(method, params)
        elif 'id' in msg:
            try:
                with self._lock:
                    proxy = self._waiting_for_reply[msg['id']]
            except KeyError:
                pass
            else:
                proxy._reply_received(msg)

        else:
            raise Exception("I don't know what to do with this message.")
