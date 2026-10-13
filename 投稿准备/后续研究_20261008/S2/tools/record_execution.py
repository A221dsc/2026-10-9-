"""Run a command once per label, preserving append-only execution evidence."""
import datetime
import json
import os
import re
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path


def record_command(command, label, root, log):
    """Reserve all outputs before spawn; never overwrite any existing evidence.

    The atomic attempt directory serializes concurrent uses of the same label.
    It is retained even for incomplete attempts, which must get a new label.
    A child that cannot be spawned has no process exit code; the receipt records
    the actual OS exception rather than inventing one.
    """
    if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', label) is None:
        raise ValueError('invalid evidence label')
    root, log = Path(root), Path(log)
    paths = [log / (label + suffix) for suffix in ('.stdout.txt', '.stderr.txt', '.execution.json')]
    if any(path.exists() or path.is_symlink() for path in paths):
        raise FileExistsError('evidence already exists for label ' + label)
    # mkdir is atomic. Concurrent losers stop before opening files or spawning.
    (log / (label + '.attempt')).mkdir(exist_ok=False)
    with ExitStack() as stack:
        stdout_file = stack.enter_context(paths[0].open('xb'))
        stderr_file = stack.enter_context(paths[1].open('xb'))
        receipt_file = stack.enter_context(paths[2].open('x', encoding='utf-8'))
        receipt = {
            'phase': label, 'command_argv': list(command), 'cwd': str(root),
            'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'stdout_path': str(paths[0]), 'stderr_path': str(paths[1]),
            'formal_runs': 0,
        }
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
        try:
            result = subprocess.run(command, capture_output=True, cwd=root, env=env)
        except OSError as exc:
            receipt.update({'status': 'SPAWN_FAILED', 'exit_code': None,
                            'spawn_error': {'type': type(exc).__name__, 'message': str(exc), 'errno': exc.errno}})
            stderr_file.write((type(exc).__name__ + ': ' + str(exc) + '\n').encode('utf-8'))
        else:
            stdout_file.write(result.stdout)
            stderr_file.write(result.stderr)
            receipt.update({'status': 'PROCESS_EXITED', 'exit_code': result.returncode})
        receipt['ended_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        json.dump(receipt, receipt_file, indent=2)
        receipt_file.write('\n')
    return receipt


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    root = Path(__file__).resolve().parents[1]
    if len(sys.argv) < 2:
        print('an evidence label is required', file=sys.stderr)
        return 2
    label = sys.argv[1]
    if label.startswith(('RED', 'GREEN')):
        command = [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', str(root / 'tests'), '-v']
        if label.startswith(('RED_RECORD', 'GREEN_RECORD')):
            command.extend(['-p', 'test_record_execution.py'])
    elif label == 'VERIFY':
        command = [sys.executable, '-B', str(root / 'tests' / 'verify_projection.py')]
    else:
        if len(sys.argv) != 4:
            print('preparation requires LABEL ARCHIVE OUT', file=sys.stderr)
            return 2
        command = [sys.executable, '-B', str(root / 'tools' / 'prepare_nasa.py'), '--archive', sys.argv[2], '--out', sys.argv[3]]
    log = root / 'artifacts' / 'diagnostics' / 'TDD_PREPARE_NASA_20261013_01'
    try:
        receipt = record_command(command, label, root, log)
    except (ValueError, OSError) as exc:
        print(json.dumps({'status': 'RECORDING_REFUSED', 'error': str(exc), 'formal_runs': 0}), file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2))
    print(Path(receipt['stdout_path']).read_bytes().decode('utf-8', errors='replace'))
    print(Path(receipt['stderr_path']).read_bytes().decode('utf-8', errors='replace'))
    return receipt['exit_code'] if receipt['exit_code'] is not None else 1

if __name__ == '__main__':
    raise SystemExit(main())
