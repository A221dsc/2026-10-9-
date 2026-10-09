"""Download complete calendar-month pickup projections from official NYC Open Data.

No index or operation-performance experiment is run by this program.
"""
from __future__ import annotations

import array
import csv
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
MANIFEST = DATA / "manifest.json"
DATASET_ID = "rwwi-khbc"
API = f"https://data.cityofnewyork.us/resource/{DATASET_ID}"
METADATA_URL = f"https://data.cityofnewyork.us/api/views/{DATASET_ID}.json"
PAGE_SIZE = 100_000
EPOCH = dt.datetime(1970, 1, 1)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def request_bytes(url: str, limit: int = 20_000_000) -> tuple[bytes, dict]:
    for attempt in range(6):
        try:
            start = utc_now()
            request = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
            with urllib.request.urlopen(request, timeout=90) as response:
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise RuntimeError(f"response exceeded bounded read: {url}")
                return body, {
                    "url": url,
                    "download_start_utc": start,
                    "download_end_utc": utc_now(),
                    "http_status": response.status,
                    "response_bytes": len(body),
                    "content_type": response.headers.get("Content-Type"),
                    "response_sha256": hashlib.sha256(body).hexdigest(),
                }
        except Exception as exc:
            if attempt == 5:
                raise
            delay = min(2 ** attempt, 15)
            print(f"RETRY {attempt + 1}: {type(exc).__name__}: {exc}; {delay}s", flush=True)
            time.sleep(delay)
    raise AssertionError("unreachable")


def request_json(url: str) -> tuple[dict | list, dict]:
    body, audit = request_bytes(url, limit=2_000_000)
    return json.loads(body), audit


