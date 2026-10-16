import random
import struct
import unittest

from dnsd import parser
from dnsd.parser import (
    AAAA, CNAME, FORMERR, NOERROR, NOTIMP, NXDOMAIN, OPT, SOA,
    A, DropQuery, Message, ParseError, Question, QueryError, ResourceRecord,
)


def header(ident=0x1234, flags=0x0100, qd=1, an=0, ns=0, ar=0):
    return struct.pack("!HHHHHH", ident, flags, qd, an, ns, ar)


def wire_name(name):
    out = b""
    for label in name.rstrip(".").split("."):
        if label:
            out += bytes([len(label)]) + label.encode()
    return out + b"\x00"


def query(name="example.com.", qtype=A, **kwargs):
    return header(**kwargs) + wire_name(name) + struct.pack("!HH", qtype, 1)


OPT_RECORD = b"\x00" + struct.pack("!HHIH", OPT, 4096, 0, 0)


class ParseQueryTest(unittest.TestCase):
    def test_simple_query(self):
        msg = parser.parse_query(query("nas.home.lan.", AAAA))
        self.assertEqual(msg.id, 0x1234)
        self.assertTrue(msg.rd)
        self.assertFalse(msg.qr)
        self.assertEqual(msg.question, Question("nas.home.lan.", AAAA, 1))
        self.assertEqual(msg.question.type_name, "AAAA")

    def test_case_is_preserved(self):
        msg = parser.parse_query(query("NaS.Home.LAN."))
        self.assertEqual(msg.question.name, "NaS.Home.LAN.")

    def test_root_name(self):
        msg = parser.parse_query(header() + b"\x00" + struct.pack("!HH", 2, 1))
        self.assertEqual(msg.question.name, ".")

    def test_records_after_question_are_ignored(self):
        data = query(ar=1) + OPT_RECORD
        msg = parser.parse_query(data)
        self.assertEqual(msg.additional, [])
        # Even a garbage record after the question does not matter.
        msg = parser.parse_query(query(an=3) + b"\xff\xff")
        self.assertEqual(msg.question.name, "example.com.")

    def test_trailing_bytes_are_ignored(self):
        self.assertEqual(parser.parse_query(query() + b"junk").question.qtype, A)

    def test_short_packet_is_dropped(self):
        for length in range(12):
            with self.assertRaises(DropQuery):
                parser.parse_query(query()[:length])

    def test_response_is_dropped(self):
        with self.assertRaises(DropQuery):
            parser.parse_query(query(flags=0x8100))

    def assert_rcode(self, data, rcode, ident=0x1234):
        with self.assertRaises(QueryError) as ctx:
            parser.parse_query(data)
        self.assertEqual(ctx.exception.rcode, rcode)
        self.assertEqual(ctx.exception.query_id, ident)

    def test_other_opcode_is_notimp(self):
        for opcode in (1, 2, 4, 5, 15):
            self.assert_rcode(query(flags=opcode << 11), NOTIMP)

    def test_opcode_checked_before_qdcount(self):
        self.assert_rcode(header(flags=2 << 11, qd=0), NOTIMP)

    def test_qdcount_other_than_one_is_formerr(self):
        self.assert_rcode(header(qd=0), FORMERR)
        self.assert_rcode(query(qd=2) + wire_name("b.") + b"\x00\x01\x00\x01", FORMERR)

    def test_header_only_is_formerr(self):
        self.assert_rcode(header(ident=7), FORMERR, ident=7)

    def test_packet_ends_early(self):
        full = query("example.com.")
        for cut in range(13, len(full)):
            self.assert_rcode(full[:cut], FORMERR)

    def test_label_over_63_bytes(self):
        self.assert_rcode(header() + b"\x40" + b"a" * 64 + b"\x00\x00\x01\x00\x01", FORMERR)
        # 0x80 is a reserved label type, also not a valid length.
        self.assert_rcode(header() + b"\x80" + b"a" * 64 + b"\x00\x00\x01\x00\x01", FORMERR)

    def test_label_of_63_bytes_is_fine(self):
        name = "a" * 63 + ".com."
        self.assertEqual(parser.parse_query(query(name)).question.name, name)

    def test_name_over_255_bytes(self):
        # Four 63-byte labels: 4 * 64 + 1 = 257 bytes on the wire.
        self.assert_rcode(query(".".join(["a" * 63] * 4) + "."), FORMERR)

    def test_name_of_255_bytes_is_fine(self):
        # 3 * 64 + 62 + 1 = 255 bytes on the wire.
        name = ".".join(["a" * 63] * 3 + ["b" * 61]) + "."
        self.assertEqual(len(parser.encode_name(name)), 255)
        self.assertEqual(parser.parse_query(query(name)).question.name, name)

    def test_pointer_to_itself(self):
        self.assert_rcode(header() + b"\xc0\x0c\x00\x01\x00\x01", FORMERR)

    def test_pointer_loop_through_labels(self):
        # offset 12: "a" then a pointer back to offset 12.
        self.assert_rcode(header() + b"\x01a\xc0\x0c\x00\x01\x00\x01", FORMERR)

    def test_pointer_outside_packet(self):
        self.assert_rcode(header() + b"\xc0\xff\x00\x01\x00\x01", FORMERR)
        self.assert_rcode(header() + b"\xff\xff\x00\x01\x00\x01", FORMERR)

    def test_truncated_pointer(self):
        self.assert_rcode(header() + b"\xc0", FORMERR)

    def test_valid_forward_pointer(self):
        # The question name points to "example.com." stored after it.
        data = header() + b"\x03www\xc0\x16" + b"\x00\x01\x00\x01" + wire_name("example.com.")
        self.assertEqual(parser.parse_query(data).question.name, "www.example.com.")

    def test_pointer_chain_over_255_bytes(self):
        # Each pointer hop adds a 63-byte label; the name grows past 255.
        body = b""
        base = 12 + 6
        for i in range(5):
            body += b"\x3f" + b"a" * 63 + struct.pack("!H", 0xC000 | (base + (i + 1) * 66))
        body += b"\x00"
        data = header() + b"\xc0" + bytes([base]) + b"\x00\x01\x00\x01" + body
        self.assert_rcode(data, FORMERR)

    def test_random_input_never_crashes(self):
        rng = random.Random(1035)
        seeds = [query(), query(ar=1) + OPT_RECORD, header() + b"\x03www\xc0\x16\x00\x01\x00\x01"]
        for _ in range(20000):
            if rng.random() < 0.3:
                data = rng.randbytes(rng.randrange(40))
            else:
                data = bytearray(rng.choice(seeds))
                for _ in range(rng.randrange(1, 5)):
                    data[rng.randrange(len(data))] = rng.randrange(256)
                data = bytes(data[:rng.randrange(len(data) + 1)])
            try:
                parser.parse_query(data)
            except (DropQuery, QueryError):
                pass


