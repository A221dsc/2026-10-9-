"""Independent frozen S1 diagnostics. Never launches native timing or tunes R6.

Exclusive destinations, actual child exits, streaming CSV acceptance, and
lossless archives keep every API record without filling the system disk.
"""
from pathlib import Path
import argparse
import collections
import csv
import ctypes
import gzip
import hashlib
import json
import math
import platform
import shutil
import subprocess
import sys
import time
import traceback

import entry_gate as gate
from dev_launch import S1, WORKSPACE, Quiet, actual_process, bind, config_bytes, dump, log
from pair_adapter import child_command

METHODS = ('Original', 'M_LIST', 'M_OBSERVE_LIST', 'M_EVENT_16',
           'M_FIXED_2048', 'R6', 'M_NO_IDLE')
NATIVE = S1 / 'artifacts/final/FINAL_20261010_01_resume_01'
ORIGINAL = S1 / 'artifacts/final/FINAL_20261010_01'
DEV = S1 / 'artifacts/dev/DEV_20261010_01'
REVIEW = S1 / 'artifacts/driver/green_review_fixes_root_01/manifest.json'
FINAL_TAG = 's1-final-native-v1'
DEV_TAG = 's1-dev-v1'


def cells(mode):
    if mode == 'mechanism':
        return [('M01', seed, method) for seed in range(93001, 93004)
                for method in METHODS if method != 'Original']
    gate.require(mode in ('resource', 'latency'), 'native timing forbidden in this entry')
    return [(f'F{i:02}', seed, method) for i in range(1, 8)
            for seed in range(91001, 91011) for method in METHODS]


def check_binding(binding):
    gate.require(gate.sha(binding['path']) == binding['sha256'], 'external file binding differs')


def check_mode(doc, mode):
    gate.require(mode in ('resource', 'latency') and doc['measurement_mode'] == mode
                 and doc['engineering_only'] is False, 'formal diagnostic mode/engineering mismatch')


def distribution(values):
    a = sorted(values)
    if not a:
        return {'count': 0, 'p50': None, 'p95': None, 'p99': None, 'max': None}
    def q(p):
        at = (len(a) - 1) * p
        lo, hi = math.floor(at), math.ceil(at)
        return a[lo] + (a[hi] - a[lo]) * (at - lo)
    return {'count': len(a), 'p50': q(.5), 'p95': q(.95), 'p99': q(.99), 'max': a[-1]}


def check_event_counts(events, row):
    counts = collections.Counter(e['type'] for e in events)
    quota = collections.Counter((e['type'], int(e['epoch'])) for e in events
                                if e['type'] in ('promotion', 'scheduled'))
    gate.require(all(v <= 1 for v in quota.values()), 'scheduled epoch quota violated')
    gate.require(set(counts) <= {'promotion', 'scheduled', 'cleanup'}, 'unknown event type')
    for e in events:
        gate.require(0 <= int(e['slot']) < 4096 and
                     ((e['type'] == 'cleanup') == (int(e['n']) == 0)), 'event slot/empty cleanup')
    for field, kind in [('promotions', 'promotion'), ('scheduled_demotions', 'scheduled'),
                        ('cleanup_demotions', 'cleanup')]:
        gate.require(int(row[field]) == counts[kind], 'conversion event missing/duplicate')
    gate.require(int(row['total_demotions']) == counts['scheduled'] + counts['cleanup'],
                 'total demotions identity')


def read_archive(path):
    with gzip.open(path, 'rb') as f:
        return f.read()


def archive_csv(path):
    """Delete only the verified duplicate after byte-identical gzip round trip."""
    path = Path(path)
    dest = path.with_suffix(path.suffix + '.gz')
    before = bind(path)
    size = path.stat().st_size
    with dest.open('xb') as out:
        with gzip.GzipFile(filename='', fileobj=out, mode='wb', compresslevel=1, mtime=0) as z:
            with path.open('rb') as src:
                shutil.copyfileobj(src, z, 1 << 20)
    h = hashlib.sha256()
    total = 0
    with gzip.open(dest, 'rb') as src:
        for chunk in iter(lambda: src.read(1 << 20), b''):
            h.update(chunk)
            total += len(chunk)
    gate.require(total == size and h.hexdigest() == before['sha256'], 'lossless archive mismatch')
    receipt = {**bind(dest), 'raw_sha256': before['sha256'], 'raw_bytes': size,
               'archive_bytes': dest.stat().st_size, 'roundtrip_verified': True}
    # This exact file was verified; no recursive deletion or cross-shell operation.
    path.unlink()
    return receipt


