"""Prepare a timestamp-only projection of the pinned NASA July 1995 archive.

The CLI accepts only the pinned real source. project_gzip is the independent,
small-sample parser used by unit tests; it never relaxes CLI source identity.
"""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

SOURCE_URL = 'https://ita.ee.lbl.gov/traces/NASA_access_log_Jul95.gz'
SOURCE_PAGE = 'https://ita.ee.lbl.gov/html/contrib/NASA-HTTP.html'
ARCHIVE_SHA256 = '199109ed0f273e095da6ccd5fc9dc4cd8bb58daa06d62135e62090fea9d27488'
ARCHIVE_BYTES = 20676672
RAW_SHA256 = '96551161b5bdcaacbc3c17fa108191c478fb35dfe87895c16e34a8f6552bf29a'
ORIGIN = dt.datetime(1995, 7, 1, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
SPAN = 2678400
N = 262144
EXCLUSION = {'ordinal': 1891715, 'length_bytes': 8, 'reason': 'missing_timestamp_bracket_at_truncated_final_line'}
STAMP = re.compile(rb'\[(\d{2})/([A-Za-z]{3})/(\d{4}):(\d{2}):(\d{2}):(\d{2}) ([+-])(\d{2})(\d{2})\]')
MONTHS = {name.encode('ascii'): index for index, name in enumerate(('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'), 1)}


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def parse_timestamp(line):
    match = STAMP.search(line)
    if match is None:
        raise ValueError('invalid timestamp bracket')
    day, month, year, hour, minute, second, sign, tz_hour, tz_minute = match.groups()
    if int(tz_hour) > 23 or int(tz_minute) > 59:
        raise ValueError('invalid timezone')
    offset_minutes = (int(tz_hour) * 60 + int(tz_minute)) * (-1 if sign == b'-' else 1)
    try:
        stamp = dt.datetime(int(year), MONTHS[month], int(day), int(hour), int(minute), int(second), tzinfo=dt.timezone(dt.timedelta(minutes=offset_minutes)))
    except (KeyError, ValueError) as exc:
        raise ValueError('invalid date: ' + str(exc)) from exc
    return int((stamp - ORIGIN).total_seconds())


def project_gzip(archive, projection, exclusion=None):
    """Stream gzip, verify CRC/EOF, and preserve physical line identity.

    Exclusion is allowed only for the exact declared final physical line with
    no bracket, no final newline, and the declared byte length. No raw text is
    returned, persisted, analyzed for host/path, or included in error messages.
    """
    projection = Path(projection)
    digest = hashlib.sha256()
    physical = valid = raw_bytes = decreases = 0
    previous = minimum = maximum = None
    unique = bytearray(SPAN)
    unique_count = 0
    per_day = {}
    excluded = []
    exclusion_ended_with_newline = False
    try:
        with projection.open('xb') as target:
            target.write(struct.pack('<8sQQ', b'S2TIME01', 0, 0))
            with gzip.open(archive, 'rb') as stream:
                for physical, line in enumerate(stream, 1):
                    digest.update(line)
                    raw_bytes += len(line)
                    if excluded:
                        raise ValueError('declared exclusion must be the final physical line')
                    try:
                        seconds = parse_timestamp(line)
                    except ValueError as exc:
                        permitted = exclusion is not None and physical == exclusion['ordinal'] and len(line) == exclusion['length_bytes'] and b'[' not in line and b']' not in line and exclusion['reason'] == EXCLUSION['reason']
                        if not permitted:
                            raise ValueError('invalid timestamp at line ' + str(physical)) from exc
                        excluded.append(dict(exclusion))
                        exclusion_ended_with_newline = line.endswith(b'\n')
                        continue
                    if not 0 <= seconds < SPAN:
                        raise ValueError('timestamp outside fixed July domain at line ' + str(physical))
                    if previous is not None and seconds < previous:
                        decreases += 1
                        raise ValueError('timestamp decrease at line ' + str(physical))
                    if not unique[seconds]:
                        unique[seconds] = 1
                        unique_count += 1
                    day_number = seconds // 86400 + 1
                    per_day[str(day_number)] = per_day.get(str(day_number), 0) + 1
                    valid += 1
                    minimum = seconds if minimum is None else min(minimum, seconds)
                    maximum = seconds if maximum is None else max(maximum, seconds)
                    previous = seconds
                    target.write(struct.pack('<QQ', seconds, physical))
                # Iterating to true EOF forces gzip CRC/ISIZE and stream-end checks.
                if stream.read(1) != b'':
                    raise ValueError('gzip end check failed')
            if exclusion is not None and excluded != [exclusion]:
                raise ValueError('expected exclusion is absent')
            if exclusion_ended_with_newline:
                raise ValueError('declared final truncated exclusion has a newline')
            target.seek(0)
            target.write(struct.pack('<8sQQ', b'S2TIME01', valid, physical))
    except FileExistsError:
        raise
    except Exception:
        if projection.is_file():
            projection.unlink()
        raise
    return {
        'physical_lines': physical, 'valid_timestamp_records': valid,
        'excluded_lines': excluded, 'excluded_count': len(excluded),
        'unique_timestamps': unique_count, 'adjacent_time_decreases': decreases,
        'min_offset_seconds': minimum, 'max_offset_seconds': maximum,
        'records_per_day': per_day,
        'missing_calendar_days': [day for day in range(1, 32) if str(day) not in per_day],
        'stride': physical + 1, 'uncompressed_bytes': raw_bytes,
        'uncompressed_sha256': digest.hexdigest(),
        'gzip_crc_and_eof_checked': True, 'gzip_crc_checked': True,
        'gzip_isize_checked': True, 'gzip_stream_end_checked': True,
        'hosts_and_request_paths_analyzed': False,
    }


def prepare_nasa(archive, out):
    """Strict production qualification, using the receipt beside the archive."""
    archive, out = Path(archive).resolve(), Path(out).resolve()
    if out.exists():
        raise FileExistsError('output directory already exists: ' + str(out))
    archive_sha = sha256_file(archive)
    archive_bytes = archive.stat().st_size
    if archive_sha != ARCHIVE_SHA256 or archive_bytes != ARCHIVE_BYTES:
        raise ValueError('archive identity mismatch')
    receipt_path = archive.with_name('download_receipt.json')
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    if receipt.get('source') != SOURCE_URL or receipt.get('sha256') != archive_sha or receipt.get('bytes') != archive_bytes or receipt.get('status_code') != 200:
        raise ValueError('download receipt does not bind to actual archive identity')
    # No output directory is created until the source identity and receipt pass.
    out.mkdir(parents=True, exist_ok=False)
    projection = out / 'timestamps.bin'
    stats = project_gzip(archive, projection, exclusion=EXCLUSION)
    expected = {
        'physical_lines': 1891715, 'valid_timestamp_records': 1891714,
        'excluded_lines': [EXCLUSION], 'excluded_count': 1,
        'unique_timestamps': 1099798, 'adjacent_time_decreases': 0,
        'min_offset_seconds': 1, 'max_offset_seconds': 2381545,
        'missing_calendar_days': [29, 30, 31], 'stride': 1891716,
        'uncompressed_bytes': 205242368, 'uncompressed_sha256': RAW_SHA256,
    }
    for key, value in expected.items():
        if stats[key] != value:
            projection.unlink()
            raise ValueError('strict source qualification mismatch: ' + key)
    if stats['valid_timestamp_records'] < 5 * N:
        projection.unlink()
        raise ValueError('less than 5N records')
    manifest = dict(stats)
    manifest.update({
        'schema': 'S2_NASA_TIME_PROJECTION_V1', 'status': 'PASS_WITH_EXPLICIT_FINAL_LINE_EXCLUSION',
        'source_url': SOURCE_URL, 'source_page': SOURCE_PAGE,
        'archive_path_read_only': str(archive), 'archive_bytes': archive_bytes,
        'archive_sha256': archive_sha,
        'download_receipt_path_read_only': str(receipt_path),
        'download_receipt_sha256': hashlib.sha256(receipt_bytes).hexdigest(),
        'download_receipt': receipt,
        'domain_epoch_local': ORIGIN.isoformat(), 'domain_span_seconds': SPAN,
        'time_resolution_seconds': 1, 'N': N, 'required_records_5N': 5 * N,
        'meets_5N_threshold': True, 'same_second_duplicates_retained': True,
        'projection': {'file': projection.name, 'bytes': projection.stat().st_size,
                       'sha256': sha256_file(projection), 'magic_ascii': 'S2TIME01',
                       'header': ['magic[8]', 'u64_le_valid_count', 'u64_le_physical_lines'],
                       'record': ['u64_le_seconds_offset', 'u64_le_original_line_ordinal']},
        'formal_runs': 0, 'formal_experiments': 0, 'operation_workload_generated': False,
        'prepared_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
    })
    with (out / 'manifest.json').open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    try:
        manifest = prepare_nasa(args.archive, args.out)
    except (ValueError, OSError, EOFError) as exc:
        print(json.dumps({'status': 'FAIL', 'error': str(exc), 'formal_runs': 0}), file=sys.stderr)
        return 1
    print(json.dumps({'status': manifest['status'], 'out': str(args.out.resolve()), 'valid_timestamp_records': manifest['valid_timestamp_records'], 'projection_sha256': manifest['projection']['sha256'], 'formal_runs': 0}, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