class ErrorResponseTest(unittest.TestCase):
    def test_bare_header(self):
        data = parser.error_response(0xBEEF, FORMERR)
        self.assertEqual(data, b"\xbe\xef\x80\x81" + bytes(8))
        msg = parser.parse_message(parser.error_response(1, NOTIMP))
        self.assertTrue(msg.qr and msg.ra)
        self.assertEqual(msg.rcode, NOTIMP)
        self.assertEqual(msg.questions, [])


class NameTextTest(unittest.TestCase):
    def test_escapes_round_trip(self):
        labels = (b"a.b", b"back\\slash", b"sp ace", b"\xff\x00", b"Mixed")
        text = parser.labels_to_text(labels)
        self.assertEqual(text, "a\\.b.back\\\\slash.sp\\032ace.\\255\\000.Mixed.")
        self.assertEqual(parser.text_to_labels(text), labels)

    def test_trailing_dot_optional(self):
        self.assertEqual(parser.text_to_labels("a.b"), parser.text_to_labels("a.b."))

    def test_bad_text_names(self):
        for bad in ("a..b.", ".a.", "a" * 64 + ".", "x\\", ".".join(["a" * 63] * 4)):
            with self.assertRaises(ValueError):
                parser.encode_name(bad)

    def test_types(self):
        self.assertEqual(parser.type_name(1), "A")
        self.assertEqual(parser.type_name(255), "ANY")
        self.assertEqual(parser.type_name(65280), "TYPE65280")
        self.assertEqual(parser.type_code("aaaa"), AAAA)
        self.assertEqual(parser.type_code("TYPE65280"), 65280)
        with self.assertRaises(ValueError):
            parser.type_code("BOGUS")