def git(*args):
    return subprocess.check_output(['git', *args], cwd=WORKSPACE).decode('utf8').strip()


def tag_bytes(tag, path):
    return subprocess.check_output(['git', 'show', f'{tag}:{Path(path).relative_to(WORKSPACE).as_posix()}'],
                                   cwd=WORKSPACE)


def frozen_entry(root):
    gate.require(not git('status', '--porcelain'), 'commit independent tools before actual diagnostics')
    tags = {FINAL_TAG: git('rev-parse', FINAL_TAG + '^{commit}'),
            DEV_TAG: git('rev-parse', DEV_TAG + '^{commit}')}
    gate.require(tags[FINAL_TAG] == '5405d8203e91733f0a884720c214fe658201b57f'
                 and tags[DEV_TAG] == 'c32e9903846540e16003c39c138bb97c00a6bf01', 'frozen tag changed')
    reviewed = gate.verify_driver(REVIEW)
    binaries = {}
    for mode in ('native', 'resource', 'latency'):
        path = S1 / f'release/binaries/s1_{mode}.exe'
        digest = reviewed['binary_sha'][path.name]
        gate.require(gate.sha(path) == digest and hashlib.sha256(tag_bytes(FINAL_TAG, path)).hexdigest() == digest,
                     'reviewed/tagged binary differs')
        binaries[mode] = bind(path)
    completion = gate.load(NATIVE / 'completion.json')
    final_gate = gate.load(NATIVE / 'FINAL_COMPLETE_GATE.json')
    gate.require(completion['status'] == 'FINAL_NATIVE_COMPLETE' and completion['actual_timing_children'] == 3160
                 and final_gate['FINAL_READY'] and not final_gate['missing_final_assets'], 'native completion gate')
    outer = gate.load(Path(str(NATIVE) + '_execution') / 'process.json')
    gate.require(outer['actual_exit_observed'] and outer['exit_code'] == 0, 'native actual completion exit')
    assets = gate.load(NATIVE / 'complete_assets.json')
    trust = gate.load(NATIVE / 'complete_asset_trust.json')
    for name in ('formal_trace_inventory', 'dev_selection', 'protocol_and_sources', 'frozen_binaries'):
        gate.require(gate.sha(assets[name]['path']) == trust[name]['sha256'], 'native archived asset changed')
    selection = gate.load(DEV / 'dev_selection.json')
    gate.require(selection['selected_theta'] == 16 and selection['selected_h'] == 2048
                 and selection['children'] == 960 and selection['inputs'] == 30, 'frozen DEV choice')
    gate.require(gate.sha(DEV / 'dev_selection.json') == trust['dev_selection']['selection_sha256'],
                 'DEV selection bytes changed')
    for name in ('FINAL_同布局增量价值报告.md', 'FINAL_raw_native_all.csv', 'FINAL_group_summary.csv',
                 'FINAL_paired_all.csv', 'FINAL_mechanism_counters_per_run.csv', 'FINAL_结果记录.json'):
        path = S1 / name
        gate.require(path.read_bytes() == tag_bytes(FINAL_TAG, path), 'published native result changed')
    protocol = gate.load(gate.PROTOCOL)
    env = protocol['environment']
    for path, digest in [(sys.executable, env['pair_python_sha256']),
                         (env['compiler'], env['compiler_sha256']),
                         (protocol['dataset']['path'], protocol['dataset']['sha256'])]:
        gate.require(gate.sha(path) == digest, 'runtime/compiler/dataset differs')
    protected = [gate.PROTOCOL, REVIEW, NATIVE / 'completion.json', NATIVE / 'FINAL_COMPLETE_GATE.json',
                 DEV / 'dev_selection.json', *[Path(v['path']) for v in binaries.values()]]
    for name in reviewed.get('source_sha', {}):
        protected.append(S1 / name)
    manifest = gate.load(REVIEW)
    protected += [S1 / k for k in manifest['source_sha'] if k.replace('\\', '/').startswith('src/')]
    protected += [S1.parents[1] / k for k in manifest['frozen_dependencies']]
    doc = {'status': 'PASS', 'git_commit': git('rev-parse', 'HEAD'), 'tags': tags,
           'reviewed_source_bundle_sha': reviewed['source_bundle_sha'], 'binaries': binaries,
           'native_gate': bind(NATIVE / 'FINAL_COMPLETE_GATE.json'), 'native_outer': bind(Path(str(NATIVE) + '_execution') / 'process.json'),
           'dev_selection': bind(DEV / 'dev_selection.json'), 'selected_theta': 16, 'selected_h': 2048,
           'protected_files': [bind(p) for p in protected], 'native_read_only': True,
           'protocol': bind(gate.PROTOCOL), 'environment': env, 'actual_platform': platform.platform()}
    dump(root / 'FROZEN_ENTRY.json', doc)
    return doc, protocol, assets, trust


