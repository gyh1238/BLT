#!/usr/bin/env bash
# A 12-validator chain at the manuscript's settings, measured, and attacked.
#
# Twelve validators, one per cluster head, which is the paper's configuration.
# Consensus latency, message size, storage growth and computation cost are
# measured here, and the tamper-evidence is demonstrated rather than asserted.
# Both run on one testnet:
#
# Part A, cost (K sync epochs at a 6 s block interval)
#   latency_s      broadcast (wall clock) -> commit of the including block H. CometBFT
#                  stamps a header with the commit time of the block before it, so
#                  H's commit time is read from the header of H+1
#   tx_bytes       protobuf size of the committed MsgCommitSyncBlock tx
#   block_bytes    block_size from /blockchain for the including block
#   interval_s     mean spacing of block times over the run
#   disk/block     data-directory growth per block, averaged over all nodes
#   cpu, rss       per-node CPU seconds per block and resident memory
#
# Part B, tamper attempts against the committed history
#   rollback       reference time behind the last committed epoch       (1110)
#   replay         an epoch id that is already committed                (1114)
#   forged time    reference time far from the consensus block time     (1112)
#   duplicate head the same head reported twice                         (1113)
#   outsider       a proposer that is not in the delegate set           (1101)
#   After each attempt every node's epoch history over the run is hashed; the
#   history must be unchanged and identical on all 12 nodes.
#
# Part C, reconnection (RECOVERY=1): node v3 is stopped, GAPS sync epochs commit
#   while it is away, and it rejoins. Per gap:
#   recovery_s     restart -> caught up with the head
#   rx_kib         bytes it received from peers while catching up (Prometheus)
#   epochs         epochs it can enumerate over the gap from its own history
#   records        member precision records it holds for the gap: full history
#                  (every epoch's member table) vs the latest block only, what a
#                  node keeping just the newest agreed state would have
#
# Part D, cross-cluster consistency (CROSS=1): proposals whose cluster rows
#   disagree with each other or with the summary: 1/4/7 heads reporting a cluster
#   time 20 ms off the rest, a row for a non-delegate head, and miscounted tables.
#   Reports whether each commits and whether all nodes still hold one history.
#
# Bandwidth: every node's CometBFT Prometheus endpoint is enabled so Part A can
# report bytes sent+received per node per block.
#
# The body carries N cluster summaries and MEMBERS member records.
#
# MEMBERS is how many member records a block carries, and the default holds the
# block at the 6.7 kB the manuscript specifies. This schema spends about 17 B on
# a record whose payload is 9 B, so 6.7 kB holds 298 of them, where the
# manuscript's packed layout holds one cluster's 683 in the same space.
# docs/spec/BLT-SAND-chain-spec.md section 7 derives both.
#
# Usage: chain_scale.sh     env: N (12), K (10), MEMBERS (298), COMMIT_MS (5500),
#                                TAMPER (1), RECOVERY (0), CROSS (0), GAPS ("1 5 10"),
#                                TESTNET_DIR, SCRATCH
# Do not wrap in a pipe, see recovery.sh.
set -uo pipefail

N="${N:-12}"
K="${K:-10}"
MEMBERS="${MEMBERS:-298}"
TAMPER="${TAMPER:-1}"
RECOVERY="${RECOVERY:-0}"
GAPS="${GAPS:-1 5 10}"
COMMIT_MS="${COMMIT_MS:-5500}"
export TESTNET_DIR="${TESTNET_DIR:-$HOME/.leochain-testnet12}"
SCRATCH="${SCRATCH:-${TMPDIR:-/tmp}/blt_scratch12}"   # override with SCRATCH=...
CHAIN_ID="leo_chain-1"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$SCRATCH"
LEAD=0
EPOCH=10

rpc() { echo "tcp://localhost:$((26657 + 10 * $1))"; }
http() { echo "http://localhost:$((26657 + 10 * $1))"; }
height() { curl -fsS --max-time 4 "$(http "$1")/status" 2>/dev/null | jq -r '.result.sync_info.latest_block_height // empty'; }