def api_url(extension: str, query: dict[str, str | int]) -> str:
    return API + extension + "?" + urllib.parse.urlencode(query)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(manifest: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    temporary = MANIFEST.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(MANIFEST)


def version_fields(metadata: dict) -> dict:
    return {name: metadata.get(name) for name in ("rowsUpdatedAt", "viewLastModified", "publicationDate")}


def parse_native(value: str) -> tuple[int, int]:
    # Floating Timestamp is timezone-free, always returned at millisecond
    # precision. Use arithmetic on naive civil-time values, not a host timezone
    # conversion, so the key encoding is machine independent.
    timestamp = dt.datetime.fromisoformat(value)
    if timestamp.tzinfo is not None or timestamp.microsecond % 1000:
        raise ValueError(f"unexpected timezone or sub-millisecond precision: {value}")
    delta = timestamp - EPOCH
    key_ms = (delta.days * 86400 + delta.seconds) * 1000 + timestamp.microsecond // 1000
    if key_ms < 0:
        raise ValueError("unexpected pre-epoch timestamp")
    fraction_digits = len(value.partition(".")[2]) if "." in value else 0
    return key_ms, fraction_digits


def self_test() -> None:
    if parse_native("1970-01-01T00:00:00.000") != (0, 3):
        raise AssertionError("epoch encoding failed")
    if parse_native("1970-01-01T00:00:01.001") != (1001, 3):
        raise AssertionError("native milliseconds were lost")
    if parse_native("2024-02-29T23:59:59.000")[0] != 1709251199000:
        raise AssertionError("leap-day encoding failed")


def download_month(month: str, next_month: str, manifest: dict) -> None:
    name = "tlc_yellow_pickup_" + month.replace("-", "_")
    where = (f"tpep_pickup_datetime >= '{month}-01T00:00:00' AND "
             f"tpep_pickup_datetime < '{next_month}-01T00:00:00'")
    count_url = api_url(".json", {
        "$select": "count(*) as rows,count(distinct tpep_pickup_datetime) as distinct_timestamps,"
                   "min(tpep_pickup_datetime) as first_time,max(tpep_pickup_datetime) as last_time",
        "$where": where,
    })
    official_rows, count_audit = request_json(count_url)
    if not isinstance(official_rows, list) or len(official_rows) != 1:
        raise RuntimeError("unexpected official aggregate response")
    aggregate = official_rows[0]
    expected_rows = int(aggregate["rows"])
    expected_distinct = int(aggregate["distinct_timestamps"])
    print(f"MONTH {month}: official rows={expected_rows}, distinct={expected_distinct}; "
          f"estimated CSV={expected_rows * 26 + 23:,} bytes", flush=True)

    existing = manifest.get("datasets", {}).get(name)
    if existing and existing.get("status") == "complete":
        raw_path = DATA / existing["csv"]["file"]
        binary_path = DATA / existing["binary"]["file"]
        if (raw_path.exists() and binary_path.exists()
                and sha256_file(raw_path) == existing["csv"]["sha256"]
                and sha256_file(binary_path) == existing["binary"]["sha256"]
                and existing["downloaded_rows"] == expected_rows):
            print(f"SKIP verified complete month {month}", flush=True)
            return
        raise RuntimeError(f"existing complete month no longer verifies: {month}")

    before, before_audit = request_json(METADATA_URL)
    if not isinstance(before, dict):
        raise RuntimeError("unexpected dataset metadata")
    record = {
        "status": "downloading",
        "calendar_month": month,
        "source_dataset_id": DATASET_ID,
        "source_dataset_url": f"https://data.cityofnewyork.us/Transportation/2024-Yellow-Taxi-Trip-Data/{DATASET_ID}",
        "source_agency": "New York City Taxi and Limousine Commission",
        "source_license": "Unspecified in official dataset metadata; NYC terms apply; do not label CC0",
        "projection": ["tpep_pickup_datetime"],
        "where": where,
        "order": ":id",
        "row_identifier": "1-based ordinal position in the complete filtered projection ordered by source :id; source :id strings are not projected",
        "row_order_claim": "Stable official source row-id order, not chronological event arrival order",
        "download_start_utc": utc_now(),
        "official_aggregate": aggregate,
        "official_aggregate_request": count_audit,
        "source_metadata_before": version_fields(before),
        "source_metadata_before_request": before_audit,
        "pages": [],
        "downloaded_rows": 0,
    }
    manifest.setdefault("datasets", {})[name] = record
    write_manifest(manifest)

    path = DATA / (name + ".csv")
    partial_path = path.with_suffix(".csv.part")
    keys_ms = array.array("Q")
    distinct: set[int] = set()
    fractional_nonzero = 0
    fraction_lengths: set[int] = set()
    descents = 0
    adjacent_equal = 0
    previous = None
    min_text = None
    max_text = None
    with partial_path.open("wb") as destination:
        while len(keys_ms) < expected_rows:
            offset = len(keys_ms)
            requested = min(PAGE_SIZE, expected_rows - offset)
            page_url = api_url(".csv", {
                "$select": "tpep_pickup_datetime", "$where": where,
                "$order": ":id", "$limit": requested, "$offset": offset,
            })
            body, audit = request_bytes(page_url)
            rows = csv.reader(io.StringIO(body.decode("utf-8-sig")))
            header = next(rows)
            if header != ["tpep_pickup_datetime"]:
                raise RuntimeError(f"unexpected CSV header {header}")
            actual = 0
            for row in rows:
                if len(row) != 1 or not row[0]:
                    raise RuntimeError("missing timestamp in month-filtered projection")
                text = row[0]
                key, precision = parse_native(text)
                if not f"{month}-01T00:00:00" <= text < f"{next_month}-01T00:00:00":
                    raise RuntimeError("downloaded timestamp is outside fixed calendar month")
                if previous is not None:
                    descents += key < previous
                    adjacent_equal += key == previous
                previous = key
                fractional_nonzero += key % 1000 != 0
                if key % 1000 and fractional_nonzero == 1:
                    print(f"PRECISION NOTICE {month}: native non-whole-second value {text}; preserve milliseconds, never round", flush=True)
                fraction_lengths.add(precision)
                min_text = text if min_text is None else min(min_text, text)
                max_text = text if max_text is None else max(max_text, text)
                distinct.add(key)
                keys_ms.append(key)
                actual += 1
            if not actual or actual > requested:
                raise RuntimeError(f"invalid page cardinality {actual}/{requested}")
            # Preserve the returned CSV bytes; remove only duplicate page headers.
            if offset == 0:
                destination.write(body)
            else:
                destination.write(body.partition(b"\n")[2])
            destination.flush()
            audit.update({"offset": offset, "requested_limit": requested, "returned_rows": actual})
            record["pages"].append(audit)
            record["downloaded_rows"] = len(keys_ms)
            write_manifest(manifest)
            print(f"PAGE {month} {len(keys_ms):,}/{expected_rows:,} ({len(keys_ms)/expected_rows:.1%})", flush=True)

    # An explicit extra page proves that the aggregate cardinality did not hide
    # truncation or rows added after the initial aggregate request.
    tail_url = api_url(".csv", {
        "$select": "tpep_pickup_datetime", "$where": where,
        "$order": ":id", "$limit": 1, "$offset": expected_rows,
    })
    tail_body, tail_audit = request_bytes(tail_url)
    tail_rows = list(csv.reader(io.StringIO(tail_body.decode("utf-8-sig"))))
    if tail_rows != [["tpep_pickup_datetime"]]:
        raise RuntimeError("extra row appeared after expected month cardinality")
    record["end_of_projection_check"] = tail_audit

    after, after_audit = request_json(METADATA_URL)
    if version_fields(before) != version_fields(after):
        raise RuntimeError("official dataset version changed during download")
    official_after, official_after_audit = request_json(count_url)
    if official_after != official_rows:
        raise RuntimeError("official month aggregate changed during download")
    if len(keys_ms) != expected_rows or len(distinct) != expected_distinct:
        raise RuntimeError("downloaded cardinality or native distinct count differs from official aggregate")
    if min_text != aggregate["first_time"] or max_text != aggregate["last_time"]:
        raise RuntimeError("downloaded min/max differs from official aggregate")

    # Fractional timestamps are never rounded. Seconds are used only after
    # every downloaded native value has been shown to be exactly whole seconds.
    unit = "seconds" if fractional_nonzero == 0 else "milliseconds"
    values = array.array("Q", (v // 1000 for v in keys_ms)) if unit == "seconds" else keys_ms
    binary_path = DATA / (name + "_source_order_uint64_" + unit + ".bin")
    if sys.byteorder != "little":
        values.byteswap()
    with binary_path.open("wb") as binary:
        binary.write(struct.pack("<Q", len(values)))
        values.tofile(binary)
    if sys.byteorder != "little":
        values.byteswap()
    partial_path.replace(path)
    record.update({
        "status": "complete",
        "download_end_utc": utc_now(),
        "downloaded_rows": len(values),
        "native_distinct_timestamps": len(distinct),
        "duplicate_extra_records": len(values) - len(distinct),
        "duplicate_extra_record_fraction": 1 - len(distinct) / len(values),
        "duplicate_fraction_definition": "1 - distinct native timestamp count / record count; no deduplication is applied",
        "min_timestamp_native": min_text,
        "max_timestamp_native": max_text,
        "min_key": min(values),
        "max_key": max(values),
        "adjacent_descents_in_source_id_order": descents,
        "adjacent_equal_in_source_id_order": adjacent_equal,
        "adjacent_comparison_pairs": len(values) - 1,
        "native_type": "Socrata Floating Timestamp, millisecond precision, timezone-free",
        "fractional_digits_observed": sorted(fraction_lengths),
        "non_whole_second_records": fractional_nonzero,
        "lossless_whole_seconds_confirmed": fractional_nonzero == 0,
        "timestamp_encoding": "Timezone-free civil-time arithmetic from 1970-01-01 00:00:00; no timezone localization or UTC-instant claim",
        "csv": {"file": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)},
        "binary": {
            "file": binary_path.name, "bytes": binary_path.stat().st_size,
            "sha256": sha256_file(binary_path), "key_unit": unit,
            "format": "little-endian uint64 record count, followed by record_count little-endian uint64 keys in source :id order; record id is ordinal position+1",
            "lossless": True,
        },
        "source_metadata_after": version_fields(after),
        "source_metadata_after_request": after_audit,
        "official_aggregate_after_request": official_after_audit,
        "official_aggregate_before_after_equal": True,
        "source_version_before_after_equal": True,
        "native_rows_distinct_minmax_match_official_aggregate": True,
    })
    write_manifest(manifest)
    print(f"COMPLETE {month}: {len(values):,} rows; distinct={len(distinct):,}; "
          f"duplicate_extra={record['duplicate_extra_record_fraction']:.6%}; "
          f"descents={descents:,}; unit={unit}; CSV SHA256={record['csv']['sha256']}", flush=True)


def finalize_relative_binaries(manifest: dict, keep_intermediate: bool = False) -> None:
    for name, record in manifest["datasets"].items():
        if record.get("status") != "complete":
            raise RuntimeError(f"month is not complete: {name}")
        if record["binary"].get("key_origin") == "calendar_month_start":
            continue
        month = record["calendar_month"]
        start = dt.datetime.fromisoformat(month + "-01T00:00:00")
        end = dt.datetime(2024, 2, 1) if month == "2024-01" else dt.datetime(2024, 3, 1)
        span = int((end - start).total_seconds())
        unit = record["binary"]["key_unit"]
        multiplier = 1 if unit == "seconds" else 1000
        offset = int((start - EPOCH).total_seconds()) * multiplier
        source_path = DATA / record["binary"]["file"]
        values = array.array("Q")
        with source_path.open("rb") as source:
            n = struct.unpack("<Q", source.read(8))[0]
            values.fromfile(source, n)
            if source.read(1):
                raise RuntimeError("binary has trailing data")
        if sys.byteorder != "little":
            values.byteswap()
        if n != record["downloaded_rows"]:
            raise RuntimeError("binary header does not match verified month rows")
        relative = array.array("Q", (v - offset for v in values))
        if min(relative) < 0 or max(relative) >= span * multiplier:
            raise RuntimeError("relative calendar keys are outside verified month span")
        target_name = "tlc_" + month.replace("-", "_") + "_uint64"
        if unit != "seconds":
            target_name += "_milliseconds"
        target = DATA / (target_name + ".bin")
        if sys.byteorder != "little":
            relative.byteswap()
        with target.open("wb") as destination:
            destination.write(struct.pack("<Q", n))
            relative.tofile(destination)
        if sys.byteorder != "little":
            relative.byteswap()
        record["binary_intermediate"] = {
            "sha256": record["binary"]["sha256"],
            "operation": "subtract exact calendar-month start from each verified integer key; no sorting, rounding or row reordering",
        }
        record["binary"] = {
            "file": target.name, "bytes": target.stat().st_size, "sha256": sha256_file(target),
            "key_unit": unit, "key_origin": "calendar_month_start",
            "format": "8-byte little-endian uint64 row count followed by one 8-byte little-endian uint64 month-relative key per source :id-ordered row",
            "rowid": "array position+1", "stride": n + 1,
            "span_seconds": span, "span_key_units": span * multiplier,
            "lossless": True,
        }
        record["min_key"] = min(relative)
        record["max_key"] = max(relative)
        record["n"] = n
        record["stride"] = n + 1
        record["span"] = span * multiplier
        record["span_seconds"] = span
        record["month_start_native"] = month + "-01T00:00:00.000"
        record["key_unit"] = unit
        record["key_origin"] = "calendar_month_start"
        record["binary_file"] = target.name
        record["timestamp_encoding"] = "Exact integer seconds from calendar month start when whole seconds are confirmed; otherwise exact native milliseconds. Timezone-free civil arithmetic; no localization or UTC-instant claim."
        record["binary_finalized_utc"] = utc_now()
        write_manifest(manifest)
        if not keep_intermediate and source_path != target and source_path.resolve().parent == DATA.resolve():
            source_path.unlink()
        print(f"FINAL BINARY {month}: {target.name}; n={n:,}; unit={unit}; span_seconds={span}; "
              f"min={record['min_key']}; max={record['max_key']}; SHA256={record['binary']['sha256']}", flush=True)


def main() -> None:
    self_test()
    if "--self-test" in sys.argv:
        print("Timestamp precision self-test passed")
        return
    DATA.mkdir(parents=True, exist_ok=True)
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    else:
        manifest = {
            "created_utc": utc_now(), "purpose": "Complete real timestamp months for index experiments; no performance run",
            "selection_rule": "All official 2024 records whose native pickup timestamp falls within each fixed calendar month",
            "modifications": "Project pickup column only, retain every selected record and native CSV value, assign stable source-order ordinal ids; no timestamp rounding, duplication injection, deduplication or occupancy-based selection",
            "sources": {
                "official_tlc": "https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page",
                "official_2024_dataset": f"https://data.cityofnewyork.us/Transportation/2024-Yellow-Taxi-Trip-Data/{DATASET_ID}",
                "order_documentation": "https://dev.socrata.com/docs/queries/order.html",
                "floating_timestamp_documentation": "https://dev.socrata.com/docs/datatypes/floating_timestamp.html",
            },
            "datasets": {},
        }
    if "--finalize" in sys.argv:
        finalize_relative_binaries(manifest)
        return
    for month, next_month in (("2024-01", "2024-02"), ("2024-02", "2024-03")):
        download_month(month, next_month, manifest)
    finalize_relative_binaries(manifest)
    print("Both complete months downloaded and verified; no performance experiment was run.")


if __name__ == "__main__":
    main()
