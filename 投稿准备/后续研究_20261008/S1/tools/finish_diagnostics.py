"""Advance remaining S1 stages only after actual complete predecessors.

No retries, no threshold selection, no native timing, no S2/S3 execution.
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import time
import traceback
from diagnostic_launch import S1
from dev_launch import bind, dump, log
import entry_gate as gate


def check_completion(process, complete, mode, count):
    gate.require(process['actual_exit_observed'] and process['exit_code'] == 0, 'actual predecessor exit failed/unobserved')
    gate.require(complete['status'] == 'PASS' and complete['mode'] == mode
                 and complete['actual_completed'] == count and complete['FAIL'] == 0, 'predecessor matrix incomplete')


def main():
    p = argparse.ArgumentParser()
    for name in ('resource', 'mechanism', 'capacity', 'latency', 'cpu', 'report', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args()
    root = a.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    dump(root / 'START.json', {'purpose': 'finish registered S1 only', 'resource': str(a.resource),
         'next_stages': ['latency', 'cpu', 'report'], 'S2_S3_authorized': False, 'started_ns': time.time_ns()})
    stage = 'wait resource actual completion'
    try:
        check_completion(gate.load(Path(str(a.mechanism) + '_execution') / 'process.json'),
                         gate.load(a.mechanism / 'COMPLETE.json'), 'mechanism', 18)
        receipt = Path(str(a.resource) + '_execution') / 'process.json'
        log(stage)
        while not receipt.exists():
            time.sleep(10)
        check_completion(gate.load(receipt), gate.load(a.resource / 'COMPLETE.json'), 'resource', 490)
        dump(root / 'RESOURCE_ACCEPTED.json', {'completion': bind(a.resource / 'COMPLETE.json'), 'actual_exit': bind(receipt)})
        tools = S1 / 'tools'
        def run(name, runtime, script, arguments):
            nonlocal stage
            stage = name
            command = [str(runtime), '-B', str(tools / 'logged_run.py'), '--output', str(root / (name + '_execution')),
                       '--', str(runtime), '-B', str(tools / script), *map(str, arguments)]
            # latency keeps the independently named standard outer receipt path.
            if name == 'latency':
                command[command.index('--output') + 1] = str(a.latency) + '_execution'
            log('advance ' + stage)
            started = time.time_ns()
            proc = subprocess.run(command)
            dump(root / (name + '_observed_exit.json'), {'command': command, 'exit_code': proc.returncode,
                 'actual_exit_observed': True, 'started_ns': started, 'ended_ns': time.time_ns()})
            gate.require(proc.returncode == 0, stage + ' actual process failed; no automatic retry')
        run('latency', sys.executable, 'diagnostic_launch.py', ['--mode', 'latency', '--output', a.latency,
                                                             '--capacity', a.capacity])
        check_completion(gate.load(Path(str(a.latency) + '_execution') / 'process.json'),
                         gate.load(a.latency / 'COMPLETE.json'), 'latency', 490)
        run('cpu', sys.executable, 'cpu_diagnostic.py', ['--output', a.cpu, '--resource', a.resource, '--latency', a.latency])
        cpu = gate.load(a.cpu / 'COMPLETE.json')
        gate.require(cpu['actual_attempts'] == 4 and all(r['status'] != 'FAIL' for r in cpu['results']), 'CPU actual child failure')
        plotting_python = Path('C:/Users/zhangjiacheng/AppData/Local/Programs/Python/Python313/python.exe')
        run('report', plotting_python, 'report_diagnostics.py', ['--mechanism', a.mechanism, '--resource', a.resource,
            '--latency', a.latency, '--cpu', a.cpu, '--output', a.report])
        dump(root / 'COMPLETE.json', {'status': 'S1_DIAGNOSTICS_COMPLETE', 'resource_runs': 490,
             'latency_runs': 490, 'mechanism_runs': 18, 'CPU_attempts': 4,
             'report': bind(a.report / 'S1_诊断完成记录.json'), 'S2_S3_started': False})
    except Exception as e:
        dump(root / 'STOPPED.json', {'status': 'STOPPED', 'stage': stage, 'error': repr(e),
             'traceback': traceback.format_exc(), 'all_attempts_retained': True, 'time_ns': time.time_ns()})
        raise


if __name__ == '__main__':
    main()