def soa(name="home.lan.", ttl=3600, minimum=300):
    rdata = (parser.encode_name("ns." + name) + parser.encode_name("admin." + name)
             + struct.pack("!IIIII", 1, 7200, 900, 86400, minimum))
    return ResourceRecord(name, SOA, 1, ttl, rdata)


class MessageTest(unittest.TestCase):
    def reply(self):
        msg = parser.parse_query(query("Files.Home.Lan.")).reply(aa=True)
        msg.answers = [
            ResourceRecord.from_text("Files.Home.Lan.", "CNAME", 300, "nas.home.lan."),
            ResourceRecord.from_text("nas.home.lan.", "A", 300, "192.168.1.10"),
            ResourceRecord.from_text("nas.home.lan.", "A", 60, "192.168.1.11"),
        ]
        msg.authority = [soa()]
        return msg

    def test_reply_header(self):
        msg = parser.parse_query(query(ident=0xABCD, flags=0x0110)).reply(NXDOMAIN, aa=True)
        data = msg.to_wire()
        self.assertEqual(data[:2], b"\xab\xcd")
        back = parser.parse_message(data)
        self.assertTrue(back.qr and back.aa and back.rd and back.ra and back.cd)
        self.assertFalse(back.tc)
        self.assertEqual(back.rcode, NXDOMAIN)
        self.assertEqual(back.question.name, "example.com.")

    def test_question_bytes_copied_unchanged(self):
        data = query("WwW.ExAmple.COM.", AAAA)
        out = parser.parse_query(data).reply().to_wire()
        self.assertEqual(out[12:], data[12:])

    def test_round_trip(self):
        msg = self.reply()
        back = parser.parse_message(msg.to_wire())
        self.assertEqual(back, msg)
        self.assertEqual([rr.value for rr in back.answers],
                         ["nas.home.lan.", "192.168.1.10", "192.168.1.11"])
        self.assertEqual(back.authority[0].soa_minimum, 300)

    def test_compression_is_used(self):
        data = self.reply().to_wire()
        self.assertIn(b"\xc0", data)
        uncompressed = 12 + 4 + len(parser.encode_name("Files.Home.Lan."))
        for rr in self.reply().answers + self.reply().authority:
            uncompressed += len(parser.encode_name(rr.name)) + 10 + len(rr.rdata)
        self.assertLess(len(data), uncompressed)

    def test_compression_is_case_exact(self):
        # "Home.Lan." in the question must not be reused for "home.lan.".
        back = parser.parse_message(self.reply().to_wire())
        self.assertEqual(back.answers[1].name, "nas.home.lan.")
        self.assertEqual(back.answers[0].name, "Files.Home.Lan.")

    def test_aaaa_from_text(self):
        rr = ResourceRecord.from_text("nas.home.lan.", "AAAA", 300, "fd00::10")
        self.assertEqual(rr.rdata, bytes.fromhex("fd000000000000000000000000000010"))
        self.assertEqual(rr.value, "fd00::10")
        self.assertEqual(rr.type_name, "AAAA")

    def test_value_of_other_types_is_none(self):
        self.assertIsNone(ResourceRecord("x.", 16, 1, 1, b"\x03abc").value)
        self.assertIsNone(ResourceRecord("x.", A, 1, 1, b"\x01").value)
        self.assertIsNone(ResourceRecord("x.", A, 1, 1, b"\x01").soa_minimum)
        self.assertIsNone(ResourceRecord("x.", SOA, 1, 1, b"\x00\x00").soa_minimum)

    def test_unknown_rdata_kept_verbatim(self):
        msg = Message(id=1, qr=True, questions=[Question("x.", 99, 1)])
        msg.answers = [ResourceRecord("x.", 65280, 1, 5, b"\xc0\x0c raw")]
        back = parser.parse_message(msg.to_wire())
        self.assertEqual(back.answers[0].rdata, b"\xc0\x0c raw")

    def test_truncation(self):
        msg = parser.parse_query(query("many.example.com.")).reply()
        msg.answers = [
            ResourceRecord.from_text("many.example.com.", "A", 60, f"10.0.{i // 256}.{i % 256}")
            for i in range(100)
        ]
        full = msg.to_wire()
        self.assertGreater(len(full), 512)
        self.assertFalse(parser.parse_message(full).tc)
        data = msg.to_wire(max_size=512)
        self.assertLessEqual(len(data), 512)
        back = parser.parse_message(data)
        self.assertTrue(back.tc)
        self.assertEqual(back.question, msg.question)
        self.assertGreater(len(back.answers), 0)
        self.assertEqual(back.answers, msg.answers[:len(back.answers)])
        # The kept records are encoded exactly as in the full message.
        self.assertEqual(data[12:], full[12:len(data)])

    def test_truncation_drops_later_sections_first_record_that_overflows(self):
        msg = self.reply()
        msg.additional = [ResourceRecord("big.", 16, 1, 1, b"x" * 600)]
        back = parser.parse_message(msg.to_wire(max_size=512))
        self.assertTrue(back.tc)
        self.assertEqual(len(back.answers), 3)
        self.assertEqual(len(back.authority), 1)
        self.assertEqual(back.additional, [])

    def test_no_truncation_when_it_fits(self):
        data = self.reply().to_wire(max_size=512)
        self.assertFalse(parser.parse_message(data).tc)

    def test_ttls_reduced(self):
        msg = self.reply()
        msg.additional = [ResourceRecord(".", OPT, 4096, 0x8000, b"")]
        aged = msg.with_ttls_reduced(100)
        self.assertEqual([rr.ttl for rr in aged.answers], [200, 200, 0])
        self.assertEqual(aged.authority[0].ttl, 3500)
        self.assertEqual(aged.additional[0].ttl, 0x8000)
        self.assertEqual(msg.answers[0].ttl, 300)