def open_csv(path):
    f = Path(path).open(encoding='utf8', newline='')
    reader = csv.DictReader(f)
    gate.require(reader.fieldnames and len(reader.fieldnames) == len(set(reader.fieldnames)), 'CSV fields')
    return f, reader


def validate_run(directory, binding, mode, method, config_sha, binary_sha, engineering=False):
    started = time.time_ns()
    directory = Path(directory)
    process = gate.load(directory / 'process.json')
    gate.require(process['exit_code'] == 0 and not (directory / 'failure.json').exists(), 'actual child failed')
    receipt = gate.load(directory / 'run_receipt.json')
    if not engineering:
        check_mode(receipt, mode)
    gate.require(receipt['measurement_mode'] == mode and receipt['config_sha'] == config_sha
                 and receipt['binary_sha'] == binary_sha, 'executed diagnostic identity')
    for key in ('cache', 'expected'):
        digest = binding[key]['sha256']
        gate.require(receipt[key + '_sha_before'] == receipt[key + '_sha_after'] == digest, 'input receipt binding')
    gate.require(receipt['metadata_sha'] == binding['meta']['sha256'], 'metadata binding')
    meta = gate.load(binding['meta']['path'])
    raw = gate.csv_rows(directory / 'raw_native.csv')
    gate.require(len(raw) == 1, 'one diagnostic child required')
    row = raw[0]
    for key, value in [('method', method), ('measurement_mode', mode), ('case_id', meta['case_id']),
                       ('seed', meta['seed']), ('N', meta['N']), ('U', meta['U']),
                       ('API_calls', meta['API_calls']), ('queries', meta['queries']),
                       ('cache_sha', binding['cache']['sha256']), ('binary_sha', binary_sha),
                       ('source_bundle_sha', receipt['source_bundle_sha']), ('config_sha', config_sha),
                       ('protocol_sha', meta['protocol_sha']), ('dataset_sha', meta['dataset_sha'])]:
        gate.require(row[key] == str(value), 'raw identity mismatch: ' + key)
    gate.require(row['status'] == ('ENGINEERING_CORRECTNESS_ONLY' if engineering else 'valid'), 'status')
    for boundary in ('start', 'end'):
        gate.require([row['placement_' + boundary + '_' + k] for k in ('mask', 'cpu', 'group')] == ['8', '3', '0'], 'actual P-core placement')
    gate.require(int(row['total_ns']) == int(row['build_ns']) + int(row['online_ns'])
                 and int(row['lifecycle_ns']) == int(row['total_ns']) + int(row['destroy_ns']), 'time accounting')
    if method != 'Original':
        gate.require(0 <= int(row['final_tree_buckets']) <= int(row['peak_tree_buckets']) <= 32
                     and int(row['cand_max']) <= 4096 and int(row['conversion_failures']) == 0, 'manager bounds/failure')
    for account in ('pool', 'buckets', 'tree', 'manager'):
        for metric in ('current', 'peak', 'allocations', 'frees'):
            v = row[account + '_' + metric]
            gate.require(v == 'NA' if mode == 'latency' or method == 'Original' else v != 'NA' and int(v) >= 0,
                         'four account availability')
    phases = gate.csv_rows(directory / 'phase.csv')
    gate.require([int(p['end_unit']) - int(p['begin_unit']) for p in phases] == meta['phase_lengths']
                 and sum(int(p['online_ns']) for p in phases) == int(row['online_ns']), 'phase coverage/time')
    events = gate.csv_rows(directory / 'conversion_events.csv')
    if method == 'Original':
        gate.require(not events, 'Original has no controller event hook')
    else:
        check_event_counts(events, row)
    event_ordinals = collections.defaultdict(list)
    representation = set()
    last_conversion = {}
    for e in events:
        slot, epoch = int(e['slot']), int(e['epoch'])
        if e['type'] != 'cleanup' and slot in last_conversion:
            gate.require(epoch >= last_conversion[slot] + 8, 'conversion cooldown')
        if e['type'] == 'promotion':
            gate.require(slot not in representation and int(e['n']) >= 128, 'promotion representation')
            representation.add(slot)
        else:
            gate.require(slot in representation, 'demotion representation')
            representation.remove(slot)
        gate.require(len(representation) <= 32, 'TREE budget trace')
        last_conversion[slot] = epoch
        event_ordinals[int(e['API_ordinal'])].append(e)
    if method != 'Original':
        gate.require(len(representation) == int(row['final_tree_buckets']), 'final TREE event reconciliation')
    lat = directory / 'latency.csv'
    series = collections.defaultdict(list)
    seen = 0
    observed_events = 0
    # Frozen writer emits quoted scalar columns. csv.reader avoids huge dicts.
    with lat.open(encoding='utf8', newline='') as f:
        reader = csv.reader(f)
        fields = next(reader)
        gate.require(len(fields) == len(set(fields)), 'latency header')
        idx = {k: fields.index(k) for k in ('API_type', 'API_ordinal', 'epoch', 'ns', 'conversion', 'phase', 'completed_units_before_active_api')}
        prefix = [row[k] for k in fields[:fields.index('API_type')]]
        unit = 0
        for phase, length in enumerate(meta['phase_lengths']):
            for local in range(length):
                kinds = ['erase', 'insert']
                q = meta['phase_q'][phase]
                if q and (local + 1) % q == 0:
                    kinds.append('range')
                for kind in kinds:
                    values = next(reader, None)
                    gate.require(values is not None and len(values) == len(fields) and values[:len(prefix)] == prefix, 'latency full identity/shape')
                    seen += 1
                    ns = int(values[idx['ns']])
                    expected_epoch = 0 if method in ('Original', 'M_LIST') else (2 * unit + (1 if kind == 'erase' else 2)) // 512
                    gate.require(values[idx['API_type']] == kind and int(values[idx['API_ordinal']]) == seen
                                 and int(values[idx['completed_units_before_active_api']]) == unit
                                 and int(values[idx['phase']]) == phase and int(values[idx['epoch']]) == expected_epoch
                                 and ns >= 0, 'per-API schedule/ordinal/clock')
                    evs = event_ordinals.get(seen, [])
                    gate.require(values[idx['conversion']] == ('true' if evs else 'false'), 'API conversion tag')
                    for e in evs:
                        gate.require(int(e['api_latency_ns']) == ns and ns >= int(e['conversion_body_ns']) >= 0,
                                     'conversion/API latency reconciliation')
                    observed_events += len(evs)
                    series[kind].append(ns)
                    if evs:
                        series['conversion_API'].append(ns)
                unit += 1
        gate.require(next(reader, None) is None and seen == meta['API_calls'] and observed_events == len(events), 'complete API/event inventory')
    summary = gate.load(directory / 'latency_summary.json')
    gate.require(summary['samples'] == seen and summary['conversion_events'] == len(events), 'latency summary count')
    all_ns = series['erase'] + series['insert'] + series['range']
    measured = distribution(all_ns)
    for key in ('p50', 'p95', 'p99', 'max'):
        # Frozen C++ JSON uses default six significant digits, retain exact CSV.
        gate.require(math.isclose(measured[key], summary[key], rel_tol=6e-6, abs_tol=.000001), 'summary quantile reconciliation')
    resources = gate.csv_rows(directory / 'resource.csv') if mode == 'resource' else []
    if mode == 'resource':
        gate.require(summary['owner_current_after_destroy'] == summary['owner_live_after_destroy'] == 0, 'owner leaks')
        periodic = []
        conversions = []
        boundaries = []
        api_keys = set()
        for s in resources:
            bits = s['snapshot_reason'].split('|')
            current, peak = int(s['whole_current']), int(s['whole_peak'])
            gate.require(peak >= current >= 0 and current == int(s['persistent_requested_bytes']), 'whole simultaneous accounting')
            if method != 'Original':
                accounts = sum(int(s[k + '_current']) for k in ('pool', 'buckets', 'tree', 'manager'))
                gate.require(current >= accounts and int(s['tree_buckets']) <= 32, 'account bounds/TREE budget')
            else:
                gate.require(all(s[k + '_current'] == 'NA' for k in ('pool', 'buckets', 'tree', 'manager')), 'Original unmapped accounts')
            if 'conversion' in bits:
                gate.require(s['output_released'] == 'false' and s['unit_semantics'] == 'completed_before_active_api', 'event snapshot timing')
                conversions.append(int(s['API_ordinal']))
            else:
                gate.require(s['output_released'] == 'true' and s['API_ordinal'] not in api_keys, 'resource dedup/output release')
                api_keys.add(s['API_ordinal'])
                if 'periodic512' in bits:
                    periodic.append(int(s['completed_unit']))
                if 'phase' in bits:
                    boundaries.append(int(s['completed_unit']))
        gate.require(periodic == list(range(512, meta['U'] + 1, 512))
                     and boundaries == list(__import__('itertools').accumulate(meta['phase_lengths']))
                     and conversions == [int(e['API_ordinal']) for e in events]
                     and 'final' in resources[-1]['snapshot_reason'], 'resource complete sample/event inventory')
        gate.require(int(resources[-1]['whole_peak']) <= summary['whole_peak_requested_bytes'], 'owner peak')
    else:
        gate.require(not (directory / 'resource.csv').exists() and summary['whole_peak_requested_bytes'] == 'NA', 'latency resource separation')
    result = {'status': 'PASS', 'measurement_mode': mode, 'engineering_only': engineering,
              'raw': row, 'summary': summary, 'phases': phases, 'conversion_events': events,
              'resources': resources, 'API_samples': seen,
              'API_distributions': {k: distribution(v) for k, v in series.items()},
              'all_API_distribution': measured,
              'conversion_body_distribution': distribution([int(e['conversion_body_ns']) for e in events]),
              'validation_started_ns': started, 'validation_ended_ns': time.time_ns()}
    dump(directory / 'ACCEPTANCE.json', result)
    archives = {}
    for path in sorted(directory.glob('*.csv')):
        archives[path.name] = archive_csv(path)
    dump(directory / 'ARCHIVES.json', archives)
    return result


