"""Parser-Tests. Frames im Originalformat der Waage, Werte und MAC sind synthetisch."""
import importlib.util, pathlib, sys

spec = importlib.util.spec_from_file_location(
    "parser", pathlib.Path(__file__).parents[1] / "custom_components/unique_health_scale/parser.py")
p = importlib.util.module_from_spec(spec); sys.modules["parser"] = p; spec.loader.exec_module(p)

ADV = [
 "aabbccddeeff0000000000000000000000",   # Ruhezustand
 "aabbccddeeffcf0000e10500000000012a",   # Gewicht schwankt
 "aabbccddeeffcf000000000000000001ce",
 "aabbccddeeffcf00004c1d00000000019f",
 "aabbccddeeffcf00004c1d000000000896",   # Gewicht steht fest
]

def test_adv():
    f = [p.find_cf_frame(bytes.fromhex(h)) for h in ADV]
    assert f[0] is None
    assert f[1].status == 1 and f[1].weight_kg == 15.05
    assert f[2].status == 1 and f[2].weight_kg == 0
    assert f[3].status == 1 and f[3].weight_kg == 75.0
    assert f[4].status == 8 and f[4].weight_kg == 75.0
    assert f[4].heart_rate is None

def test_checksum_is_xor():
    # Format wie von der Waage gesendet: cf 00 00 <Gewicht LE> 00 00 00 00 <Status> <XOR>
    assert p.parse_cf_frame(bytes.fromhex("cf0000e10500000000012a")).weight_kg == 15.05
    assert p.parse_cf_frame(bytes.fromhex("cf000004060000000001cc")).weight_kg == 15.40

def test_bad_checksum():
    assert p.parse_cf_frame(bytes.fromhex("cf00004c1d000000000800")) is None

def test_measurement_flow():
    m = p.Measurement()
    seen = []
    for h in ADV[1:]:
        m.feed_cf(p.find_cf_frame(bytes.fromhex(h)))
        seen.append(m.weight_kg)
    assert seen == [None, None, None, 75.0]
    assert m.weight_kg == 75.0 and not m.complete
    bf20 = bytes([0xBF, 0x00]) + b"".join(v.to_bytes(4,"little") for v in (1,2,3,4,5)) + b"\x00"
    bf100 = bytes([0xBF, 0x01]) + b"".join(v.to_bytes(4,"little") for v in (6,7,8,9,10)) + b"\x00"
    assert m.feed(bf20) and m.feed(bf100)
    assert m.impedances == {"z20_right_arm":1,"z20_left_arm":2,"z20_trunk":3,"z20_right_leg":4,"z20_left_leg":5,
                            "z100_right_arm":6,"z100_left_arm":7,"z100_trunk":8,"z100_right_leg":9,"z100_left_leg":10}
    assert m.impedances_complete
    end = bytearray.fromhex("cf48c04c1d000000000000"); end[10] = p._xor(end[:10])
    assert m.feed(bytes(end))
    assert m.complete and m.heart_rate == 0x48 and m.weight_kg == 75.0 and m.impedances_complete

def test_df():
    def df(part, freq, vals):
        body = bytes([0xDF, 0x02, part, freq]) + b"".join(v.to_bytes(4,"little") for v in vals)
        return body + bytes([p._xor(body)])
    m = p.Measurement()
    for part, freq, vals in ((0,0,(1,2,3)),(1,0,(4,5,0)),(0,1,(6,7,8)),(1,1,(9,10,0))):
        assert m.feed(df(part, freq, vals))
    assert m.impedances_complete and m.impedances["z100_left_leg"] == 10 and m.impedances["z20_right_leg"] == 4
    reset = bytes([0xDF,0xFF]) + bytes(14)
    assert m.feed(reset + bytes([p._xor(reset)])) and m.impedances == {}
    assert not m.feed(df(0, 0, (1, 2, 3))[:-1] + b"\x00")  # falsche Pruefsumme
    assert not m.feed(b"\x10\x00")


def encode(tenths, key, mult):
    """Gegenstueck zu decode_impedance, wie es die Waage anwendet."""
    t = (tenths ^ key) + key * mult
    n = [(t >> (4 * i)) & 0xF for i in range(4)]
    return n[0] | (key & 0xF) << 4 | n[1] << 8 | (key >> 4) << 12 | n[2] << 16 | mult << 20 | n[3] << 24 | 0x5 << 28

def test_decode_impedance():
    assert p.decode_impedance(encode(3100, 0x10, 0)) == 310.0
    for tenths in (250, 2600, 3100, 6999):
        for key in (0x00, 0x02, 0x9D, 0xFF):
            for mult in (0, 2, 7, 15):
                assert p.decode_impedance(encode(tenths, key, mult)) == tenths / 10
    assert p.decode_impedance(0) is None

def test_impedances_ohm():
    m = p.Measurement()
    assert m.impedances_ohm is None
    m.impedances = {k: encode(2500 + i, 0x21 + i, i) for i, k in enumerate(p.IMPEDANCE_KEYS)}
    assert m.impedances_ohm == {k: (2500 + i) / 10 for i, k in enumerate(p.IMPEDANCE_KEYS)}
