# Running `leo_chain-1` on a Bare-Metal / Server Host

This is the operator runbook for taking `leochaind` out of the laptop
sandbox and onto a real server. It assumes the build artifacts produced
by `make build-go` (or `make build-all`) are available and that you have
shell access to the target host.

---

## 1. Sizing the host

Numbers below are from a brief 12-node co-located run on a 2-vCPU /
15 GiB VM (this dev box):

| Metric | Per node | 12 nodes co-located |
|--------|----------|---------------------|
| RSS at idle | ~170 MB | ~2.0 GB |
| CPU (steady-state, empty mempool) | ~5–10 % of one core | ~108 % across 2 vCPUs (saturated) |
| Disk: state + WAL growth | ~50 MB/day per node (empty blocks) | ~600 MB/day combined |
| Disk: full-payload blocks (8 192 members, every block) | ~135 kB × 24 700 blocks/day ≈ **3.2 GB/day per node** | **~38 GB/day combined** |
| Block interval | n/a | 3.5 s target; observed 4–6 s under CPU saturation |

> **The first 30–60 s after launch always show longer block intervals**
> (15+ s) while CometBFT bootstraps its view-change and proposer
> rotation. Sample at height ≥ 30 for honest measurements.

### Recommended minimums (single-host, 12 co-located validators)

| Resource | Minimum | Comfortable |
|----------|---------|-------------|
| vCPU | 4 | 8 (1 core per ~3 validators when payload is full) |
| RAM | 4 GB | 8 GB |
| Disk free | 100 GB (≈ 1 month of full-payload blocks) | 500 GB + tiered cold storage |
| Network | 1 Gbps loopback is fine (single host); cross-host wants ≥ 10 ms RTT for the 3.5 s commit budget to hold | — |

For a **production deployment** the right model is **one validator per
host** (or per container), not 12 co-located. Co-location only makes
sense for a dev/staging cluster.

---

## 2. Two deployment modes

### Mode A — Co-located dev cluster (single host)

Quickest path; mirrors `scripts/init_n_validators.sh` + `scripts/start_local.sh`.
Use for staging, CI, and digital-twin demos. Not recommended for production.

```bash
# from the repo root on the target host
make build-go                                    # produces release/leochaind-linux-{amd64,arm64}
sudo install -m 0755 release/leochaind-linux-amd64 /usr/local/bin/leochaind
export PATH=$PATH:/usr/local/bin

./scripts/init_n_validators.sh 12                # writes ~/.leochain-testnet/v{0..11}
./scripts/start_local.sh 12                      # nohup-launches all 12

./scripts/check_unity_rpc.sh                     # verifies the chain
./scripts/start_local.sh stop                    # graceful shutdown
```

`init_n_validators.sh` already steps p2p/RPC/API/gRPC ports by 10 per
validator and wires `persistent_peers` full-mesh on 127.0.0.1, so no
extra firewall surgery is needed on a dev box.

### Mode B — One validator per host (production)

This is the layout the BLT-SAND spec assumes (12 independent operators,
one per cluster head). The bootstrap is essentially `scripts/init_n_validators.sh`
run **once** to produce the 12 home dirs + the genesis with all 12
`initial_delegates`, then each operator copies their own `v<i>/` to
their own host.

Suggested handoff:

```bash
# on a bastion / build host
./scripts/init_n_validators.sh 12
tar -C ~/.leochain-testnet -czf v0-home.tar.gz v0/
# repeat for v1..v11, ship each tarball to the corresponding operator
# also publish ~/.leochain-testnet/v0/config/genesis.json as the canonical genesis
```

Each operator on their host:

```bash
sudo install -m 0755 leochaind-linux-amd64 /usr/local/bin/leochaind
mkdir -p ~/.leochain
tar -C ~/.leochain --strip-components=1 -xzf v<i>-home.tar.gz
# patch persistent_peers from the loopback-mesh in the tarball to the
# real public IP:port of the other 11 operators, e.g.:
sed -i 's|@127.0.0.1:266|@<PUBLIC_IP_OF_PEER>:266|g' ~/.leochain/config/config.toml
sudo systemctl enable --now leochaind                # see §3 below
```

---

## 3. `systemd` unit (one per host)

Drop this at `/etc/systemd/system/leochaind.service`:

```ini
[Unit]
Description=leo_chain-1 validator
After=network-online.target
Wants=network-online.target

[Service]
User=leochain
Group=leochain
ExecStart=/usr/local/bin/leochaind start --home /var/lib/leochain --log_level info
Restart=on-failure
RestartSec=5
LimitNOFILE=65535
# tighten as appropriate
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=yes
ReadWritePaths=/var/lib/leochain

[Install]
WantedBy=multi-user.target
```

```bash
sudo useradd --system --create-home --home-dir /var/lib/leochain leochain
sudo install -d -o leochain -g leochain /var/lib/leochain
sudo mv ~/.leochain/* /var/lib/leochain/
sudo chown -R leochain:leochain /var/lib/leochain
sudo systemctl daemon-reload
sudo systemctl enable --now leochaind
journalctl -u leochaind -f
```

---

## 4. Firewall

| Port | Purpose | Should be reachable from |
|------|---------|--------------------------|
| 26656/tcp | p2p (CometBFT) | the other 11 validators only |
| 26657/tcp | RPC (used by Unity, ops dashboards) | trusted ops network |
| 1317/tcp | REST gateway (`/leochain/blt/latest_epoch` for Unity) | trusted ops network |
| 9090/tcp | gRPC | trusted ops network |

Block 26657 / 1317 / 9090 from the public internet. The p2p port is the
only one that needs cross-operator reachability.

---

## 5. Long-running concerns to plan for now

1. **Disk growth.** Full-payload blocks (12 clusters × 8 192 members)
   are ~135 kB on-wire ≈ **3.2 GB/day per node** at 3.5 s blocks.
   Enable `app.toml` state pruning: `pruning = "custom"` with
   `pruning-keep-recent = 100000`, `pruning-interval = 100`. Snapshot
   policy is left to ops.
2. **`min-gas-prices` is set to `0leo`** in dev. For an open network,
   set a non-zero floor in `app.toml` once the token has value.
3. **Halt-height / hard fork.** Spec §IV.A allows a single hard-fork
   checkpoint during the mission lifetime. Operators should agree on a
   `halt-height` in `app.toml` ahead of any planned upgrade.
4. **Liveness budget.** 2/3 quorum means up to 4 of 12 validators can
   be offline. Beyond that, the chain stalls. Page on
   `leochaind status` reporting `catching_up: false` going false-positive
   for >2 blocks, or on the consensus round number climbing.
5. **Backup the validator key.** `config/priv_validator_key.json` and
   `config/node_key.json` reconstruct the validator identity. Lose them
   → operator slashed (double-sign if a replacement signs from a fresh
   key while the old one is still in someone's hands).

---

## 6. Verifying the install

From any host with shell access to the validator (or its RPC):

```bash
leochaind status | jq '{chain_id: .node_info.network,
                        height: .sync_info.latest_block_height,
                        catching_up: .sync_info.catching_up}'
# chain_id == "leo_chain-1", catching_up == false, height should advance every ~3.5 s

leochaind query blt params         # cluster_count=12, epoch_length_ms=3500
leochaind query blt delegate-set   # 12 entries
leochaind query blt latest-epoch   # NotFound until the first MsgCommitSyncBlock lands
```

The Unity team can validate the wire contract independently with
`scripts/check_unity_rpc.sh http://<host>:26657`.

---

## 7. Verdict on co-locating 12 nodes on this dev box

Based on the brief 12-node trial on the 2 vCPU / 15 GiB / 14 GB-free
host (see Task #15 observations):

- **RAM and process startup**: fine (2 GB peak; ~170 MB/node).
- **CPU**: saturated. The two-vCPU host ran ~108 % combined CPU at idle
  blocks. Adding payload (MsgCommitSyncBlock submissions and member
  table churn) would push block intervals further past the 3.5 s target.
- **Disk**: 14 GB free will fill in **~4–5 days of full-payload
  operation** (3.2 GB/day per node × 12). For an unattended bare-metal
  run this is unsafe.

> **Recommendation**: this box is OK for short integration tests, but
> **not** for an unattended long-running 12-validator setup. For
> bare-metal deployment use either (a) one host per validator on hardware
> matching §1 recommendations, or (b) a single host with **≥ 8 vCPU and
> ≥ 500 GB disk** if you must co-locate.

If you only need a stable demo target for Unity (no real cluster head
mechanics), run **4 nodes** instead of 12: same protocol behavior,
quorum of 3, and fits comfortably on this host.
