"""Guards the single-engine invariant, the parameter wiring, and the vote.

Three questions, each of which would invalidate a comparison if the answer
changed: is every arm running one engine rather than a copy of it, is every
driver reading the same parameters from the registry, and does a round still
commit by quorum rather than by averaging what the heads reported?

Run:  python tools/verify_engines.py
"""

from __future__ import annotations

import os as _os
import sys as _sys
# Run from anywhere: the engine modules live in model/, figure style in figures/, and
# data/ and result/ are resolved from the repository root.
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.isdir(_os.path.join(_ROOT, 'model')):   # climb to the repository root
    _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_os.path.join(_ROOT, 'model'), _os.path.join(_ROOT, 'figures')]
_os.chdir(_ROOT)

import ast
import io
import os
import sys

ENGINE = 'model/main_all.py'
RETIRED = 'main_all_panela.py'

PASS, FAIL = 'OK  ', 'FAIL'
_failures = 0


def check(name: str, ok: bool, detail: str = '') -> None:
    global _failures
    if not ok:
        _failures += 1
    print(f"  [{PASS if ok else FAIL}] {name}" + (f"  {detail}" if detail else ''))


def definitions(path: str) -> dict:
    src = io.open(path, encoding='utf-8').read()
    lines = src.split('\n')
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef):
            key = node.name
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            key = 'const:' + node.targets[0].id
        else:
            continue
        out[key] = '\n'.join(lines[node.lineno - 1:node.end_lineno])
    return out


def test_single_engine() -> None:
    print("")
    print("single engine:")
    check("the retired fork has not come back", not os.path.exists(RETIRED))

    defs = definitions(ENGINE)
    # Capabilities that existed only in the fork and had to survive the merge.
    for name in ('_labels_from_clusters', 'const:FTSP_STATIC_GRAPH'):
        check(f"ported from the fork: {name}", name in defs)
    # Definitions the merge kept main_all's version of.
    for name in ('sync_with_cluster_bc_vec', 'sync_global_ats', 'sync_local_robust',
                 'cluster_head_graph', 'headnet_byhop'):
        check(f"canonical definition present: {name}", name in defs)

    src = io.open(ENGINE, encoding='utf-8').read()
    check("neighbour selection keeps the optional cluster restriction",
          'labels=None' in src)


def test_parameter_wiring() -> None:
    print("")
    print("parameter wiring:")
    import blt_params
    import engine_profiles
    import main_all

    want = blt_params.ppb_to_hz(blt_params.value('osc_healthy_ppb'))
    check("healthy oscillator comes from the parameter registry",
          abs(main_all.NORMAL_OSC_STDDEV - want) < 1e-12,
          f"{main_all.NORMAL_OSC_STDDEV:.4g} Hz = {blt_params.value('osc_healthy_ppb')} ppb")
    check("faulty oscillator is NOT the healthy one",
          engine_profiles.FAULTY_STDDEV_HZ > 5 * want,
          f"faulty {engine_profiles.FAULTY_STDDEV_HZ:.4g} Hz vs healthy {want:.4g} Hz")

    # Both profiles must name parameters the engine actually defines; apply()
    # raises otherwise, which is why it is called here.
    for label, profile in (('accuracy', engine_profiles.ACCURACY_PROFILE),
                           ('fault', engine_profiles.FAULT_PROFILE)):
        try:
            engine_profiles.apply(profile, main_all)
            check(f"{label} profile binds onto the engine", True,
                  f"{len(profile)} parameters")
        except AttributeError as exc:
            check(f"{label} profile binds onto the engine", False, str(exc))


def test_consensus_is_a_vote() -> None:
    """The commit rule must be a vote on a proposal, not a spread test on a
    median. The distinction is not cosmetic: under the median rule a colluding
    majority committed cleanly and the commit rate ROSE with the number of
    liars."""
    print("")
    print("consensus:")
    import blt_params
    src = io.open(ENGINE, encoding='utf-8').read()
    body = src[src.index('def sync_with_cluster_bc_vec'):src.index('def sync_local_robust')]

    check("the proposal is fixed by rotation, not derived from the values",
          'proposer = int(round_no)' in body)
    check("heads vote on the proposal", 'votes = np.abs(reported - proposal)' in body)
    check("the committed value is the proposal itself", 'global_avg = proposal' in body)
    # The ban on aggregating the reported values applies to the COMMIT path. The
    # failed-round fallback does reconcile toward their median, which is
    # sound because it commits nothing: no block, no ledger entry, and the value
    # is not what a later round votes on. So the fallback block is cut out first
    # and then checked separately, if it ever commits, both checks fail.
    fb_start = body.find('if not FAILED_ROUND_FALLBACK:')
    fallback = body[fb_start:body.index('\n\n', fb_start)] if fb_start >= 0 else ''
    commit_path = body.replace(fallback, '') if fallback else body
    check("no aggregate over reported values survives in the commit path",
          'np.median(reported[' not in commit_path and 'np.median(cluster_avgs[' not in commit_path)
    check("the failed-round fallback commits nothing",
          bool(fallback) and "BC_DIAG['commit']" not in fallback and 'global_avg' not in fallback,
          'it reconciles toward the median of the reports and returns')
    check("a lie that carries a quorum is counted separately",
          "BC_DIAG['bad_commit']" in body)

    q = blt_params.value('bc_quorum')
    check("quorum is the classical PBFT 2/3", abs(q - 2 / 3) < 1e-9,
          f"q={q:.4f}: honest carries while f <= N*{1 - q:.3f}, "
          f"a lie carries once f >= N*{q:.3f}")


def main() -> int:
    print("BLT-SAND engine verification")
    test_single_engine()
    test_parameter_wiring()
    test_consensus_is_a_vote()
    print("")
    print('all checks passed' if not _failures else f'{_failures} check(s) FAILED')
    return 1 if _failures else 0


if __name__ == '__main__':
    sys.exit(main())