class ParseMessageTest(unittest.TestCase):
    def upstream_reply(self):
        # Hand-written reply with compressed owner names and CNAME/SOA RDATA.
        q = wire_name("www.example.com.")
        body = q + b"\x00\x01\x00\x01"
        # answer 1: www.example.com. CNAME example.com. (pointer into question)
        body += b"\xc0\x0c" + struct.pack("!HHIH", CNAME, 1, 120, 2) + b"\xc0\x10"
        # answer 2: example.com. A 93.184.216.34
        body += b"\xc0\x10" + struct.pack("!HHIH", A, 1, 60, 4) + bytes([93, 184, 216, 34])
        # authority: example.com. SOA ns.example.com. hostmaster.example.com. ...
        rdata = b"\x02ns\xc0\x10" + b"\x0ahostmaster\xc0\x10" + struct.pack("!IIIII", 1, 2, 3, 4, 30)
        body += b"\xc0\x10" + struct.pack("!HHIH", SOA, 1, 900, len(rdata)) + rdata
        return header(flags=0x8180, an=2, ns=1) + body

    def test_compressed_reply(self):
        msg = parser.parse_message(self.upstream_reply())
        self.assertEqual(msg.rcode, NOERROR)
        self.assertTrue(msg.qr and msg.ra and msg.rd)
        self.assertEqual([rr.name for rr in msg.answers], ["www.example.com.", "example.com."])
        self.assertEqual(msg.answers[0].value, "example.com.")
        self.assertEqual(msg.answers[0].rdata, parser.encode_name("example.com."))
        self.assertEqual(msg.answers[1].value, "93.184.216.34")
        self.assertEqual(msg.authority[0].soa_minimum, 30)
        self.assertEqual(msg.authority[0].ttl, 900)

    def test_reencoded_reply_is_equal(self):
        msg = parser.parse_message(self.upstream_reply())
        self.assertEqual(parser.parse_message(msg.to_wire()), msg)

    def test_truncated_replies_raise(self):
        data = self.upstream_reply()
        for cut in range(len(data)):
            with self.assertRaises(ParseError):
                parser.parse_message(data[:cut])

    def test_rdlength_shorter_than_name(self):
        data = header(flags=0x8180, qd=0, an=1) + b"\x00" + struct.pack("!HHIH", CNAME, 1, 1, 1) + b"\x03abc\x00"
        with self.assertRaises(ParseError):
            parser.parse_message(data)

    def test_random_input_never_crashes(self):
        rng = random.Random(2308)
        seed = self.upstream_reply()
        for _ in range(20000):
            data = bytearray(seed)
            for _ in range(rng.randrange(1, 6)):
                data[rng.randrange(len(data))] = rng.randrange(256)
            try:
                msg = parser.parse_message(bytes(data))
            except ParseError:
                continue
            for rr in msg.answers + msg.authority + msg.additional:
                rr.value, rr.soa_minimum
            parser.parse_message(msg.to_wire(max_size=512))


if __name__ == "__main__":
    unittest.main()
