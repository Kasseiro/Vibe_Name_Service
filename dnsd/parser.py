import ipaddress
import struct
from dataclasses import dataclass, field, replace

HEADER_SIZE = 12
UDP_LIMIT = 512
MAX_LABEL = 63
MAX_NAME = 255

NOERROR = 0
FORMERR = 1
SERVFAIL = 2
NXDOMAIN = 3
NOTIMP = 4
REFUSED = 5

CLASS_IN = 1

TYPES = {
    "A": 1, "NS": 2, "MD": 3, "MF": 4, "CNAME": 5, "SOA": 6, "MB": 7, "MG": 8,
    "MR": 9, "NULL": 10, "WKS": 11, "PTR": 12, "HINFO": 13, "MINFO": 14,
    "MX": 15, "TXT": 16, "RP": 17, "AFSDB": 18, "SIG": 24, "KEY": 25,
    "AAAA": 28, "LOC": 29, "SRV": 33, "NAPTR": 35, "KX": 36, "CERT": 37,
    "DNAME": 39, "OPT": 41, "APL": 42, "DS": 43, "SSHFP": 44, "IPSECKEY": 45,
    "RRSIG": 46, "NSEC": 47, "DNSKEY": 48, "DHCID": 49, "NSEC3": 50,
    "NSEC3PARAM": 51, "TLSA": 52, "SMIMEA": 53, "HIP": 55, "CDS": 59,
    "CDNSKEY": 60, "OPENPGPKEY": 61, "CSYNC": 62, "ZONEMD": 63, "SVCB": 64,
    "HTTPS": 65, "SPF": 99, "TKEY": 249, "TSIG": 250, "IXFR": 251,
    "AXFR": 252, "MAILB": 253, "MAILA": 254, "ANY": 255, "URI": 256,
    "CAA": 257,
}
TYPE_NAMES = {code: name for name, code in TYPES.items()}

A = TYPES["A"]
NS = TYPES["NS"]
CNAME = TYPES["CNAME"]
SOA = TYPES["SOA"]
PTR = TYPES["PTR"]
AAAA = TYPES["AAAA"]
OPT = TYPES["OPT"]
ANY = TYPES["ANY"]

# RDATA layouts for types that embed domain names: an int is that many fixed
# bytes, "N" is a name, and whatever follows the layout is copied as is. Names
# are expanded on parse, because a compression pointer only means something
# inside the message it came from.
_LAYOUTS = {
    TYPES["NS"]: ("N",), TYPES["MD"]: ("N",), TYPES["MF"]: ("N",),
    TYPES["CNAME"]: ("N",), TYPES["SOA"]: ("N", "N"), TYPES["MB"]: ("N",),
    TYPES["MG"]: ("N",), TYPES["MR"]: ("N",), TYPES["PTR"]: ("N",),
    TYPES["MINFO"]: ("N", "N"), TYPES["MX"]: (2, "N"), TYPES["RP"]: ("N", "N"),
    TYPES["AFSDB"]: (2, "N"), TYPES["KX"]: (2, "N"), TYPES["SRV"]: (6, "N"),
    TYPES["DNAME"]: ("N",),
}
# Only the RFC 1035 types may be compressed on output (RFC 3597 section 4).
_COMPRESSIBLE = {TYPES[t] for t in ("NS", "MD", "MF", "CNAME", "SOA", "MB", "MG", "MR", "PTR", "MINFO", "MX")}


class ParseError(ValueError):
    pass


class DropQuery(Exception):
    """The input gets no reply at all."""


class QueryError(Exception):
    """The input gets a bare header reply with this RCODE."""

    def __init__(self, query_id, rcode, reason):
        super().__init__(reason)
        self.query_id = query_id
        self.rcode = rcode


def type_name(code):
    return TYPE_NAMES.get(code, f"TYPE{code}")


def type_code(name):
    name = name.upper()
    if name in TYPES:
        return TYPES[name]
    if name.startswith("TYPE") and name[4:].isdigit() and int(name[4:]) <= 0xFFFF:
        return int(name[4:])
    raise ValueError(f"unknown type: {name!r}")


