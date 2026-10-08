import secrets
import socket
import struct
import time

HEADER_SIZE = 12
QR = 0x80
TC = 0x02


def parse_address(text, default_port=53):
    host, sep, port = text.rpartition(":")
    if not sep or "]" in port:
        host, port = text, default_port
    return host.strip("[]"), int(port)


def question_of(message):
    pos = HEADER_SIZE
    while pos < len(message):
        length = message[pos]
        if length == 0:
            end = pos + 5
            return message[HEADER_SIZE:end].lower() if end <= len(message) else None
        if length > 63:
            return None
        pos += length + 1
    return None


def matches(query, reply):
    if len(reply) < HEADER_SIZE or reply[:2] != query[:2] or not reply[2] & QR:
        return False
    question = question_of(query)
    if question is None or reply[4:6] == b"\x00\x00":
        return True
    return question_of(reply) == question


class Forwarder:
    def __init__(self, upstream, timeout=2.0, attempts=2):
        host, port = parse_address(upstream)
        info = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)[0]
        self._family = info[0]
        self._address = info[4]
        self._timeout = timeout
        self._attempts = attempts

    def forward(self, query):
        if len(query) < HEADER_SIZE:
            return None
        for _ in range(self._attempts):
            packet = secrets.token_bytes(2) + query[2:]
            reply = self._udp(packet)
            if reply is not None and reply[2] & TC:
                reply = self._tcp(packet) or reply
            if reply is not None:
                return query[:2] + reply[2:]
        return None

    def _udp(self, packet):
        try:
            with socket.socket(self._family, socket.SOCK_DGRAM) as sock:
                sock.connect(self._address)
                sock.send(packet)
                deadline = time.monotonic() + self._timeout
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None
                    sock.settimeout(remaining)
                    reply = sock.recv(65535)
                    if matches(packet, reply):
                        return reply
        except OSError:
            return None

    def _tcp(self, packet):
        try:
            with socket.socket(self._family, socket.SOCK_STREAM) as sock:
                sock.settimeout(self._timeout)
                sock.connect(self._address)
                sock.sendall(struct.pack("!H", len(packet)) + packet)
                (length,) = struct.unpack("!H", self._read(sock, 2))
                reply = self._read(sock, length)
                return reply if matches(packet, reply) else None
        except OSError:
            return None

    @staticmethod
    def _read(sock, count):
        data = b""
        while len(data) < count:
            chunk = sock.recv(count - len(data))
            if not chunk:
                raise ConnectionError("upstream closed the connection")
            data += chunk
        return data
