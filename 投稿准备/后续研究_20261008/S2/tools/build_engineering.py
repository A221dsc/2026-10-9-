"""Build only S2 native/resource engineering binaries; retain every actual exit."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

S2 = Path(__file__).resolve().parents[1]
ORIGINAL = Path('C:/Users/zhangjiacheng/Desktop/zjc/小论文')
LLVM = ORIGINAL / '投稿准备/adaptive_poolhbi/final_tools/llvm-mingw-20260922-ucrt-x86_64/bin/clang++.exe'
TLX = ORIGINAL / '投稿准备/adaptive_poolhbi/final_experiments/legacy/vendor/tlx'

def digest(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, default=S2 / 'artifacts/engineering/build_v1')
    a = p.parse_args()
    out = a.output.resolve()
    if not out.is_relative_to((S2 / 'artifacts/engineering').resolve()):
        p.error('build output must be S2/artifacts/engineering')
    out.mkdir(parents=True, exist_ok=False)
    inventory = [LLVM, TLX / 'tlx/die/core.cpp', S2 / 's2_protocol.json', Path(sys.executable)]
    inventory.extend(sorted((S2 / 'src').glob('*')))
    inventory.extend(sorted((TLX / 'tlx').rglob('*.hpp')))
    final = S2.parent.parent / 'adaptive_poolhbi/final'
    inventory.extend(sorted(final.glob('*.hpp')))
    core = final.parent / 'final_experiments'
    inventory.extend(core / name for name in ('driver_core.hpp', 'trace_cache.hpp', 'legacy/generators.hpp', 'legacy/public_index.hpp'))
    inventory.extend([S2.parent / 'S1/src/matched_index.hpp', S2.parent / 'S1/src/owner_tracker.hpp', S2.parent / 'S1/src/sha256.hpp', S2 / 'tests/test_s2_driver.cpp', Path(__file__)])
    inputs = [{'path': str(x.resolve()), 'sha256': digest(x)} for x in inventory]
    bundle = sorted(inputs, key=lambda entry: entry['path'])
    source_bundle_sha = hashlib.sha256(''.join(entry['path'] + '\n' + entry['sha256'] + '\n' for entry in bundle).encode('utf-8')).hexdigest()
    manifest = {'schema': 'S2.build.v1', 'engineering_only': True, 'python_version': sys.version, 'inputs': inputs, 'source_bundle_sha': source_bundle_sha, 'source_bundle_algorithm': 'sha256 UTF8 concatenation of sorted absolute path + LF + file SHA256 + LF', 'commands': []}
    common = [str(LLVM), '-std=c++17', '-O3', '-DNDEBUG', '-static', '-Wall', '-Wextra', '-Wno-unknown-pragmas', '-Wno-misleading-indentation', '-Wno-unused-function', '-DS2_SOURCE_BUNDLE_SHA="' + source_bundle_sha + '"', '-I', str(TLX)]
    failed = False
    core_object = out / 'tlx_die_core.o'
    core_command = common + ['-c', str(TLX / 'tlx/die/core.cpp'), '-o', str(core_object)]
    core_result = subprocess.run(core_command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    (out / 'tlx_core_compile.log').write_text(core_result.stdout + core_result.stderr, encoding='utf-8')
    manifest['commands'].append({'argv': core_command, 'exit_code': core_result.returncode, 'unit': 'tlx_core'})
    (out / 'build_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    if core_result.returncode or 'warning:' in core_result.stderr:
        return 1
    for mode in ('native', 'resource'):
        macros = [] if mode == 'native' else ['-DINDEX_MEMORY', '-DADAPTIVE_ALLOC_TRACK']
        for unit in ('test', 'driver'):
            source = S2 / ('tests/test_s2_driver.cpp' if unit == 'test' else 'src/s2_driver.cpp')
            exe = out / f's2_{unit}_{mode}.exe'
            deps = out / f'{unit}_{mode}.dependencies.txt'
            command = common + macros + ['-MMD', '-MF', str(deps)] + (['-municode'] if unit == 'driver' else []) + [str(source), str(core_object), '-o', str(exe)]
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
            (out / f'{unit}_{mode}_compile.log').write_text(result.stdout + result.stderr, encoding='utf-8')
            warnings = [line for line in result.stderr.splitlines() if 'warning:' in line]
            entry = {'argv': command, 'exit_code': result.returncode, 'mode': mode, 'unit': unit, 'compiler_warnings': warnings}
            failed |= bool(warnings)
            if result.returncode == 0:
                entry['binary_sha256'] = digest(exe)
                entry['dependencies'] = {'path': str(deps), 'sha256': digest(deps)}
                if unit == 'test':
                    test = subprocess.run([str(exe)], cwd=out, capture_output=True, text=True, encoding='utf-8', errors='replace')
                    (out / f'{unit}_{mode}_test.log').write_text(test.stdout + test.stderr, encoding='utf-8')
                    entry['test'] = {'argv': [str(exe)], 'cwd': str(out), 'exit_code': test.returncode}
                    failed |= test.returncode != 0
            else:
                failed = True
            manifest['commands'].append(entry)
            (out / 'build_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            print(mode, unit, result.returncode, flush=True)
    return int(failed)

if __name__ == '__main__':
    raise SystemExit(main())