# Names are text in presentation form: absolute, with "\." "\\" and "\DDD"
# escapes, so any wire label survives the round trip byte for byte.

def labels_to_text(labels):
    if not labels:
        return "."
    out = []
    for label in labels:
        for byte in label:
            if byte in b".\\":
                out.append("\\" + chr(byte))
            elif 0x21 <= byte <= 0x7E:
                out.append(chr(byte))
            else:
                out.append(f"\\{byte:03d}")
        out.append(".")
    return "".join(out)


def text_to_labels(name):
    if name in ("", "."):
        return ()
    labels = []
    label = bytearray()
    i = 0
    while i < len(name):
        char = name[i]
        if char == ".":
            if not label:
                raise ValueError(f"empty label in {name!r}")
            labels.append(bytes(label))
            label = bytearray()
        elif char == "\\":
            digits = name[i + 1:i + 4]
            if len(digits) == 3 and digits.isdigit() and int(digits) <= 255:
                label.append(int(digits))
                i += 3
            elif i + 1 < len(name):
                label += name[i + 1].encode("ascii")
                i += 1
            else:
                raise ValueError(f"dangling escape in {name!r}")
        else:
            label += char.encode("ascii")
        i += 1
    if label:
        labels.append(bytes(label))
    labels = tuple(labels)
    _check_labels(labels)
    return labels


def _check_labels(labels):
    if any(len(label) > MAX_LABEL for label in labels):
        raise ValueError("label over 63 bytes")
    if sum(len(label) + 1 for label in labels) + 1 > MAX_NAME:
        raise ValueError("name over 255 bytes")


def read_labels(data, offset):
    """Read a possibly compressed name; return (labels, offset after it)."""
    labels = []
    length = 1
    end = None
    seen = set()
    while True:
        if offset >= len(data):
            raise ParseError("name runs past the end of the packet")
        byte = data[offset]
        if byte & 0xC0 == 0xC0:
            if offset + 1 >= len(data):
                raise ParseError("truncated compression pointer")
            target = ((byte & 0x3F) << 8) | data[offset + 1]
            if end is None:
                end = offset + 2
            if target in seen:
                raise ParseError("compression pointer loop")
            if target >= len(data):
                raise ParseError("compression pointer outside the packet")
            seen.add(target)
            offset = target
            continue
        if byte & 0xC0:
            raise ParseError("label over 63 bytes")
        offset += 1
        if byte == 0:
            return tuple(labels), (offset if end is None else end)
        length += byte + 1
        if length > MAX_NAME:
            raise ParseError("name over 255 bytes")
        if offset + byte > len(data):
            raise ParseError("label runs past the end of the packet")
        labels.append(bytes(data[offset:offset + byte]))
        offset += byte


def read_name(data, offset):
    labels, offset = read_labels(data, offset)
    return labels_to_text(labels), offset


class _Writer:
    def __init__(self, compress=True):
        self.buf = bytearray()
        self.compress = compress
        self._offsets = {}

    def name(self, name, compress=True):
        labels = text_to_labels(name) if isinstance(name, str) else tuple(name)
        for i in range(len(labels)):
            suffix = labels[i:]
            if compress and self.compress and suffix in self._offsets:
                self.buf += struct.pack("!H", 0xC000 | self._offsets[suffix])
                return
            if len(self.buf) < 0x4000:
                self._offsets.setdefault(suffix, len(self.buf))
            self.buf.append(len(labels[i]))
            self.buf += labels[i]
        self.buf.append(0)

    def record(self, rr):
        self.name(rr.name)
        self.buf += struct.pack("!HHI", rr.rtype, rr.rclass, rr.ttl & 0xFFFFFFFF)
        start = len(self.buf)
        self.buf += b"\x00\x00"
        layout = _LAYOUTS.get(rr.rtype)
        if layout is None:
            self.buf += rr.rdata
        else:
            pos = 0
            for item in layout:
                if item == "N":
                    labels, pos = read_labels(rr.rdata, pos)
                    self.name(labels, compress=rr.rtype in _COMPRESSIBLE)
                else:
                    self.buf += rr.rdata[pos:pos + item]
                    pos += item
            self.buf += rr.rdata[pos:]
        struct.pack_into("!H", self.buf, start, len(self.buf) - start - 2)