class Run:
    def __init__(self, root, mode):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=False)
        self.mode = mode
        self.quiet = Quiet()
        self.results = []
        self.phase = 'frozen entry'
        self.freeze, self.protocol, self.assets, self.trust = frozen_entry(self.root)
        self.env = self.protocol['environment']
        self.pin = self.env['pin_tool']
        self.configs = {}
        self.inputs = {}

    def preflight(self, modes):
        topo, _ = actual_process([self.env['topology_tool'], '--iters', '1000'], self.root / 'preflight', 'topology')
        topology = list(csv.DictReader(topo.split('#')[0].strip().splitlines()))
        gate.require(any(r['logical'] == '3' and r['kind'] == 'P' and r['mask_hex'] == '0x8' for r in topology), 'fixed P core absent')
        for mode in modes:
            binary = self.freeze['binaries'][mode]
            for method in METHODS:
                stdout, _ = actual_process([self.pin, '0x8', binary['path'], 'describe', '--method', method],
                                           self.root / 'preflight', mode + '_' + method)
                doc = json.loads(stdout)
                gate.require(doc['measurement_mode'] == mode and doc['binary_sha'] == binary['sha256']
                             and doc['source_bundle_sha'] == self.freeze['reviewed_source_bundle_sha']
                             and doc['process_mask'] == 8 and doc['logical_cpu'] == 3, 'describe mode/placement/binary')
                self.configs[mode, method] = doc['config_sha']
                path = self.root / 'configs' / f'{mode}_{method}.json'
                path.parent.mkdir(exist_ok=True)
                with path.open('xb') as f:
                    f.write(config_bytes(stdout))
        dump(self.root / 'ENVIRONMENT.json', {'platform': platform.platform(), 'topology': topology,
             'logical_cpu': 3, 'affinity_mask': 8, 'group': 0,
             'quiet': self.quiet.check(self.root / 'preflight/gate_quiet.json', reset=True),
             'disk': shutil.disk_usage(self.root)._asdict()})

    def bind_final(self):
        inventory = gate.load(self.assets['formal_trace_inventory']['path'])
        self.phase = 'readonly input binding'
        for fs in inventory['files']:
            check_binding(fs)
        for entry in inventory['entries']:
            files = {k: bind(entry[field]) for k, field in
                     [('cache', 'cache_path'), ('expected', 'expected_path'), ('meta', 'metadata_path')]}
            self.inputs[entry['case_id'], int(entry['seed'])] = files
        gate.require(len(self.inputs) == 70, 'complete independent input inventory')
        dump(self.root / 'INPUT_BINDINGS.json', [{'case': c, 'seed': s, **f} for (c, s), f in self.inputs.items()])

    def mechanism_inputs(self):
        self.phase = 'registered mechanism preparation'
        binary = self.freeze['binaries']['resource']['path']
        for seed in range(93001, 93004):
            path = self.root / 'inputs' / f'M01_{seed}'
            actual_process([binary, 'prepare', '--case', 'M01', '--seed', str(seed), '--profile', 'mechanism',
                            '--protocol-sha', self.freeze['protocol']['sha256'], '--output', str(path)],
                           self.root / 'preparation', str(seed))
            files = {k: bind(path / name) for k, name in [('cache', 'cache.bin'), ('expected', 'cache.expected.bin'), ('meta', 'cache.meta.json')]}
            cache = gate.cache_identity(files['cache']['path'], files['expected']['path'])
            meta = gate.load(files['meta']['path'])
            gate.require(meta['profile'] == 'mechanism' and not meta['engineering_only'] and meta['seed'] == seed
                         and cache['N'] == cache['U'] == 131072 and cache['queries'] == 0, 'registered M01 geometry')
            self.inputs['M01', seed] = files
        dump(self.root / 'INPUT_BINDINGS.json', [{'case': c, 'seed': s, **f} for (c, s), f in self.inputs.items()])

    def child(self, case, seed, method, mode, label=None):
        self.phase = f'{mode}:{case}:{seed}:{method}'
        path = self.root / 'runs' / (label or f'{case}_{seed}_{method}')
        gate.require(not path.exists(), 'immutable child already exists')
        files = self.inputs[case, seed]
        for f in files.values():
            check_binding(f)
        binary = self.freeze['binaries'][mode]
        check_binding(binary)
        self.quiet.check(path / 'quiet.json')
        command = child_command(self.pin, binary['path'], files['cache']['path'], files['cache']['sha256'], method,
                                path / 'output', self.root.name, '1', self.phase, 1, 'A')
        log('actual start ' + self.phase)
        started = time.time_ns()
        actual_process(command, path / 'output')
        elapsed = time.time_ns() - started
        result = validate_run(path / 'output', files, mode, method,
                              self.configs[mode, method], binary['sha256'])
        result['outer_elapsed_ns'] = elapsed
        result['path'] = str(path)
        self.results.append(result)
        checkpoint = bind(path / 'output/ACCEPTANCE.json')
        seal = {'status': 'PASS', 'cell': [case, seed, method], 'mode': mode,
                'acceptance': checkpoint, 'archives': bind(path / 'output/ARCHIVES.json'),
                'process': bind(path / 'output/process.json'), 'quiet': bind(path / 'quiet.json')}
        dump(path / 'SEALED.json', seal)
        with (self.root / 'progress.jsonl').open('a', encoding='utf8') as f:
            f.write(json.dumps(bind(path / 'SEALED.json'), ensure_ascii=False) + '\n')
        log(f'accepted {len(self.results)} {self.phase}; APIs={result["API_samples"]}; conversions={len(result["conversion_events"])}')
        return result

    def finish(self, planned):
        gate.require(len(self.results) == planned, 'missing/duplicate matrix cell')
        for f in self.freeze['protected_files']:
            check_binding(f)
        for files in self.inputs.values():
            for f in files.values():
                check_binding(f)
        seals = [bind(p) for p in sorted((self.root / 'runs').glob('*/SEALED.json'))]
        gate.require(len(seals) == planned, 'sealed matrix count')
        dump(self.root / 'COMPLETE.json', {'status': 'PASS', 'mode': self.mode, 'planned': planned,
             'actual_completed': len(self.results), 'FAIL': 0, 'all_seals': seals,
             'API_samples': sum(r['API_samples'] for r in self.results),
             'conversions': sum(len(r['conversion_events']) for r in self.results),
             'native_unchanged': True, 'ended_ns': time.time_ns(), 'git_commit': git('rev-parse', 'HEAD')})

    def capacity(self):
        self.preflight(('resource', 'latency'))
        self.bind_final()
        self.child('F03', 91001, 'R6', 'resource', 'capacity_resource_F03_R6')
        self.child('F03', 91001, 'R6', 'latency', 'capacity_latency_F03_R6')
        samples = []
        for r in self.results:
            archive = gate.load(Path(r['path']) / 'output/ARCHIVES.json')
            raw = sum(f['raw_bytes'] for f in archive.values())
            zipped = sum(f['archive_bytes'] for f in archive.values())
            samples.append({'mode': r['measurement_mode'], 'raw_bytes': raw, 'gzip_bytes': zipped,
                            'API_samples': r['API_samples'], 'elapsed_ns': r['outer_elapsed_ns'],
                            'validation_ns': r['validation_ended_ns'] - r['validation_started_ns']})
        protocol_apis = sum(c['api_calls'] for c in self.protocol['final_cases']) * 10 * 7
        factor = max(s['gzip_bytes'] / s['API_samples'] for s in samples)
        required = math.ceil(2 * protocol_apis * factor * 2 + max(s['raw_bytes'] for s in samples) * 2 + (5 << 30))
        available = shutil.disk_usage(self.root).free
        doc = {'status': 'PASS' if available >= required else 'CAPACITY_BLOCKED', 'engineering_only': True,
               'formal_runs': 0, 'capacity_runs': 2, 'samples': samples, 'APIs_per_formal_mode': protocol_apis,
               'estimated_uncompressed_both_bytes': math.ceil(2 * protocol_apis * max(s['raw_bytes'] / s['API_samples'] for s in samples)),
               'estimated_archive_both_bytes': math.ceil(2 * protocol_apis * factor),
               'required_free_with_2x_archive_margin_staging_and_5GiB_reserve': required, 'actual_free': available,
               'recovery': 'exclusive outputs; failed attempts untouched; only externally sealed completed prefix can be reused; no automatic performance retry',
               'compression': 'gzip level1; original SHA256 plus compressed SHA256 and verified full decompression before removing duplicate',
               'algorithm_parameters_workloads_unchanged': True, 'ended_ns': time.time_ns()}
        dump(self.root / 'CAPACITY.json', doc)
        gate.require(doc['status'] == 'PASS', 'actual engineering capacity insufficient')
        self.finish(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', required=True, choices=('capacity', 'mechanism', 'resource', 'latency'))
    ap.add_argument('--output', required=True)
    ap.add_argument('--capacity', type=Path)
    args = ap.parse_args()
    run = None
    # Named OS mutex prevents simultaneous diagnostic batches, including detached launchers.
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateMutexW(None, False, 'Local\\PoolHBI_S1_Diagnostics')
    gate.require(handle and kernel.GetLastError() != 183, 'another diagnostic launcher owns serial slot')
    try:
        run = Run(args.output, args.mode)
        if args.mode == 'capacity':
            run.capacity()
        else:
            gate.require(args.capacity is not None, 'actual capacity pilot required before formal execution')
            capacity = gate.load(args.capacity)
            gate.require(capacity['status'] == 'PASS' and capacity['engineering_only'], 'capacity gate blocked')
            dump(run.root / 'CAPACITY_BINDING.json', bind(args.capacity))
            mode = 'resource' if args.mode == 'mechanism' else args.mode
            run.preflight((mode,))
            if args.mode == 'mechanism':
                run.mechanism_inputs()
            else:
                run.bind_final()
            matrix = cells(args.mode)
            dump(run.root / 'START.json', {'status': 'READY', 'mode': args.mode, 'cells': matrix,
                 'planned': len(matrix), 'frozen_entry': bind(run.root / 'FROZEN_ENTRY.json'),
                 'input_bindings': bind(run.root / 'INPUT_BINDINGS.json'), 'native_reruns': 0,
                 'AA_native_not_repeated': True, 'config_sha': {m: run.configs[mode, m] for m in METHODS}})
            for cell in matrix:
                run.child(*cell, mode)
            run.finish(len(matrix))
    except Exception as e:
        if run is not None:
            dump(run.root / 'BATCH_FAILURE.json', {'status': 'STOPPED', 'mode': args.mode,
                 'phase': run.phase, 'accepted': len(run.results), 'error': repr(e),
                 'traceback': traceback.format_exc(), 'time_ns': time.time_ns(), 'failed_attempt_retained': True})
        raise
    finally:
        kernel.CloseHandle(handle)


if __name__ == '__main__':
    main()