# ---------------------------------------------------------------- bring-up
echo ">> init $N validators in $TESTNET_DIR"
bash "$HERE/init_n_validators.sh" "$N" >/dev/null || { echo "init failed"; exit 1; }
for i in $(seq 0 $((N-1))); do
  CFG="$TESTNET_DIR/v$i/config/config.toml"
  sed -i "s|^timeout_commit = .*|timeout_commit = \"${COMMIT_MS}ms\"|" "$CFG"
  sed -i "s|^prometheus = false|prometheus = true|" "$CFG"
  sed -i "s|^prometheus_listen_addr = .*|prometheus_listen_addr = \":$((26660 + 10 * i))\"|" "$CFG"
done
bash "$HERE/start_local.sh" "$N" >/dev/null
echo ">> waiting for blocks"
for _ in $(seq 1 450); do h=$(height 0); [ -n "$h" ] && [ "$h" -ge 3 ] && break; sleep 2; done   # 12 nodes can take minutes to open RPC on a loaded host
h=$(height 0); echo "   height ${h:-none}"; [ -z "$h" ] && { echo "chain did not start"; bash "$HERE/start_local.sh" stop; exit 1; }

V0_ADDR=$(jq -r '.address' "$TESTNET_DIR/v0/key.json")

# --------------------------------------------------------- tx body template
make_template() {   # $1 proposer address, $2 duplicate-head flag
  python - "$1" "$2" "$N" "$MEMBERS" "$SCRATCH/template.json" <<'PY'
import json, sys
proposer, dup, n, members, out = sys.argv[1], sys.argv[2] == '1', int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
clusters = [{"cluster_id": i, "head_id": 100 + i, "head_offset_to_global_q01ns": 10 * (i - n // 2),
             "member_count": members // n, "inlier_count": members // n,
             "member_offset_mean_q01ns": 0, "member_offset_var_q01ns2": 25} for i in range(n)]
if dup:
    clusters[1]["head_id"] = clusters[0]["head_id"]
member_table = [{"node_id": k + 1, "cluster_id": k % n, "offset_to_head_q01ns": (k % 64) - 32,
                 "resp_prob_q255": 250, "time_acc_q01ns": 64, "flags": 1} for k in range(members)]
msg = {"@type": "/leochain.blt.MsgCommitSyncBlock", "proposer": proposer,
       "body": {"global": {"global_ref_time_q01ns": "0", "cluster_count": n, "member_count": members},
                "cluster_table": clusters, "member_table": member_table},
       "relay_path_hash": None, "epoch_id": 0}
tx = {"body": {"messages": [msg], "memo": "", "timeout_height": "0", "extension_options": [],
               "non_critical_extension_options": []},
      "auth_info": {"signer_infos": [], "fee": {"amount": [], "gas_limit": "2000000", "payer": "", "granter": ""}},
      "signatures": []}
json.dump(tx, open(out, "w"))
PY
}

# Submit one epoch from key $4 with lead offset $3 seconds. Echoes "code txhash t_broadcast".
submit() {   # $1 epoch, $2 template, $3 extra ref offset s, $4 key
  local epoch=$1 tmpl=$2 extra=$3 key=$4 ref t0 h
  ref=$(python -c "
import datetime as d
now = d.datetime.now(d.timezone.utc).timestamp()
print(int((int((now + $LEAD + $extra) * 1e9) - 1735689600000000000) * 10))")
  python -c "
import json
t = json.load(open('$tmpl'))
m = t['body']['messages'][0]
m['body']['global']['global_ref_time_q01ns'] = '$ref'
m['epoch_id'] = $epoch
json.dump(t, open('$SCRATCH/unsigned.json', 'w'))"
  leochaind tx sign "$SCRATCH/unsigned.json" --from "$key" --keyring-backend test \
    --home "$TESTNET_DIR/v0" --chain-id "$CHAIN_ID" --node "$(rpc 0)" \
    --output-document "$SCRATCH/signed.json" >/dev/null 2>&1 || { echo "signfail - -"; return; }
  t0=$(python -c "import time; print(time.time())")
  local bres ccode
  bres=$(leochaind tx broadcast "$SCRATCH/signed.json" --node "$(rpc 0)" --output json 2>/dev/null)
  h=$(echo "$bres" | jq -r '.txhash // empty')
  [ -z "$h" ] && { echo "nobroadcast - $t0"; return; }
  # A tx refused at CheckTx never reaches a block; report its mempool code instead of timing out.
  ccode=$(echo "$bres" | jq -r '.code // 0')
  [ "$ccode" != "0" ] && { echo "$ccode $h $t0"; return; }
  local code=""
  for _ in $(seq 1 60); do
    sleep 0.5
    code=$(leochaind query tx "$h" --node "$(rpc 0)" --output json 2>/dev/null | jq -r '.code // empty')
    [ -n "$code" ] && break
  done
  echo "${code:-timeout} $h $t0"
}

txinfo() {   # $1 hash -> "height tx_bytes raw_log"
  curl -fsS "$(http 0)/tx?hash=0x$1" 2>/dev/null | python -c "
import json, sys, base64
r = json.load(sys.stdin)['result']
print(r['height'], len(base64.b64decode(r['tx'])), (r['tx_result'].get('log') or '').replace(' ', '_')[:200])" 2>/dev/null
}

block_time_s() {   # $1 height
  curl -fsS "$(http 0)/block?height=$1" | python -c "
import json, sys, re, datetime as d
t = json.load(sys.stdin)['result']['block']['header']['time']
t = re.sub(r'\.(\d{6})\d*', r'.\1', t).replace('Z', '+00:00')
print(d.datetime.fromisoformat(t).timestamp())"
}

block_size() {   # $1 height
  curl -fsS "$(http 0)/blockchain?minHeight=$1&maxHeight=$1" | jq -r '.result.block_metas[0].block_size'
}

proc_stats() {   # total CPU seconds and mean RSS MB over leochaind processes
  powershell.exe -NoProfile -Command \
    "\$p = Get-Process leochaind -ErrorAction SilentlyContinue; if (\$p) { '{0:F1} {1:F0} {2}' -f ((\$p | Measure-Object CPU -Sum).Sum), ((\$p | Measure-Object WorkingSet64 -Average).Average / 1MB), \$p.Count }" | tr -d '\r'
}

p2p_bytes() {   # $1 node -> total p2p bytes sent + received so far
  curl -fsS --max-time 4 "http://localhost:$((26660 + 10 * $1))/metrics" 2>/dev/null |
    awk '/^cometbft_p2p_peer_(send|receive)_bytes_total/ {s += $NF} END {printf "%.0f", s}'
}
p2p_rx() {   # $1 node -> total p2p bytes received so far
  curl -fsS --max-time 4 "http://localhost:$((26660 + 10 * $1))/metrics" 2>/dev/null |
    awk '/^cometbft_p2p_peer_receive_bytes_total/ {s += $NF} END {printf "%.0f", s}'
}
p2p_total() { local t=0 b; for i in $(seq 0 $((N-1))); do b=$(p2p_bytes "$i"); t=$((t + ${b:-0})); done; echo "$t"; }

data_bytes_total() { du -sb "$TESTNET_DIR"/v*/data 2>/dev/null | awk '{s+=$1} END {print s}'; }

commit_one() {   # calibrate the lead against R3, like recovery.sh. Echoes "latency tx_bytes block_bytes height"
  local epoch=$1 r code h t0 info hh bytes log skew
  for _ in 1 2 3; do
    r=$(submit "$epoch" "$SCRATCH/template.json" 0 v0)
    code=${r%% *}; h=$(echo "$r" | cut -d' ' -f2); t0=$(echo "$r" | cut -d' ' -f3)
    if [ "$code" = "0" ]; then
      info=$(txinfo "$h"); hh=${info%% *}; bytes=$(echo "$info" | cut -d' ' -f2)
      for _ in $(seq 1 30); do [ "$(height 0)" -gt "$hh" ] && break; sleep 1; done
      bt=$(block_time_s $((hh + 1)))
      echo "$(python -c "print(f'{$bt - $t0:.2f}')") $bytes $(block_size "$hh") $hh"
      return
    fi
    log=$(txinfo "$h" | cut -d' ' -f3)
    skew=$(echo "$log" | grep -o 'skew=-\?[0-9]\+' | head -1 | cut -d= -f2)
    if [ "$code" = "1112" ] && [ -n "$skew" ]; then
      LEAD=$(python -c "print(round($LEAD - $skew / 1e9, 3))")
    else
      echo "  ! epoch $epoch code=$code $log" >&2; return
    fi
  done
}

history_hash() {   # $1 node, $2 from, $3 to
  leochaind query blt epoch-history-range "$2" "$3" --node "$(rpc "$1")" --output json 2>/dev/null |
    python -c "import sys, hashlib, json; print(hashlib.sha256(json.dumps(json.load(sys.stdin)['snapshots'], sort_keys=True).encode()).hexdigest()[:16])" 2>/dev/null
}

# ------------------------------------------------------------------ Part A
make_template "$V0_ADDR" 0
echo
echo "== Part A: $K sync epochs, $N validators, $MEMBERS member records, timeout_commit ${COMMIT_MS}ms"
h_start=$(height 0); disk0=$(data_bytes_total); read -r cpu0 _ _ < <(proc_stats); net0=$(p2p_total)
printf "%6s %10s %9s %11s %7s\n" epoch latency_s tx_bytes block_bytes height
lat_all=""
for _ in $(seq 1 "$K"); do
  EPOCH=$((EPOCH + 1))
  out=$(commit_one "$EPOCH")
  [ -z "$out" ] && continue
  set -- $out
  printf "%6s %10s %9s %11s %7s\n" "$EPOCH" "$1" "$2" "$3" "$4"
  lat_all="$lat_all $1"
  sleep 1
done
h_end=$(height 0); disk1=$(data_bytes_total); read -r cpu1 rss nproc < <(proc_stats); net1=$(p2p_total)
t_first=$(block_time_s "$h_start"); t_last=$(block_time_s "$h_end")
python - "$lat_all" "$h_start" "$h_end" "$t_first" "$t_last" "$disk0" "$disk1" "$cpu0" "$cpu1" "$rss" "$nproc" "$N" "$net0" "$net1" <<'PY'
import sys, statistics as st
lat = [float(x) for x in sys.argv[1].split()]
h0, h1 = int(sys.argv[2]), int(sys.argv[3]); t0, t1 = float(sys.argv[4]), float(sys.argv[5])
d0, d1 = int(sys.argv[6]), int(sys.argv[7]); c0, c1 = float(sys.argv[8]), float(sys.argv[9])
rss, nproc, n = float(sys.argv[10]), int(sys.argv[11]), int(sys.argv[12])
net0, net1 = float(sys.argv[13] or 0), float(sys.argv[14] or 0)
blocks = max(h1 - h0, 1)
print()
print(f"committed         {len(lat)}")
if lat:
    print(f"latency_s         median {st.median(lat):.2f}  min {min(lat):.2f}  max {max(lat):.2f}")
print(f"interval_s        {(t1 - t0) / blocks:.2f}  over {blocks} blocks")
print(f"disk/block        {(d1 - d0) / blocks / n / 1024:.1f} KiB per node")
print(f"cpu               {(c1 - c0) / blocks / max(nproc, 1):.3f} s per block per node  ({nproc} processes)")
print(f"rss               {rss:.0f} MB mean per node")
print(f"p2p               {(net1 - net0) / blocks / n / 1024:.1f} KiB sent+received per node per block")
print(f"SUMMARY n={n} lat_med={st.median(lat) if lat else float('nan'):.2f} interval={(t1 - t0) / blocks:.2f} "
      f"cpu_per_block_node={(c1 - c0) / blocks / max(nproc, 1):.3f} rss={rss:.0f} "
      f"p2p_kib_per_block_node={(net1 - net0) / blocks / n / 1024:.1f}")
PY

# ------------------------------------------------------------------ Part B
if [ "$TAMPER" = "1" ]; then
echo
echo "== Part B: tamper attempts (history window $h_start..$(height 0))"
win_to=$(height 0)
base=$(history_hash 0 "$h_start" "$win_to")
printf "%-16s %6s %-10s %s\n" attempt code history "nodes agreeing"
attempt() {   # $1 label, $2 epoch, $3 template, $4 extra offset s, $5 key
  local r code same=0 hv
  r=$(submit "$2" "$3" "$4" "$5"); code=${r%% *}
  sleep 7
  for i in $(seq 0 $((N-1))); do
    hv=$(history_hash "$i" "$h_start" "$win_to")
    [ "$hv" = "$base" ] && same=$((same + 1))
  done
  local hist="unchanged"; [ "$(history_hash 0 "$h_start" "$win_to")" != "$base" ] && hist="CHANGED"
  printf "%-16s %6s %-10s %s/%s\n" "$1" "$code" "$hist" "$same" "$N"
}
attempt "rollback"       $((EPOCH + 1)) "$SCRATCH/template.json" -30 v0
attempt "replay"         "$EPOCH"       "$SCRATCH/template.json" 0   v0
attempt "forged time"    $((EPOCH + 2)) "$SCRATCH/template.json" 60  v0
make_template "$V0_ADDR" 1
attempt "duplicate head" $((EPOCH + 3)) "$SCRATCH/template.json" 0   v0
leochaind keys add outsider --keyring-backend test --home "$TESTNET_DIR/v0" --output json >/dev/null 2>&1
OUT_ADDR=$(leochaind keys show outsider -a --keyring-backend test --home "$TESTNET_DIR/v0")
leochaind tx bank send v0 "$OUT_ADDR" 1000000leo --keyring-backend test --home "$TESTNET_DIR/v0" \
  --chain-id "$CHAIN_ID" --node "$(rpc 0)" -y >/dev/null 2>&1; sleep 8
make_template "$OUT_ADDR" 0
attempt "outsider"       $((EPOCH + 4)) "$SCRATCH/template.json" 0   outsider

echo
echo "code 0 on any attempt, or a CHANGED history, is a failure of the ledger's guarantees."
EPOCH=$((EPOCH + 5))
make_template "$V0_ADDR" 0
fi

# ------------------------------------------------------------------ Part D
if [ "${CROSS:-0}" = "1" ]; then
echo
echo "== Part D: cross-cluster consistency checks ($N cluster heads)"
printf "%-32s %6s %-10s %s\n" attempt code result "nodes agreeing"
cross() {   # $1 label, $2 mutation of the honest template
  python - "$2" "$SCRATCH/template.json" "$SCRATCH/cross.json" <<'PY'
import json, sys
mut, src, out = sys.argv[1:4]
t = json.load(open(src))
b = t['body']['messages'][0]['body']
ct = b['cluster_table']
if mut.startswith('shift'):            # k heads report a cluster time 20 ms off the others
    for c in ct[:int(mut[5:])]:
        c['head_offset_to_global_q01ns'] += 200_000_000   # 20 ms in 0.1 ns units (tolerance 10 ms)
elif mut == 'unknown':                 # a cluster row signed for a head that is not a delegate
    ct[0]['head_id'] = 999
elif mut == 'clusters':                # summary claims fewer clusters than it carries
    b['global']['cluster_count'] = len(ct) - 1
elif mut == 'members':                 # summary claims more member records than it carries
    b['global']['member_count'] = len(b['member_table']) + 1
json.dump(t, open(out, 'w'))
PY
  EPOCH=$((EPOCH + 1))
  local r code same=0 top ref hv res
  r=$(submit "$EPOCH" "$SCRATCH/cross.json" 0 v0); code=${r%% *}
  sleep 8
  top=$(( $(height 0) - 1 ))
  ref=$(history_hash 0 "$h_start" "$top")
  for i in $(seq 0 $((N-1))); do
    hv=$(history_hash "$i" "$h_start" "$top")
    [ "$hv" = "$ref" ] && same=$((same + 1))
  done
  res="rejected"; [ "$code" = "0" ] && res="committed"
  printf "%-32s %6s %-10s %s/%s\n" "$1" "$code" "$res" "$same" "$N"
}
cross "control: consistent summary"  none
cross "1 of $N heads 20 ms off"      shift1
cross "4 of $N heads 20 ms off"      shift4
cross "7 of $N heads 20 ms off"      shift7
cross "head not in delegate set"     unknown
cross "cluster count != table"       clusters
cross "member count != table"        members
echo
echo "A committed epoch keeps every cluster row as reported, so a minority of heads that"
echo "disagree stays visible on the ledger; a global time that most heads contradict (1109),"
echo "and a row for a non-delegate head (1102) are refused; a summary that miscounts its"
echo "own tables is refused at admission (message validation, code 18) by every node."
fi

# ------------------------------------------------------------------ Part C
if [ "$RECOVERY" = "1" ]; then
VICTIM=3
echo
echo "== Part C: node v$VICTIM disconnected for N committed epochs, then rejoins"
printf "%6s %9s %10s %9s %8s %22s\n" gap missed_h recovery_s rx_kib epochs "records full/latest"
for gap in $GAPS; do
  pid=$(sed -n "$((VICTIM + 1))p" "$TESTNET_DIR/pids")
  h_down=$(height "$VICTIM")
  kill "$pid" 2>/dev/null; sleep 4
  committed=0
  for _ in $(seq 1 "$gap"); do
    EPOCH=$((EPOCH + 1))
    [ -n "$(commit_one "$EPOCH")" ] && committed=$((committed + 1))
    sleep 1
  done
  h_head=$(height 0)
  nohup leochaind start --home "$TESTNET_DIR/v$VICTIM" --log_level info >"$TESTNET_DIR/v$VICTIM.log" 2>&1 &
  newpid=$!
  sed -i "$((VICTIM + 1))s/.*/$newpid/" "$TESTNET_DIR/pids"
  t0=$(python -c "import time; print(time.time())")
  rx0=""; rec="-"
  for _ in $(seq 1 180); do
    sleep 1
    [ -z "$rx0" ] && rx0=$(p2p_rx "$VICTIM")
    hv=$(height "$VICTIM"); h0=$(height 0)
    if [ -n "$hv" ] && [ -n "$h0" ] && [ "$hv" -ge "$((h0 - 1))" ]; then
      rec=$(python -c "import time; print(f'{time.time() - $t0:.1f}')"); break
    fi
  done
  rx1=$(p2p_rx "$VICTIM")
  rx="-"; [ -n "$rx0" ] && [ -n "$rx1" ] && rx=$(python -c "print(f'{($rx1 - ${rx0:-0}) / 1024:.0f}')")
  counts=$(leochaind query blt epoch-history-range "$h_down" "$h_head" --node "$(rpc "$VICTIM")" --output json 2>/dev/null |
    python -c "
import json, sys
snaps = json.load(sys.stdin).get('snapshots', [])
full = sum(int(s['body']['global'].get('member_count', 0)) for s in snaps)
latest = int(snaps[-1]['body']['global'].get('member_count', 0)) if snaps else 0
print(len(snaps), full, latest)" 2>/dev/null)
  set -- ${counts:-0 0 0}
  printf "%6s %9s %10s %9s %8s %22s\n" "$committed" "$((h_head - h_down))" "$rec" "$rx" "$1/$committed" "$2 / $3"
done
echo "records: member precision records the rejoined node holds for the gap. A node"
echo "keeping only the newest agreed state has the latest block's records alone."
fi
bash "$HERE/start_local.sh" stop >/dev/null
