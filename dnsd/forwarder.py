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


def question_end(message):
    pos = HEADER_SIZE
    while pos < len(message):
        length = message[pos]
        if length == 0:
            end = pos + 5
            return end if end <= len(message) else None
        if length > 63:
            return None
        pos += length + 1
    return None


def question_of(message):
    end = question_end(message)
    return None if end is None else message[HEADER_SIZE:end].lower()


def strip_records(query):
    end = question_end(query)
    if end is None or query[4:6] != b"\x00\x01":
        return query
    return query[:6] + bytes(6) + query[HEADER_SIZE:end]


def remaining(deadline):
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError("upstream timed out")
    return left


def matches(query, reply):
    if len(reply) < HEADER_SIZE or reply[:2] != query[:2] or not reply[2] & QR:
        return False
    question = question_of(query)
    if question is None or reply[4:6] == b"\x00\x00":
        return True
    return question_of(reply) == question


class Forwarder:
    def __init__(self, upstream, timeout=2.0):
        host, port = parse_address(upstream)
        info = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)[0]
        self._family = info[0]
        self._address = info[4]
        self._timeout = timeout

    def forward(self, query):
        if len(query) < HEADER_SIZE:
            return None
        deadline = time.monotonic() + self._timeout
        packet = secrets.token_bytes(2) + strip_records(query)[2:]
        reply = self._udp(packet, deadline)
        if reply is not None and reply[2] & TC:
            reply = self._tcp(packet, deadline)
        if reply is None:
            return None
        return query[:2] + reply[2:]

    def _udp(self, packet, deadline):
        try:
            with socket.socket(self._family, socket.SOCK_DGRAM) as sock:
                sock.connect(self._address)
                sock.send(packet)
                while True:
                    sock.settimeout(remaining(deadline))
                    reply = sock.recv(65535)
                    if matches(packet, reply):
                        return reply
        except OSError:
            return None

    def _tcp(self, packet, deadline):
        try:
            with socket.socket(self._family, socket.SOCK_STREAM) as sock:
                sock.settimeout(remaining(deadline))
                sock.connect(self._address)
                sock.settimeout(remaining(deadline))
                sock.sendall(struct.pack("!H", len(packet)) + packet)
                (length,) = struct.unpack("!H", self._read(sock, 2, deadline))
                reply = self._read(sock, length, deadline)
                return reply if matches(packet, reply) else None
        except OSError:
            return None

    @staticmethod
    def _read(sock, count, deadline):
        data = b""
        while len(data) < count:
            sock.settimeout(remaining(deadline))
            chunk = sock.recv(count - len(data))
            if not chunk:
                raise ConnectionError("upstream closed the connection")
            data += chunk
        return data