@dataclass(frozen=True)
class Question:
    name: str
    qtype: int
    qclass: int = CLASS_IN

    @property
    def type_name(self):
        return type_name(self.qtype)


@dataclass(frozen=True)
class ResourceRecord:
    name: str
    rtype: int
    rclass: int
    ttl: int
    rdata: bytes

    @classmethod
    def from_text(cls, name, rtype, ttl, value, rclass=CLASS_IN):
        """Build an A, AAAA or CNAME record from zone file form."""
        if isinstance(rtype, str):
            rtype = type_code(rtype)
        if rtype == A:
            rdata = ipaddress.IPv4Address(value).packed
        elif rtype == AAAA:
            rdata = ipaddress.IPv6Address(value).packed
        elif rtype in _LAYOUTS and _LAYOUTS[rtype] == ("N",):
            rdata = encode_name(value)
        else:
            raise ValueError(f"cannot build {type_name(rtype)} from text")
        return cls(name, rtype, rclass, ttl, rdata)

    @property
    def type_name(self):
        return type_name(self.rtype)

    @property
    def value(self):
        """Zone file form of A, AAAA and single-name RDATA, else None."""
        try:
            if self.rtype == A and len(self.rdata) == 4:
                return str(ipaddress.IPv4Address(self.rdata))
            if self.rtype == AAAA and len(self.rdata) == 16:
                return str(ipaddress.IPv6Address(self.rdata))
            if _LAYOUTS.get(self.rtype) == ("N",):
                return read_name(self.rdata, 0)[0]
        except ParseError:
            pass
        return None

    @property
    def soa_minimum(self):
        """MINIMUM field of an SOA record, else None."""
        if self.rtype != SOA:
            return None
        try:
            _, pos = read_labels(self.rdata, 0)
            _, pos = read_labels(self.rdata, pos)
        except ParseError:
            return None
        if len(self.rdata) - pos != 20:
            return None
        return struct.unpack_from("!I", self.rdata, pos + 16)[0]


@dataclass
class Message:
    id: int = 0
    qr: bool = False
    opcode: int = 0
    aa: bool = False
    tc: bool = False
    rd: bool = False
    ra: bool = False
    z: bool = False
    ad: bool = False
    cd: bool = False
    rcode: int = NOERROR
    questions: list = field(default_factory=list)
    answers: list = field(default_factory=list)
    authority: list = field(default_factory=list)
    additional: list = field(default_factory=list)

    @property
    def question(self):
        return self.questions[0] if self.questions else None

    @property
    def flags(self):
        return (
            self.qr << 15 | (self.opcode & 0xF) << 11 | self.aa << 10 | self.tc << 9
            | self.rd << 8 | self.ra << 7 | self.z << 6 | self.ad << 5 | self.cd << 4
            | (self.rcode & 0xF)
        )

    def reply(self, rcode=NOERROR, aa=False):
        """Start a response: same ID, RD and question, QR=1, RA=1."""
        return Message(
            id=self.id, qr=True, opcode=self.opcode, aa=aa, rd=self.rd, ra=True,
            cd=self.cd, rcode=rcode, questions=list(self.questions),
        )

    def with_ttls_reduced(self, seconds):
        """Copy with every record TTL lowered by seconds, not below 0."""
        def reduce(records):
            return [
                rr if rr.rtype == OPT else replace(rr, ttl=max(0, rr.ttl - seconds))
                for rr in records
            ]
        return replace(
            self, questions=list(self.questions), answers=reduce(self.answers),
            authority=reduce(self.authority), additional=reduce(self.additional),
        )

    def to_wire(self, max_size=None):
        """Encode; past max_size, drop whole records from the end and set TC."""
        writer = _Writer()
        writer.buf += bytes(HEADER_SIZE)
        for q in self.questions:
            writer.name(q.name)
            writer.buf += struct.pack("!HH", q.qtype, q.qclass)
        counts = [len(self.questions), 0, 0, 0]
        truncated = False
        for index, section in enumerate((self.answers, self.authority, self.additional), 1):
            for rr in section:
                mark = len(writer.buf)
                writer.record(rr)
                if max_size is not None and len(writer.buf) > max_size:
                    del writer.buf[mark:]
                    truncated = True
                    break
                counts[index] += 1
            if truncated:
                break
        flags = self.flags | (0x0200 if truncated else 0)
        struct.pack_into("!HHHHHH", writer.buf, 0, self.id & 0xFFFF, flags, *counts)
        return bytes(writer.buf)


