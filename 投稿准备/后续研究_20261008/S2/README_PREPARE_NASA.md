# S2 NASA July 1995 timestamp preparation

This stage prepares data only. It does not compile a driver, generate an operation workload, or run a formal/performance experiment (`formal_runs = 0`).

`tools/prepare_nasa.py --archive ARCHIVE --out NEW_DIRECTORY` accepts only the pinned real NASA July 1995 gzip archive. The output directory must not exist. The actual archive SHA-256 and byte count must match; the read-only `download_receipt.json` beside the archive must bind the source URL, successful download, SHA-256, and byte count. The tool streams decompression through EOF, verifies gzip CRC/ISIZE, computes the decompressed SHA-256, and checks exact qualification counts. The CLI has no small-sample or relaxed-identity mode.

The only permitted exclusion is physical line 1891715, exactly 8 bytes, missing timestamp brackets and a final newline. It receives no invented timestamp. Every other invalid line, unexpected exclusion, decrease, outside-domain timestamp, or identity mismatch fails.

The fixed domain remains `1995-07-01T00:00:00-04:00` plus 2678400 seconds (31 calendar days). Source time precision remains one second; same-second duplicates remain separate records. Original physical line ordinals remain their identities. Hosts and request paths are neither analyzed nor emitted.

`timestamps.bin` has a 24-byte header: 8-byte ASCII magic `S2TIME01`, little-endian u64 valid count, little-endian u64 physical line count. Each following record is a little-endian u64 seconds offset and a little-endian u64 original physical line ordinal. The identity stride is `physical_lines + 1 = 1891716`. `manifest.json` includes exact exclusion, source/receipt binding, decompressed and projection SHA-256, missing calendar days, the 5N threshold, and gzip end checks.

The independent generic parser is tested with miniature gzip inputs. Its unit tests are separate from the strict real-source qualification. `tests/verify_projection.py` independently reads every produced record without importing the preparation module.

Evidence in `artifacts/diagnostics/TDD_PREPARE_NASA_20261013_01`:

- `RED_02.execution.json`, `.stdout.txt`, `.stderr.txt`: 15 expected test failures before the preparation tool existed, exit 1.
- `GREEN.execution.json`, `.stdout.txt`, `.stderr.txt`: all 15 tests passed, exit 0.
- `REAL_PREPARE.execution.json`, `.stdout.txt`, `.stderr.txt`: real-source preparation passed, exit 0.
- `VERIFY.execution.json`, `.stdout.txt`, `.stderr.txt`: all 1891714 binary records independently read back; size and SHA matched, exit 0.
- The initial `RED` subprocess evidence is retained too. Its subprocess correctly returned 1; the recorder's subsequent console display hit a GBK encoding error. The recorder was corrected before `RED_02`.

The source archive, its receipt, and the original FAIL qualification audit remain in the original workspace and were read only. The new manifest explicitly states `PASS_WITH_EXPLICIT_FINAL_LINE_EXCLUSION`; it does not replace the original audit.
