"""Actual-output regression checks for the three driver review findings."""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

S1 = Path(__file__).resolve().parents[1]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--artifact', required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--baseline', action='store_true')
    args = ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        raise ValueError('immutable safe tag required')
    source = S1 / args.artifact
    out = S1 / 'artifacts/driver' / args.tag
    out.mkdir(parents=True, exist_ok=False)
    inputs = {}
    results = []
    commands = []
    def load(path):
        inputs[str(path.relative_to(S1)).replace('\\', '/')] = sha(path)
        return path.read_text(encoding='utf-8')
    def check(name, fn):
        try:
            fn()
            result = {'id': name, 'status': 'PASS'}
        except AssertionError as err:
            result = {'id': name, 'status': 'FAIL', 'reason': str(err)}
        results.append(result)
        print(name, result['status'], result.get('reason', ''), flush=True)
    def actual_describe(method):
        command = [str(source / 's1_native.exe'), 'describe', '--method', method]
        p = subprocess.run(command, capture_output=True, timeout=55)
        commands.append({'command': command, 'exit_code': p.returncode})
        (out / (method + '.stdout.txt')).write_bytes(p.stdout)
        (out / (method + '.stderr.txt')).write_bytes(p.stderr)
        assert p.returncode == 0, 'describe process did not succeed'
        inputs[str((source / 's1_native.exe').relative_to(S1))] = sha(source / 's1_native.exe')
        return json.loads(p.stdout)
    def warning_gate():
        manifest = json.loads(load(source / 'manifest.json'))
        diagnostics = []
        for path in source.glob('*compile.stderr.txt'):
            if re.search(r'\bwarning:', load(path)):
                diagnostics.append(path.name)
        assert not (diagnostics and manifest['status'] == 'ENGINEERING_GREEN'), 'warning compile accepted as GREEN: ' + ','.join(diagnostics)
        if not args.baseline:
            spec = importlib.util.spec_from_file_location('driver_builder', S1 / 'tools/build_driver.py')
            builder = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(builder)
            probe = out / 'warning_probe.cpp'
            probe.write_text('int probe(int unused) { return 0; }\n', encoding='utf-8')
            command = [str(builder.COMPILER), '-std=c++17', '-Wall', '-Wextra', '-c', str(probe), '-o', str(out / 'warning_probe.o')]
            p = subprocess.run(command, capture_output=True, timeout=55)
            commands.append({'command': command, 'exit_code': p.returncode})
            (out / 'warning_probe.stdout.txt').write_bytes(p.stdout)
            (out / 'warning_probe.stderr.txt').write_bytes(p.stderr)
            assert p.returncode == 0 and b'warning:' in p.stderr, 'probe must really compile with warning and exit0'
            assert builder.compiler_warning_lines(p.stderr), 'actual warning must be rejected'
            assert not builder.compiler_warning_lines(b'clang version 23\n"-cc1" "-Wextra"\n'), '-### normal diagnostic text is not warning'
            try:
                builder.require_warning_free(p.stderr)
            except RuntimeError:
                pass
            else:
                raise AssertionError('exit0 compiler warning must fail the build acceptance gate')
            builder.require_warning_free(b'clang version 23\n"-cc1" "-Wextra"\n')
    def work_availability():
        for method in ('Original', 'M_LIST', 'R6'):
            desc = actual_describe(method)
            rows = list(csv.DictReader(load(source / 'native_cli' / method / 'raw_native.csv').splitlines()))
            assert len(rows) == 1
            available = rows[0]['total_avoidable_work'] != 'NA'
            assert desc['native_work_available'] is available, method + ' descriptor/raw W mismatch'
        if not args.baseline:
            for method in ('M_OBSERVE_LIST', 'M_NO_IDLE', 'M_EVENT_8', 'M_EVENT_16', 'M_EVENT_32', 'M_EVENT_64', 'M_FIXED_128', 'M_FIXED_512', 'M_FIXED_2048', 'M_FIXED_8192'):
                assert actual_describe(method)['native_work_available'] is True
    def unavailable_fields():
        summaries = {(mode, method): json.loads(load(source / (mode + '_cli') / method / 'latency_summary.json'))
                     for mode in ('latency', 'resource') for method in ('M_LIST', 'R6', 'Original')}
        (out / 'observed_summaries.json').write_text(json.dumps({mode + '/' + method: value for (mode, method), value in summaries.items()}, indent=2), encoding='utf-8')
        for mode in ('latency', 'resource'):
            for method in ('M_LIST', 'R6', 'Original'):
                summary = summaries[(mode, method)]
                for key in ('whole_peak_requested_bytes', 'owner_current_after_destroy', 'owner_live_after_destroy'):
                    if mode == 'latency':
                        assert summary[key] == 'NA', mode + '/' + method + '/' + key + ' is unmeasured, must be NA'
                    else:
                        assert isinstance(summary[key], int) and summary[key] >= 0
                assert summary['resource_metric'] == ('NA' if mode == 'latency' else 'simultaneous_live_requested_bytes_not_hardware_RSS')
                for key in ('diagnostic_list_work', 'range_buffers', 'epoch_scans', 'candidate_visits'):
                    assert summary[key] == 'NA' if method == 'Original' else isinstance(summary[key], int)
                if method == 'M_LIST':
                    assert summary['diagnostic_list_work'] > 0
                    assert summary['range_buffers'] == summary['epoch_scans'] == summary['candidate_visits'] == 0
                if mode == 'resource':
                    assert summary['owner_current_after_destroy'] == summary['owner_live_after_destroy'] == 0
    check('MF1', warning_gate)
    check('MF2', work_availability)
    check('MF3', unavailable_fields)
    record = {'schema': 'S1.driver.review.regression.v1', 'baseline': args.baseline,
              'results': results, 'inputs_sha256': inputs, 'commands': commands,
              'test_sha256': sha(Path(__file__)), 'performance_executed': False,
              'evidence_sha256': {p.name: sha(p) for p in out.iterdir() if p.is_file()}}
    (out / 'manifest.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return 1 if any(r['status'] == 'FAIL' for r in results) else 0

if __name__ == '__main__':
    sys.exit(main())
