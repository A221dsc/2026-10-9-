"""Read-only S1 evidence report when the frozen runtime entry is blocked.

Does not launch benchmarks, sample CPU, or substitute an incomplete final report.
"""
from pathlib import Path
import argparse
import json
import statistics
import sys
import time
from diagnostic_launch import S1, verified_prefix, check_binding, git
from report_diagnostics import read_batch, resource_rows, paired_resources, mechanism_rows, latency_rows, write_csv
from dev_launch import dump, bind
import entry_gate as gate


def report_prefix(root):
    records, seals = verified_prefix(root, 'latency')
    for record, binding in zip(records, seals):
        record['evidence_path'] = gate.load(binding['path'])['acceptance']['path']
    return records, seals


def markdown_sections(sections):
    text = ''
    previous = ''
    for section in sections:
        if text:
            text += '\n' if previous.startswith('|') and section.startswith('|') else '\n\n'
        text += section
        previous = section
    return text + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    base = S1 / 'artifacts/diagnostics'
    mechanism, ma = read_batch(base / 'MECHANISM_20261011_01', 18, 'mechanism')
    resource, ra = read_batch(base / 'RESOURCE_20261011_01', 490, 'resource')
    latency, seals = report_prefix(base / 'LATENCY_20261011_01')
    rows = resource_rows(resource)
    for row, accepted in zip(rows, resource):
        for account in ('pool', 'buckets', 'tree', 'manager'):
            for field in ('peak', 'allocations', 'frees'):
                row[account + '_' + field] = accepted['raw'][account + '_' + field]
    pairs = paired_resources(rows)
    phases = mechanism_rows(mechanism)
    write_csv(root / 'S1_资源完整汇总.csv', rows)
    write_csv(root / 'S1_资源配对汇总.csv', pairs)
    write_csv(root / 'S1_机制阶段汇总.csv', phases)
    write_csv(root / 'S1_延迟已封存前缀_非完整矩阵.csv', latency_rows(latency))
    archives = ma + ra
    for seal in seals:
        d = gate.load(seal['path'])
        for name, receipt in gate.load(d['archives']['path']).items():
            check_binding(receipt)
            archives.append({'batch_mode': 'latency', 'case': d['cell'][0], 'seed': d['cell'][1],
                             'method': d['cell'][2], 'CSV': name, **receipt})
    write_csv(root / 'S1_现有原始CSV归档索引.csv', archives)
    execution_rows = []
    for directory in sorted(base.iterdir()):
        process = directory / 'process.json'
        launched = directory / 'launched.json'
        if process.exists():
            doc = gate.load(process)
            execution_rows.append({'attempt': directory.name, 'status': 'EXIT_OBSERVED',
                'exit_code': doc['exit_code'], 'actual_exit_observed': doc.get('actual_exit_observed', True),
                'command': json.dumps(doc.get('command', []), ensure_ascii=False), 'receipt': str(process)})
        elif launched.exists():
            doc = gate.load(launched)
            execution_rows.append({'attempt': directory.name, 'status': 'EXIT_UNOBSERVED',
                'exit_code': 'NA', 'actual_exit_observed': False,
                'command': json.dumps(doc.get('command', []), ensure_ascii=False), 'receipt': str(launched)})
    write_csv(root / 'S1_实际执行与失败尝试状态.csv', execution_rows)
    protocol = gate.load(gate.PROTOCOL)
    env = protocol['environment']
    incident = {'status': 'BLOCKED_FROZEN_RUNTIME_MISMATCH', 'observed_ns': time.time_ns(),
        'runtime_path': env['pair_python'], 'expected_sha256': env['pair_python_sha256'],
        'actual_sha256': gate.sha(env['pair_python']),
        'compiler_unchanged': gate.sha(env['compiler']) == env['compiler_sha256'],
        'dataset_unchanged': gate.sha(protocol['dataset']['path']) == protocol['dataset']['sha256'],
        'failed_entry_process': bind(base / 'LATENCY_20261011_02_execution/process.json'),
        'failed_entry_stderr': bind(base / 'LATENCY_20261011_02_execution/stderr.txt'),
        'new_formal_runs_in_failed_entry': 0, 'old_outer_exit': 'UNOBSERVED',
        'external_termination_cause': 'UNKNOWN', 'S2_S3_started': False,
        'resume_policy': '23 verified ordered sealed cells reused; only remaining 467 may run after original runtime restoration',
        'git_commit': git('rev-parse', 'HEAD')}
    gate.require(incident['actual_sha256'] != incident['expected_sha256'], 'partial blocked report requires actual runtime mismatch')
    dump(root / 'S1_入口阻断与恢复记录.json', incident)
    sections = ['# S1 同布局归因阶段证据报告（未完成最终裁决）',
      '本报告仅整理已完成批次。冻结 Python 启动器发生字节变化，恢复入口实际退出码为 1；未启动新增正式运行。'
      '未放宽 S0 校验、修改 R6、重跑 DEV/FINAL native，或启动 S2/S3。',
      '## 实际状态',
      '| 批次 | 已验收 / 计划 | 状态 |', '|---|---:|---|',
      '| 机制 | 18 / 18 | PASS，实际整体退出 0 |',
      '| Resource | 490 / 490 | PASS，实际整体退出 0 |',
      '| Latency | 23 / 490 | 23 次子运行 PASS；旧整体退出未观测，剩余 467 未执行 |',
      '| 恢复入口 | 1 次入口尝试 | FAIL：运行时身份不一致，正式运行 0 次 |',
      '| CPU 四场景 | 0 / 4 | NOT_RUN：等待完整 latency 闸门，非“采样工具不可用” |',
      '机制记录 4,718,592 次 API，resource 168,113,400 次 API；latency 已验收前缀 12,082,176 次 API。'
      '模式分开计量，不合并排名，不拼接成联合轨迹。正式已验收子运行合计 531；已完成的两种矩阵未发现 FAIL。',
      '## 机制有效性与限制',
      '以下各方法在三个种子上具有相同阶段树桶数量。A/B 列表由该次运行的完整转换事件重建，未借用 native 计数。',
      '| 方法 | 五阶段 TREE 数 | 每种子 promotions | scheduled | cleanup |', '|---|---|---:|---:|---:|']
    for method in ('M_LIST', 'M_OBSERVE_LIST', 'M_EVENT_16', 'M_FIXED_2048', 'R6', 'M_NO_IDLE'):
        subset = [r for r in phases if r['method'] == method and r['seed'] == 93001]
        raw = next(d['raw'] for d in mechanism if d['raw']['method'] == method and d['raw']['seed'] == '93001')
        sections.append(f"| {method} | {' → '.join(str(r['tree_buckets']) for r in subset)} | {raw['promotions']} | {raw['scheduled_demotions']} | {raw['cleanup_demotions']} |")
    sections += ['R6 与 Event16 均能回收 A 热点的树预算、接纳 B，再接纳 A；NoIdle 持有旧 A 的 32 个树桶，B 被预算阻挡。'
      'Fixed2048 出现额外端点树化。以上证明机制在登记 fixture 中可运作，并不证明 R6 优于 Event16。'
      'M01 始终非空，cleanup 为 NOT_EXERCISED；资源 F04 的 R6 十种子共记录 7 次 cleanup，相关完整事件与计数恒等式通过验收。'
      '每 epoch 升级及普通降级配额、预算、冷却、转换集合与最终树桶对账均通过既有验收。'
      '阶段 avoidable_work 未由冻结接口输出，标为 NA；不能从独立 native 批次补入。',
      '## 资源增量价值',
      '下表为同输入、同种子 R6 / 对照的最终持久请求字节配对比值中位数。小于 1 表示请求字节较少；'
      'CSV 另含 IQR、wins/10 和 whole peak。IQR 不是置信区间。',
      '| 场景 | M_LIST | Event16 | Fixed2048 | NoIdle |', '|---|---:|---:|---:|---:|']
    for case in (f'F{i:02}' for i in range(1, 8)):
        values = [next(r['median_ratio'] for r in pairs if r['case_id'] == case and r['reference'] == ref
                       and r['metric'] == 'persistent_final') for ref in ('M_LIST', 'M_EVENT_16', 'M_FIXED_2048', 'M_NO_IDLE')]
        sections.append('| ' + case + ' | ' + ' | '.join(f'{v:.4f}' for v in values) + ' |')
    sections += ['F05：R6 避免低工作量树化，比 Event16/Fixed2048 少约 39.9% 请求字节，10/10 配对更低；相对 M_LIST 没有资源收益。'
      'F03：普通回收相比 NoIdle 少约 13.7%，10/10 更低；R6 仍比 M_LIST 多约 1.17%。'
      'F06/F07：R6、Event16、Fixed2048 资源相近，R6 比 M_LIST 多约 66.5%。'
      'F04 相比 NoIdle 的比值约 0.9977，仅 5/10 更低，不能声称稳定大幅减少空间。'
      '四账户 current/peak/allocations/frees 均在汇总及原始记录中保留；Original 的不可映射账户为 NA。'
      'whole peak 含同时存活的请求分配与输出；各账户峰值不能相加充当同时峰值。'
      '请求字节不是 RSS，树回收不表示节点池归还，K=32 也不是字节预算。',
      '## 时间、转换暂停与 CPU',
      '既有 FINAL native 结果保持只读，其结论仍是：R6 对基础同布局 LIST 和简单门控没有跨场景稳定加速。'
      '本报告不重新筛选原生结果。资源批次中带诊断的时间不用于吞吐排名。'
      'Latency 仅完成 F01 前缀，不足以形成完整逐 API 或转换暂停比较；p50/p95/p99/max 及完整转换事件仍保留于各次原始记录。'
      'CPU 四场景尚未执行，没有可报告 CPU 占比，不能以墙钟差值替代。',
      '## 论文当前可以与不能主张的内容',
      '可以主张：在冻结的定长记录窗口与匹配布局实验中，预算及普通回收实现热点迁移后的树表示回收；'
      '低工作量成本门控可避免简单门控的部分无效树化。需要同时报告代价、相对 LIST 的资源劣势和没有稳定增量提速的负结果。',
      '不能主张：成本代理普遍优于事件信号、Adaptive 全面加速、已获得完整尾延迟或 CPU 归因，'
      '也不能把单机单线程、Taxi 时间键加合成操作推广为真实生产查询或并发性能。最终研究定位裁决仍待余下证据。',
      '## 恢复条件与缩减方向（未启动）',
      f"冻结启动器：`{env['pair_python']}`；要求 SHA256 `{env['pair_python_sha256']}`，"
      f"当前为 `{incident['actual_sha256']}`。缓存运行时目录中未发现该启动器的原版备份。"
      '需要恢复匹配的原运行时及其依赖，再让入口自动验证；不得直接把新身份写进冻结协议。'
      '随后只执行剩余 467 条 latency，完成四个 CPU 尝试与最终报告。',
      'S2 候选缩减：M_LIST / Event16 / R6 / TLX，三个负载、一个独立时间键来源，最长四窗口周转，'
      '短运行必须是真实共同前缀；具体矩阵在 S1 最终裁决后再定。'
      'S3 候选仅限经过实测归因的一个管理路径优化，新版本单独冻结，不沿用旧 R6 性能结论；不增加学习算法或并发实现。',
      '## 原始证据与复现',
      '所有归档保留原始 CSV SHA256、gzip SHA256 与完整解压回验记录。大文件保留于本地，未声称全部上传 Git。',
      f"- 机制：`{base / 'MECHANISM_20261011_01'}`",
      f"- Resource：`{base / 'RESOURCE_20261011_01'}`",
      f"- Latency 前缀：`{base / 'LATENCY_20261011_01'}`",
      f"- 入口失败：`{base / 'LATENCY_20261011_02_execution'}`",
      '新增恢复测试先 RED 4 项失败（工具缺失），再 GREEN；恢复及诊断回归共 18 项 PASS。'
      '阶段报告首个分析尝试因缺少 evidence_path 元数据退出 1，保留原目录；补充两项先 RED 再 GREEN 测试后改用新报告目录。'
      '这不是正式实验重跑。S1_实际执行与失败尝试状态.csv 列出实际观测到的退出码，包括预期 RED、历史工程失败和未观测退出。'
      '早先工程测试失败尝试仍保留于 artifacts/diagnostics；没有删除或选择性重跑正式性能格子。',
      '复现本阶段只读报告：使用 Python 3.13 执行 `tools/report_diagnostics_partial.py --output <新空目录>`。'
      '该分析运行时不用于正式实验，脚本不启动任何 benchmark。']
    report = root / 'S1同布局归因阶段证据报告_运行时阻断.md'
    report.write_text(markdown_sections(sections), encoding='utf8')
    dump(root / 'S1_阶段证据完成记录.json', {'status': 'PARTIAL_EVIDENCE_COMPLETE_S1_BLOCKED',
      'mechanism_PASS': 18, 'resource_PASS': 490, 'latency_PASS': 23, 'latency_NOT_RUN': 467,
      'CPU_NOT_RUN': 4, 'entry_FAIL': 1, 'formal_sealed_FAIL': 0, 'S2_S3_started': False,
      'archive_files': len(archives), 'files': [bind(p) for p in root.iterdir() if p.is_file()]})
    print(json.dumps({'status': 'PARTIAL_EVIDENCE_COMPLETE_S1_BLOCKED', 'report': str(report)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
