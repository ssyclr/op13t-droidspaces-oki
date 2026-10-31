#!/usr/bin/env python3
"""Write the pre-flash report for one workflow run and decide pass/fail.

Usage: report.py <artifacts dir> <baseline dir> <options file> <out dir>

<artifacts dir> holds the stock/ and, when it was built, droidspaces/ artifact
of the workflow. <baseline dir> holds what was taken from the phone. Exit status
is non-zero if a build must not be flashed. Differences only a person can judge
are listed under "needs review" and hold back flashing until someone has read
them.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kabi  # noqa: E402

FORBIDDEN = ('CFS_BANDWIDTH', 'CGROUP_PIDS')
MUST_STAY_ON = ('MODULE_SIG_PROTECT', 'MODVERSIONS')
TRUSTED_KEYS = '"certs/stock_module_signing.pem"'
# Set on purpose in both builds: the release string (MODULE_SCMVERSION depends
# on LOCALVERSION_AUTO; struct module keeps the field either way) and the stock
# certificate.
EXPECTED_CONFIG_DIFF = {'LOCALVERSION', 'LOCALVERSION_AUTO', 'MODULE_SCMVERSION', 'SYSTEM_TRUSTED_KEYS'}
ROOT_STRINGS = re.compile(rb'kernelsu|sukisu|susfs', re.I)


def read(path, default=''):
    try:
        with open(path, encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        return default


class Report:
    def __init__(self, variants):
        self.lines = []
        self.failures = {v: [] for v in variants}
        self.reviews = {v: [] for v in variants}

    def p(self, text=''):
        self.lines.append(text)

    def h(self, text):
        self.lines += ['', f'## {text}', '']

    def details(self, summary, items, limit=3000):
        items = list(items)
        if not items:
            return
        self.p(f'<details><summary>{summary}（{len(items)}）</summary>')
        self.p()
        self.p('```')
        self.lines += items[:limit]
        if len(items) > limit:
            self.p(f'... 另有 {len(items) - limit} 项未列出')
        self.p('```')
        self.p('</details>')
        self.p()


def config_section(r, art, base, options_file, skipped, variants):
    r.h('1. 内核配置（从编出的 Image 用 extract-ikconfig 提取）')
    stock = kabi.load_config(f'{base}/stock.config')
    built = kabi.load_config(f'{art}/stock/config')
    diff = sorted(o for o in stock.keys() | built.keys() if stock.get(o) != built.get(o))
    unexpected = [o for o in diff if o not in EXPECTED_CONFIG_DIFF]
    r.p(f'**stock 构建 → 手机 `stock.config`**：差异 {len(diff)} 项，'
        f'其中版本串和证书项 {len(diff) - len(unexpected)} 项，其余 {len(unexpected)} 项。')
    r.p()
    r.details('差异（除版本串和证书外，全部需要人工判断）',
              (f"{o}: 手机 {stock.get(o, '-')} -> 构建 {built.get(o, '-')}"
               f"{'  (预期)' if o in EXPECTED_CONFIG_DIFF else ''}" for o in diff))
    if unexpected:
        r.reviews['stock'].append(f'stock 构建的配置与手机有 {len(unexpected)} 项差异：{" ".join(unexpected[:12])}')
    for opt in MUST_STAY_ON:
        if built.get(opt) != 'y':
            r.failures['stock'].append(f'CONFIG_{opt} 不是 y')
    if 'droidspaces' not in variants:
        return

    ds = kabi.load_config(f'{art}/droidspaces/config')
    missing = set(read(f'{art}/droidspaces/kconfig_missing.txt').split())
    r.p('**droidspaces 构建**')
    r.p()
    r.p('| 选项 | 分类 | 原厂 | 本次 | 结果 |')
    r.p('|---|---|---|---|---|')
    listed = set()
    for opt, category in kabi.load_option_list(options_file):
        listed.add(opt)
        before, after = stock.get(opt, '-'), ds.get(opt, '-')
        if opt in skipped:
            verdict = '⏭ 本次跳过'
        elif after == 'y':
            verdict = '✅ 已开启'
        elif opt in missing:
            verdict = '➖ 该源码树的 Kconfig 里没有这个符号'
        else:
            verdict = '❌ 未生效（依赖不满足被丢弃？）'
            r.failures['droidspaces'].append(f'CONFIG_{opt} 没有生效')
        r.p(f'| `{opt}` | {category} | {before} | {after} | {verdict} |')
    for opt in FORBIDDEN:
        before, after = stock.get(opt, 'n'), ds.get(opt, 'n')
        ok = before == after
        r.p(f"| `{opt}` | 禁止改动 | {before} | {after} | {'✅ 与原厂一致' if ok else '❌ 被改动'} |")
        if not ok:
            r.failures['droidspaces'].append(f'CONFIG_{opt} 与原厂不一致')
    for opt in MUST_STAY_ON:
        ok = ds.get(opt) == 'y'
        r.p(f"| `{opt}` | 必须保持 | {stock.get(opt, 'n')} | {ds.get(opt, 'n')} | {'✅' if ok else '❌'} |")
        if not ok:
            r.failures['droidspaces'].append(f'CONFIG_{opt} 不是 y')
    keys = ds.get('SYSTEM_TRUSTED_KEYS', '-')
    r.p(f"| `SYSTEM_TRUSTED_KEYS` | 信任原厂证书 | {stock.get('SYSTEM_TRUSTED_KEYS', '-')} | {keys} | "
        f"{'✅' if keys == TRUSTED_KEYS else '❌'} |")
    if keys != TRUSTED_KEYS:
        r.failures['droidspaces'].append('CONFIG_SYSTEM_TRUSTED_KEYS 未按预期设置')
    ksu = sorted(o for o in ds if o.startswith('KSU'))
    if ksu:
        r.failures['droidspaces'].append(f"出现了 root 相关配置：{' '.join(ksu)}")
    r.p()
    derived = sorted(o for o in built.keys() | ds.keys() if built.get(o) != ds.get(o))
    r.details('stock 构建 → droidspaces 构建 全部配置差异（含 Kconfig 自动派生的选项）',
              (f"{o}: {built.get(o, '-')} -> {ds.get(o, '-')}{'' if o in listed else '  (派生)'}" for o in derived))


def symbols_section(r, art, variants):
    r.h('2. 导出符号')
    if 'droidspaces' not in variants:
        r.p('本次没有 droidspaces 构建，跳过。')
        return None
    stock = kabi.load_symvers(f'{art}/stock/vmlinux.symvers')
    ds = kabi.load_symvers(f'{art}/droidspaces/vmlinux.symvers')
    c = kabi.compare_symvers(stock, ds)
    r.p('| 对比 | 基准符号数 | 新符号数 | CRC 变化 | 删除 | 导出类型/命名空间变化 | 新增 |')
    r.p('|---|---|---|---|---|---|---|')
    r.p(f"| stock 构建 → droidspaces 构建 | {c['base_count']} | {c['new_count']} | {len(c['crc_changed'])} | "
        f"{len(c['removed'])} | {len(c['export_changed'])} | {len(c['added'])} |")
    r.p()
    if c['crc_changed'] or c['removed'] or c['export_changed']:
        r.failures['droidspaces'].append('已有符号的 CRC / 导出属性有变化，或有符号被删除')
    r.details('CRC 变化', (f'{s}: {stock[s][0]} -> {ds[s][0]}' for s in c['crc_changed']))
    r.details('被删除的符号', c['removed'])
    r.details('导出类型/命名空间变化', (f'{s}: {stock[s][1:]} -> {ds[s][1:]}' for s in c['export_changed']))
    r.details('新增符号（预期来自 USER_NS）', (f'{s}  {ds[s][2]}  {ds[s][3]}'.rstrip() for s in c['added']))
    return c


def modules_section(r, art, base, variants):
    r.h('3. 手机模块用到的符号（device_modversions.tsv）')
    modules = kabi.load_modversions(f'{base}/device_modversions.tsv')
    vmlinux = {s: m for s, m in modules.items() if m[1] == '-'}
    r.p(f'手机模块共引用 {len(modules)} 个符号，其中 {len(modules) - len(vmlinux)} 个由其他模块提供，'
        f'{len(vmlinux)} 个由 vmlinux 提供。')
    r.p()
    r.p('| 构建 | 检查符号数 | CRC 一致 | CRC 不一致 | 构建里不存在 |')
    r.p('|---|---|---|---|---|')
    result = {}
    for variant in variants:
        symvers = kabi.load_symvers(f'{art}/{variant}/vmlinux.symvers')
        bad = sorted(s for s in vmlinux if s in symvers and symvers[s][0] != vmlinux[s][0])
        gone = sorted(s for s in vmlinux if s not in symvers)
        r.p(f'| {variant} | {len(vmlinux)} | {len(vmlinux) - len(bad) - len(gone)} | {len(bad)} | {len(gone)} |')
        result[variant] = {'crc_mismatch': bad, 'missing': gone, 'symvers': symvers}
        if bad or gone:
            note = '（公开源码与原厂不一致，停）' if variant == 'stock' else ''
            r.failures[variant].append(f'手机模块依赖的符号有 {len(bad)} 个 CRC 不一致、{len(gone)} 个不存在{note}')
    r.p()
    for variant in variants:
        symvers = result[variant].pop('symvers')
        r.details(f'{variant}：CRC 不一致',
                  (f"{s}: 模块 {vmlinux[s][0]} -> 构建 {symvers[s][0]}  ({len(vmlinux[s][2])} 个模块，如 "
                   f"{sorted(vmlinux[s][2])[0]})" for s in result[variant]['crc_mismatch']))
        r.details(f'{variant}：构建里不存在（找不到提供者）',
                  (f"{s}  ({len(vmlinux[s][2])} 个模块，如 {sorted(vmlinux[s][2])[0]})"
                   for s in result[variant]['missing']))
    return result


def load_layouts(path):
    with open(path, 'rb') as f:
        return kabi.struct_layouts(kabi.parse_btf(f.read()))


def layout_diff(r, label, name, before, after):
    """List how layouts differ and return (additions, moved, appeared, vanished)."""
    changed = sorted(k for k in before.keys() & after.keys() if before[k] != after[k])
    additions, moved = [], []
    for key in changed:
        if len(before[key]) == 1 and len(after[key]) == 1:
            change = kabi.describe_layout_change(next(iter(before[key])), next(iter(after[key])))
        else:
            change = {'additions_only': False, 'size': None, 'moved': [], 'removed': [], 'added': [],
                      'reused': [], 'note': '同名结构体有多个定义'}
        (additions if change['additions_only'] else moved).append((key, change))
    appeared, vanished = sorted(after.keys() - before.keys()), sorted(before.keys() - after.keys())
    r.p(f'**{label}**：比较了 {len(before.keys() & after.keys())} 个结构体；'
        f'只在空隙或预留槽里新增成员 {len(additions)} 个，已有成员移位/尺寸变化 {len(moved)} 个；'
        f'新出现 {len(appeared)} 个，消失 {len(vanished)} 个。')
    r.p()
    lines = []
    for key, c in additions:
        lines.append(f'{key}: size {c["size"][0]}B 不变')
        lines += [f'    = {m} 仍在原偏移，改到了匿名 union 里' for m in c['reused']]
        lines += [f'    + @{off}B {member} : {sig}' for off, member, sig in c['added']]
    r.details(f'{name}：只在空隙或预留槽里新增成员的结构体', lines)
    lines = []
    for key, c in moved:
        lines.append(f'{key}: size {c["size"]} {c.get("note", "")}'.rstrip())
        lines += [f'    ~ {m}: {o} -> {n}' for m, o, n in c['moved']]
        lines += [f'    - {m}' for m in c['removed']]
        lines += [f'    + @{off}B {member} : {sig}' for off, member, sig in c['added']]
    r.details(f'{name}：已有成员移位或尺寸变化的结构体（需人工审查）', lines)
    r.details(f'{name}：新出现的结构体', appeared)
    r.details(f'{name}：消失的结构体', vanished)
    return [k for k, _ in additions], [k for k, _ in moved], appeared, vanished


def btf_section(r, art, base, variants):
    r.h('4. 结构体布局（BTF，覆盖内核里所有具名结构体）')
    phone = load_layouts(f'{base}/stock.btf')
    stock = load_layouts(f'{art}/stock/vmlinux.btf')
    additions, moved, appeared, vanished = layout_diff(r, '手机 → stock 构建', 'stock', phone, stock)
    summary = {'stock': {'additions': additions, 'moved': moved, 'appeared': appeared, 'vanished': vanished}}
    if additions or moved:
        r.failures['stock'].append(f"结构体布局与原厂不一致：{' '.join(additions + moved)}")
    if appeared or vanished:
        r.reviews['stock'].append(f'结构体集合与原厂不同：新出现 {len(appeared)} 个，消失 {len(vanished)} 个')
    if 'droidspaces' not in variants:
        return summary
    ds = load_layouts(f'{art}/droidspaces/vmlinux.btf')
    additions, moved, appeared, vanished = layout_diff(r, 'stock 构建 → droidspaces 构建（判定依据）',
                                                       'droidspaces', stock, ds)
    summary['droidspaces'] = {'additions': additions, 'moved': moved, 'appeared': appeared, 'vanished': vanished}
    if moved:
        r.failures['droidspaces'].append(f"已有成员移位或尺寸变化：{' '.join(moved)}")
    if 'struct task_struct' not in additions:
        r.reviews['droidspaces'].append('task_struct 没有出现「只新增成员」的变化，与补丁 001 的预期不符')
    unexpected = [k for k in additions if k != 'struct task_struct']
    if unexpected:
        r.reviews['droidspaces'].append(f"除 task_struct 外还有结构体新增成员：{' '.join(unexpected)}")
    return summary


def cert_section(r, art, base, variants):
    r.h('5. 模块签名证书')
    stock_der = kabi.pem_to_der(f'{base}/stock_module_signing.pem')
    builtin = int(re.search(r'\.builtin_trusted_keys: (\d+)', read(f'{base}/proc_keys.txt')).group(1))
    r.p(f'原厂内置 {builtin} 张。新 Image 应为「原厂证书 + 新内核自己的一张」，共 {builtin + 1} 张。')
    r.p()
    r.p('```')
    r.p(read(f'{base}/certs.txt'))
    r.p('```')
    r.p()
    result = {}
    for variant in variants:
        with open(f'{art}/{variant}/Image', 'rb') as f:
            certs = [der for _, der in kabi.find_der_certs(f.read())]
        found = stock_der in certs
        ok = found and len(certs) == builtin + 1
        r.p(f"- {variant}：Image 内置 {len(certs)} 张，原厂证书{'已包含' if found else '未包含'} {'✅' if ok else '❌'}")
        if not ok:
            r.failures[variant].append(f'证书不符合预期：{len(certs)} 张，原厂证书{"已" if found else "未"}包含')
        result[variant] = {'count': len(certs), 'stock_cert': found}
    return result


def version_section(r, art, base, variants):
    r.h('6. 版本串')
    stock_line = read(f'{base}/proc_version.txt')
    release = read(f'{base}/uname.txt')
    r.p(f'- 手机：`{stock_line}`')
    for variant in variants:
        line = read(f'{art}/{variant}/linux_version.txt')
        same_release = line.startswith(f'Linux version {release} ')
        same_line = line == stock_line
        mark = '✅ 整行一致' if same_line else ('⚠️ release 一致，其余不同' if same_release else '❌ release 不一致')
        r.p(f'- {variant}（{mark}）：`{line}`')
        if not same_release:
            r.failures[variant].append('Linux version 里的 release 与原厂不一致')
        elif not same_line:
            r.reviews[variant].append('/proc/version 的 release 一致，但其余部分（编译器或构建信息）不同')


def root_section(r, art, variants):
    r.h('7. 无 root')
    for variant in variants:
        with open(f'{art}/{variant}/Image', 'rb') as f:
            hits = sorted({m.group(0).decode().lower() for m in ROOT_STRINGS.finditer(f.read())})
        r.p(f"- {variant}：{'❌ 发现 ' + ' '.join(hits) if hits else '✅ 没有 KernelSU / SukiSU / SuSFS 字符串'}")
        if hits:
            r.failures[variant].append(f"Image 里有 root 相关字符串：{' '.join(hits)}")


def protection_section(r, art, base, variants):
    r.h('8. CONFIG_MODULE_SIG_PROTECT 实际生效')
    r.p('`gki_unprotected_symbols` 为空时，内核不再执行这项保护（`kernel/module/gki_module.c`），'
        '即使配置是 `=y`。这里解析 Image 里的两张表。')
    r.p()
    modules = kabi.load_modversions(f'{base}/device_modversions.tsv')
    signed = set(read(f'{base}/signed_modules.txt').split())
    # Unsigned modules may only take these from vmlinux or from a signed module
    # if they are on the unprotected list.
    need = {s for s, (_, provider, users) in modules.items()
            if (provider == '-' or provider in signed) and users - signed}
    r.p('| 构建 | 非保护符号 | 受保护导出 | 未签名模块需要的符号 | 其中会被拒绝 |')
    r.p('|---|---|---|---|---|')
    result = {}
    for variant in variants:
        unprotected = set(read(f'{art}/{variant}/gki_lists/unprotected.txt').split())
        protected = set(read(f'{art}/{variant}/gki_lists/protected_exports.txt').split())
        listed = set(read(f'{art}/{variant}/abi_symbollist.raw').split())
        blocked = sorted(need - unprotected)
        r.p(f'| {variant} | {len(unprotected)} | {len(protected)} | {len(need)} | {len(blocked)} |')
        if not unprotected or not protected:
            r.failures[variant].append('保护表为空：MODULE_SIG_PROTECT 实际没有生效')
        if unprotected != listed:
            r.failures[variant].append('Image 里的非保护符号表与 KMI 符号列表不一致')
        if blocked:
            r.failures[variant].append(f'{len(blocked)} 个未签名模块需要的符号会被保护逻辑拒绝')
        if 'abi_gki_protected_exports' in read(f'{art}/{variant}/source.diff'):
            r.failures[variant].append('改动了 android/abi_gki_protected_exports_*')
        result[variant] = {'unprotected': len(unprotected), 'protected': len(protected), 'blocked': blocked}
    r.p()
    for variant in variants:
        r.details(f'{variant}：会被拒绝的符号', result[variant]['blocked'])
    return result


def main(art, base, options_file, out):
    sys.stdout.reconfigure(encoding='utf-8')
    skipped = set(os.environ.get('SKIP_OPTIONS', '').split())
    variants = [v for v in ('stock', 'droidspaces') if os.path.exists(f'{art}/{v}/Image')]
    if 'stock' not in variants:
        sys.exit('no stock build: there is nothing to compare against')
    r = Report(variants)
    config_section(r, art, base, options_file, skipped, variants)
    symbols = symbols_section(r, art, variants)
    modules = modules_section(r, art, base, variants)
    btf = btf_section(r, art, base, variants)
    certs = cert_section(r, art, base, variants)
    version_section(r, art, base, variants)
    root_section(r, art, variants)
    protection = protection_section(r, art, base, variants)

    head = [
        '# 刷机前检查报告',
        '',
        f"- 手机：`{read(f'{base}/uname.txt')}`",
        f"- 源码提交：`{read(f'{art}/stock/common_head.txt', '?')}`",
        f"- 本次跳过的推荐选项：{' '.join(sorted(skipped)) or '无'}",
        f"- 两个变体都关掉的配置项：{os.environ.get('DISABLE_OPTIONS', '') or '无'}",
        f"- 风驰补丁：{'已打（非官方）' if os.environ.get('FENGCHI') == 'true' else '未打'}",
    ]
    if 'droidspaces' not in variants:
        head.append('- 本次没有 droidspaces 构建')
    verdicts = {}
    for variant in variants:
        fails, reviews = r.failures[variant], r.reviews[variant]
        verdicts[variant] = 'fail' if fails else ('review' if reviews else 'pass')
        text = {'fail': '不通过 ❌', 'review': '待人工判断 ⚠️', 'pass': '通过 ✅'}[verdicts[variant]]
        head += ['', f'**{variant}：{text}**']
        head += [f'- ❌ {f}' for f in fails]
        head += [f'- ⚠️ {w}' for w in reviews]
    os.makedirs(out, exist_ok=True)
    with open(f'{out}/abi-report.md', 'w', encoding='utf-8') as f:
        f.write('\n'.join(head + r.lines) + '\n')
    with open(f'{out}/abi-report.json', 'w', encoding='utf-8') as f:
        json.dump({'verdicts': verdicts, 'failures': r.failures, 'reviews': r.reviews, 'symbols': symbols,
                   'modules': modules, 'btf': btf, 'certs': certs, 'protection': protection},
                  f, ensure_ascii=False, indent=1)
    print('\n'.join(head))
    return 1 if any(r.failures.values()) else 0


if __name__ == '__main__':
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    sys.exit(main(*sys.argv[1:]))