def encode_name(name):
    writer = _Writer(compress=False)
    writer.name(name)
    return bytes(writer.buf)


def _parse_header(data):
    if len(data) < HEADER_SIZE:
        raise ParseError("packet shorter than a header")
    ident, flags, *counts = struct.unpack_from("!HHHHHH", data)
    message = Message(
        id=ident, qr=bool(flags & 0x8000), opcode=(flags >> 11) & 0xF,
        aa=bool(flags & 0x0400), tc=bool(flags & 0x0200), rd=bool(flags & 0x0100),
        ra=bool(flags & 0x0080), z=bool(flags & 0x0040), ad=bool(flags & 0x0020),
        cd=bool(flags & 0x0010), rcode=flags & 0xF,
    )
    return message, counts


def _parse_question(data, offset):
    labels, offset = read_labels(data, offset)
    if offset + 4 > len(data):
        raise ParseError("question runs past the end of the packet")
    qtype, qclass = struct.unpack_from("!HH", data, offset)
    return Question(labels_to_text(labels), qtype, qclass), offset + 4


def _expand_rdata(data, start, end, rtype):
    layout = _LAYOUTS.get(rtype)
    if layout is None:
        return bytes(data[start:end])
    out = bytearray()
    pos = start
    for item in layout:
        if item == "N":
            labels, pos = read_labels(data, pos)
            out += encode_name(labels)
        else:
            pos += item
            out += data[pos - item:pos]
        if pos > end:
            raise ParseError("RDATA runs past its length")
    return bytes(out + data[pos:end])


def _parse_record(data, offset):
    name, offset = read_name(data, offset)
    if offset + 10 > len(data):
        raise ParseError("record header runs past the end of the packet")
    rtype, rclass, ttl, rdlength = struct.unpack_from("!HHIH", data, offset)
    offset += 10
    end = offset + rdlength
    if end > len(data):
        raise ParseError("RDATA runs past the end of the packet")
    rdata = _expand_rdata(data, offset, end, rtype)
    return ResourceRecord(name, rtype, rclass, ttl, rdata), end


def parse_message(data):
    """Parse a whole message, such as an upstream reply. Raises ParseError."""
    message, (qdcount, ancount, nscount, arcount) = _parse_header(data)
    offset = HEADER_SIZE
    for _ in range(qdcount):
        question, offset = _parse_question(data, offset)
        message.questions.append(question)
    for count, section in ((ancount, message.answers), (nscount, message.authority),
                           (arcount, message.additional)):
        for _ in range(count):
            rr, offset = _parse_record(data, offset)
            section.append(rr)
    return message


def parse_query(data):
    """Parse a client query by the contract's rules.

    Raises DropQuery when the input gets no reply, and QueryError when it gets
    a bare NOTIMP or FORMERR header. Records after the question are ignored.
    """
    try:
        message, counts = _parse_header(data)
    except ParseError:
        raise DropQuery("packet shorter than a header") from None
    if message.qr:
        raise DropQuery("packet is a response")
    if message.opcode != 0:
        raise QueryError(message.id, NOTIMP, f"opcode {message.opcode}")
    if counts[0] != 1:
        raise QueryError(message.id, FORMERR, f"QDCOUNT {counts[0]}")
    try:
        question, _ = _parse_question(data, HEADER_SIZE)
    except ParseError as e:
        raise QueryError(message.id, FORMERR, str(e)) from None
    message.questions.append(question)
    return message


def error_response(query_id, rcode):
    """Bare 12-byte header: the ID, QR=1, RA=1, the RCODE, all counts zero."""
    return struct.pack("!HHHHHH", query_id & 0xFFFF, 0x8080 | (rcode & 0xF), 0, 0, 0, 0)
