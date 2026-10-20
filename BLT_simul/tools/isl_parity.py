"""Check the Unity port of the ISL link model against blt_isl.py.

Compiles BLT_dt/Assets/Scripts/IslLinkModel.cs with the Roslyn compiler that
ships inside a Unity editor, runs it on the constellation main_all builds, and
compares every quantity the two implementations should agree on.

Exact:     outage exponent and probabilities, the link set (count + checksum),
           acquisition behaviour.
Close:     route statistics. Both use Dijkstra on the same weights, but ties
           between equal-cost routes break differently, so hop means may differ
           in the last digits.
Statistical: drawn route success against its expectation.

Run:  python tools/isl_parity.py [--sizes 500,8192]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                 # BLT_simul/
REPO = os.path.dirname(ROOT)                 # the repository, which also holds BLT_dt/
sys.path[:0] = [os.path.join(ROOT, 'model'), os.path.join(ROOT, 'figures')]
os.chdir(ROOT)

import blt_isl  # noqa: E402
import main_all  # noqa: E402

UNITY_DATA = os.environ.get(
    'UNITY_EDITOR_DATA', r'C:\Program Files\Unity\Hub\Editor\6000.2.8f1\Editor\Data')
DOTNET = os.path.join(UNITY_DATA, 'NetCoreRuntime', 'dotnet.exe')
CSC = os.path.join(UNITY_DATA, 'DotNetSdkRoslyn', 'csc.dll')
SOURCES = [os.path.join(REPO, 'BLT_dt', 'Assets', 'Scripts', 'IslLinkModel.cs'),
           os.path.join(HERE, 'isl_parity', 'Parity.cs')]

_failures = 0


def check(name, ok, detail=''):
    global _failures
    _failures += not ok
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ''))


def compile_port(workdir):
    shared = os.path.join(UNITY_DATA, 'NetCoreRuntime', 'shared', 'Microsoft.NETCore.App')
    runtime = sorted(os.listdir(shared))[-1]
    refdir = os.path.join(shared, runtime)
    refs = [f'-r:{os.path.join(refdir, f)}' for f in
            ('System.Runtime.dll', 'System.Private.CoreLib.dll', 'System.Console.dll',
             'System.Collections.dll', 'System.Linq.dll', 'System.Runtime.Extensions.dll')]
    exe = os.path.join(workdir, 'parity.dll')
    # Unity 2021.3 compiles C# 9; hold the port to it.
    subprocess.run([DOTNET, CSC, '-nologo', '-nostdlib', '-langversion:9.0', '-optimize+',
                    f'-out:{exe}', *refs, *SOURCES], check=True)
    with open(os.path.join(workdir, 'parity.runtimeconfig.json'), 'w') as f:
        json.dump({'runtimeOptions': {'tfm': 'net6.0', 'framework': {
            'name': 'Microsoft.NETCore.App', 'version': runtime}}}, f)
    return exe


def python_side(pos, cl, heads):
    n = len(pos)
    p = blt_isl
    out = {'k': p.outage_exponent()}
    for d in (0, 1250, 2000, 2400, 2500):
        out[f'pout_{d}'] = float(p.exchange_outage_prob(d))
    model = p.LinkModel(n, np.random.default_rng(0))
    model.update(pos, cl, 0.0)
    keys = model.i * n + model.j
    out['links'] = len(keys)
    out['key_checksum'] = float(np.sum(keys % 1000003))
    hops, loss, unroutable = [], [], 0
    for tree, idxs, h in zip(model.local_trees, cl, heads):
        m = idxs[idxs != h]
        dep = tree.depth[m]
        unroutable += int((dep < 0).sum())
        ok = m[dep > 0]
        hops.append(tree.depth[ok])
        loss.append(1 - tree.path_success()[ok])
    hops, loss = np.concatenate(hops), np.concatenate(loss)
    out.update(routed=len(hops), unroutable=unroutable, hops_mean=float(hops.mean()),
               hops_max=int(hops.max()), loss_mean=float(loss.mean()))
    return out


def run_size(n, exe, workdir):
    sats = main_all.initialize_satellites(n, 0, seed=1)
    pos, *_ = main_all._extract_arrays(sats)
    cl = main_all.cluster_indices_from_kmeans(pos, 12)
    heads = blt_isl.cluster_heads(pos, cl)
    labels = np.empty(n, dtype=int)
    for c, idxs in enumerate(cl):
        labels[idxs] = c
    pfile, hfile = os.path.join(workdir, f'pos{n}.csv'), os.path.join(workdir, f'heads{n}.csv')
    with open(pfile, 'w') as f:
        for (x, y, z), c in zip(pos, labels):
            f.write(f'{float(x)!r},{float(y)!r},{float(z)!r},{int(c)}\n')
    with open(hfile, 'w') as f:
        f.write('\n'.join(str(h) for h in heads))
    res = subprocess.run([DOTNET, exe, pfile, hfile], capture_output=True, text=True)
    if res.returncode:
        raise RuntimeError(f'C# harness failed:\n{res.stderr[-2000:]}')
    cs = {k: float(v) for k, v in (line.split() for line in res.stdout.split('\n') if line.strip())}
    py = python_side(pos, cl, heads)

    print(f'\nN = {n}')
    check('outage exponent identical', cs['k'] == py['k'], f"{cs['k']}")
    worst = max(abs(cs[f'pout_{d}'] - py[f'pout_{d}']) for d in (0, 1250, 2000, 2400, 2500))
    check('outage probabilities agree to 1e-12', worst < 1e-12, f'worst {worst:.1e}')
    check('same link set', cs['links'] == py['links'] and cs['key_checksum'] == py['key_checksum'],
          f"C# {int(cs['links'])} vs Python {py['links']}")
    check('same routable / unroutable members',
          cs['routed'] == py['routed'] and cs['unroutable'] == py['unroutable'],
          f"C# {int(cs['routed'])}/{int(cs['unroutable'])} vs Python {py['routed']}/{py['unroutable']}")
    check('mean hops within 2%', abs(cs['hops_mean'] - py['hops_mean']) <= 0.02 * py['hops_mean'],
          f"C# {cs['hops_mean']:.3f} vs Python {py['hops_mean']:.3f}")
    check('expected route loss within 5% (relative) or 1e-5',
          abs(cs['loss_mean'] - py['loss_mean']) <= max(0.05 * py['loss_mean'], 1e-5),
          f"C# {cs['loss_mean']:.5f} vs Python {py['loss_mean']:.5f}")
    check('drawn success matches expectation (C#)',
          abs(cs['draw_observed'] - cs['draw_expected']) < 0.005,
          f"{cs['draw_observed']:.4f} vs {cs['draw_expected']:.4f}")
    check('acquisition: none far, none while acquiring, one after',
          (cs['acq_far'], cs['acq_new'], cs['acq_after']) == (0, 0, 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sizes', default='500,8192')
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as work:
        exe = compile_port(work)
        for n in (int(s) for s in args.sizes.split(',')):
            run_size(n, exe, work)
    print(f"\n{'all checks passed' if not _failures else f'{_failures} check(s) FAILED'}")
    return 1 if _failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
