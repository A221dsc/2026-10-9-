"""Independent binary read-back, without importing the preparation tool."""
import hashlib
import json
import struct
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
data = root / 'artifacts' / 'data' / 'NASA_JUL95_20261013_01'
manifest = json.loads((data / 'manifest.json').read_text(encoding='utf-8'))
projection = data / 'timestamps.bin'
digest = hashlib.sha256()
unique = set()
previous = -1
with projection.open('rb') as stream:
    header = stream.read(24)
    digest.update(header)
    assert struct.unpack('<8sQQ', header) == (b'S2TIME01', 1891714, 1891715)
    count = 0
    for ordinal in range(1, 1891715):
        raw = stream.read(16)
        assert len(raw) == 16
        digest.update(raw)
        seconds, original = struct.unpack('<QQ', raw)
        assert original == ordinal
        assert 0 <= seconds < 2678400 and seconds >= previous
        previous = seconds
        unique.add(seconds)
        count += 1
    assert stream.read(1) == b''
assert count == manifest['valid_timestamp_records'] == 1891714
assert len(unique) == manifest['unique_timestamps'] == 1099798
assert min(unique) == 1 and max(unique) == 2381545
assert projection.stat().st_size == 24 + 16 * count == 30267448
assert digest.hexdigest() == manifest['projection']['sha256'] == '8914c691dc39f0f425ade34d34789e2b1985a9434fe31d1300bccb79a641c81c'
assert manifest['stride'] == 1891716
assert manifest['domain_span_seconds'] == 2678400
assert manifest['excluded_lines'] == [{'ordinal': 1891715, 'length_bytes': 8, 'reason': 'missing_timestamp_bracket_at_truncated_final_line'}]
assert manifest['formal_runs'] == 0
assert manifest['missing_calendar_days'] == [29, 30, 31]
source_audit = Path(manifest['archive_path_read_only']).with_name('qualification_audit.json')
assert json.loads(source_audit.read_text(encoding='utf-8-sig'))['status'] == 'FAIL'
print(json.dumps({'status': 'PASS', 'binary_records_read_back': count, 'identity_preserved': True, 'projection_bytes': projection.stat().st_size, 'projection_sha256': digest.hexdigest(), 'original_qualification_audit_status': 'FAIL', 'original_qualification_audit_sha256_read_only': hashlib.sha256(source_audit.read_bytes()).hexdigest(), 'formal_runs': 0}, indent=2))
