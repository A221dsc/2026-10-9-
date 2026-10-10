"""Four registered CPU sampling attempts, no wall-time-derived CPU shares."""
from pathlib import Path
import argparse
import json
import shutil
import subprocess
import sys
import time
import entry_gate as gate
from diagnostic_launch import S1, ORIGINAL, METHODS, check_binding
from dev_launch import bind, dump
from pair_adapter import child_command


def observed(command, directory, name):
    directory.mkdir(parents=True, exist_ok=True)
    started = time.time_ns()
    proc = subprocess.run([str(a) for a in command], capture_output=True)
    (directory / (name + '.stdout.txt')).write_bytes(proc.stdout)
    (directory / (name + '.stderr.txt')).write_bytes(proc.stderr)
    receipt = {'command': list(map(str, command)), 'started_ns': started,
               'ended_ns': time.time_ns(), 'exit_code': proc.returncode, 'actual_exit_observed': True}
    dump(directory / (name + '.process.json'), receipt)
    return proc


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--resource', type=Path, required=True)
    p.add_argument('--latency', type=Path, required=True)
    a = p.parse_args()
    root = a.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    for mode, directory in [('resource', a.resource), ('latency', a.latency)]:
        complete = gate.load(directory / 'COMPLETE.json')
        gate.require(complete['status'] == 'PASS' and complete['actual_completed'] == 490
                     and complete['mode'] == mode, 'diagnostic batch incomplete; CPU stage not authorized yet')
    env = gate.load(gate.PROTOCOL)['environment']
    wpr = shutil.which('wpr.exe')
    binary = S1 / 'release/binaries/s1_native.exe'
    reviewed = gate.load(S1 / 'artifacts/driver/green_review_fixes_root_01/manifest.json')
    gate.require(gate.sha(binary) == reviewed['binary_sha'][binary.name], 'reviewed native identity changed')
    results = []
    for case in ('F01', 'F03', 'F06', 'F07'):
        directory = root / case
        directory.mkdir()
        status = {'case_id': case, 'seed': 91001, 'method': 'R6', 'purpose': 'CPU_SAMPLING_ONLY',
                  'native_rank_sample': False, 'binary': bind(binary), 'tool': wpr,
                  'CPU_percentage': None, 'wall_difference_used_as_CPU_share': False}
        if not wpr:
            status.update(status='UNAVAILABLE', reason='Windows sampling executable absent')
        else:
            before = observed([wpr, '-status'], directory, 'status_before')
            text = before.stdout.decode('utf8', errors='replace') + before.stderr.decode('utf8', errors='replace')
            if before.returncode != 0 or 'WPR is not recording' not in text:
                status.update(status='UNAVAILABLE', reason='cannot establish an unused WPR session; existing session untouched')
            else:
                start = observed([wpr, '-start', 'CPU', '-filemode'], directory, 'start')
                if start.returncode != 0:
                    status.update(status='UNAVAILABLE', reason='actual WPR CPU start rejected', tool_exit_code=start.returncode,
                                  stderr=(start.stdout + start.stderr).decode('utf8', errors='replace'))
                else:
                    input_dir = ORIGINAL / 'inputs' / f'final_{case}_91001'
                    cache = input_dir / 'cache.bin'
                    meta = gate.load(input_dir / 'cache.meta.json')
                    check_binding({'path': str(cache), 'sha256': meta['cache_sha']})
                    command = child_command(env['pin_tool'], binary, cache, meta['cache_sha'], 'R6',
                         directory / 'profiled_output', root.name, '1', f'CPU:{case}:91001', 1, 'A')
                    try:
                        child = observed(command, directory, 'profiled_child')
                    finally:
                        stopped = observed([wpr, '-stop', directory / 'CPU.etl'], directory, 'stop')
                    if child.returncode != 0 or stopped.returncode != 0:
                        status.update(status='FAIL', reason='actual profiled child or trace stop failed')
                    else:
                        status.update(status='CAPTURED_UNANALYZED', trace=bind(directory / 'CPU.etl'),
                             reason='Raw ETL retained; no validated stack-export and symbol attribution pipeline; CPU fractions unavailable')
        dump(directory / 'RESULT.json', status)
        results.append(status)
        print(case, status['status'], flush=True)
    dump(root / 'COMPLETE.json', {'status': 'DONE', 'registered_attempts': 4, 'actual_attempts': len(results),
         'results': results, 'CPU_shares_fabricated': False, 'timing_results_not_reselected': True})


if __name__ == '__main__':
    main()
