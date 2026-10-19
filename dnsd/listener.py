import socket
import socketserver
import struct
import threading

from dnsd.forwarder import parse_address
from dnsd.parser import UDP_LIMIT

TCP_IDLE_TIMEOUT = 10.0


class _UDPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data, sock = self.request
        reply = self.server.resolver.handle(data, self.client_address[0], UDP_LIMIT)
        if reply is not None:
            try:
                sock.sendto(reply, self.client_address)
            except OSError:
                pass


class _TCPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        sock = self.request
        sock.settimeout(TCP_IDLE_TIMEOUT)
        try:
            while True:
                data = self._read_message(sock)
                if data is None:
                    return
                reply = self.server.resolver.handle(data, self.client_address[0])
                if reply is None:
                    return
                sock.sendall(struct.pack("!H", len(reply)) + reply)
        except OSError:
            pass

    @staticmethod
    def _read_message(sock):
        header = _read_exactly(sock, 2)
        if header is None:
            return None
        (length,) = struct.unpack("!H", header)
        return _read_exactly(sock, length)


def _read_exactly(sock, count):
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            return None
        data += chunk
    return data


class _UDPServer(socketserver.ThreadingUDPServer):
    daemon_threads = True
    max_packet_size = 65535

    def __init__(self, family, address, resolver):
        self.address_family = family
        self.resolver = resolver
        super().__init__(address, _UDPHandler)


class _TCPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, family, address, resolver):
        self.address_family = family
        self.resolver = resolver
        super().__init__(address, _TCPHandler)


class Listener:
    """Serves DNS over UDP and TCP on the same address and port."""

    def __init__(self, address, resolver):
        host, port = parse_address(address)
        family, _, _, _, sockaddr = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0]
        self.tcp = _TCPServer(family, sockaddr, resolver)
        # With port 0, UDP takes the port the OS gave TCP.
        sockaddr = (sockaddr[0], self.tcp.server_address[1], *sockaddr[2:])
        try:
            self.udp = _UDPServer(family, sockaddr, resolver)
        except OSError:
            self.tcp.server_close()
            raise
        self._threads = []

    @property
    def address(self):
        return self.tcp.server_address

    def start(self):
        for server in (self.udp, self.tcp):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self._threads.append(thread)

    def serve_forever(self):
        self.start()
        for thread in self._threads:
            thread.join()

    def close(self):
        for server in (self.udp, self.tcp):
            if self._threads:
                server.shutdown()
            server.server_close()
        self._threads = []
