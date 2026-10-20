import numpy as np
from geopy.distance import great_circle
from math import sqrt, sin, cos
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import pandas as pd
from function_get_tle import get_sat_from_text
from scipy.spatial import KDTree

import random

import blt_core
import blt_params
import blt_links
import blt_isl

TIME_TICK = 0.001


def _get_or_synthesize_constellation(number_of_sat):
    """Return name/pos/vel/ang_vel lists of length number_of_sat. Pads beyond
    the TLE base by rotating random base satellites around the z-axis so the
    synthetic copies share altitude and inclination distribution."""
    nl, pl, vl, val = get_sat_from_text(number_of_sat)
    base = len(nl)
    if base >= number_of_sat:
        return nl[:number_of_sat], pl[:number_of_sat], vl[:number_of_sat], val[:number_of_sat]
    extra = number_of_sat - base
    rng = np.random.default_rng(42)
    out_n = list(nl)
    out_p = list(pl)
    out_v = list(vl)
    out_a = list(val)
    base_idx = rng.integers(0, base, size=extra)
    thetas = rng.uniform(0, 2 * np.pi, size=extra)
    for k in range(extra):
        bi = int(base_idx[k])
        c = float(np.cos(thetas[k]))
        s = float(np.sin(thetas[k]))
        x, y, z = pl[bi]
        vx, vy, vz = vl[bi]
        out_n.append(f'SYNTH-{k}')
        out_p.append([x * c - y * s, x * s + y * c, z])
        out_v.append([vx * c - vy * s, vx * s + vy * c, vz])
        out_a.append(val[bi])
    return out_n, out_p, out_v, out_a


# Number of KMeans clusters used to lay out cluster-aligned faults; matches the
# simulation k so that "whole faulty clusters" coincide with the BFT voting
# units (cluster heads).
FAULT_CLUSTER_K = 12

# Healthy oscillator frequency spread (Hz at the 40 MHz nominal). The paper
# specifies ~+-1 ppb initial offset; 0.04 Hz / 40 MHz = 1 ppb. A faulty
# oscillator carries this same jitter plus a coherent malfunction_drift_bias of
# a few ppb, which is a moderately degraded part rather than a dead one: the
# datasheet bound on ageing and temperature puts a part that has drifted out of
# specification in that range, and it still runs. Both figures are registry
# entries with their sources (`blt_params.py`).
NORMAL_OSC_STDDEV = blt_params.ppb_to_hz(blt_params.value('osc_healthy_ppb'))


def initialize_satellites(number_of_sat, num_malfunctioning,
                          malfunction_mean=50 * (10 ** 6),
                          malfunction_stddev=10,
                          malfunction_drift_bias=0.0,
                          concentrate_faults=False,
                          cluster_aligned=False,
                          cluster_pick='largest',
                          seed=None):
    """Initialize satellites using the get_sat_tle function and setup additional properties.

    When concentrate_faults=True the faulty satellites are picked as a spatial
    cluster (one random seed + its nearest neighbors) so they fall into a small
    number of KMeans clusters, a prerequisite for BFT outlier exclusion to
    actually exclude anything.
        `seed` makes a run reproducible: it fixes both the oscillator frequency
    draw and the fault placement. Passing the same seed to two algorithms gives
    them byte-identical initial conditions, which is what makes a difference
    between them attributable to mechanism rather than to the draw. None keeps
    the old non-reproducible behaviour.
        `cluster_pick` selects which clusters degrade under cluster_aligned.
    'largest' takes them in size order, which is deterministic, so seeds average
    the oscillator draw and never the fault geometry. 'random' draws the set per
    seed, which is what a comparison across constellation sizes needs; see the
    comment at the branch below.
    """
    rng = np.random.default_rng(seed)

    name_list, pos_list, vel_list, vel_ang_list = _get_or_synthesize_constellation(number_of_sat)

    satellites = []

    # Define normal oscillator mean and standard deviation
    normal_mean = 40 * (10 ** 6)  # Hz
    normal_stddev = NORMAL_OSC_STDDEV  # Hz; NORMAL_OSC_STDDEV/normal_mean = ppb spread

    if cluster_aligned and num_malfunctioning > 0:
        # Whole-cluster placement: the degradation is regionally correlated, so
        # it takes clusters entire rather than sprinkling members. Whole KMeans
        # clusters are consumed, largest first, up to the budget, and any
        # remainder is scattered as a strict minority into the still-healthy
        # clusters so none of those acquires a lying majority.
        #
        # The voting unit is the cluster, not the satellite, so this places the
        # faults on the axis the quorum is defined over: each consumed cluster
        # adds exactly one head that misreports. The scattered-fault placement,
        # selected separately, is the other extreme and tests the local filter
        # instead.
        pos_arr = np.asarray(pos_list, dtype=float)
        clusters = cluster_indices_from_kmeans(pos_arr, FAULT_CLUSTER_K)
        if cluster_pick == 'random':
            # Which clusters degrade is drawn per seed rather than fixed by
            # size. Size order is deterministic, so repeats average only the
            # oscillator draw and never the fault geometry, and since KMeans
            # sizes differ with the constellation size, the degraded set differs
            # between two Ns as well: {1,6,8,11} measured at N=500 against
            # {1,3,4,5} at N=8192. The proposer rotates as round_no % k over a
            # handful of rounds, so those two sets put a different number of
            # unreliable heads into the proposer sequence, and a comparison
            # across N picks that up instead of the size effect it is after.
            #
            # Randomising here leaves the fault model alone: whole clusters
            # still degrade, and their heads still become unreliable *because*
            # their own members did. Selecting faulty heads directly would break
            # that link and model something else entirely, heads misreporting
            # while their members are healthy, which is the adversarial case
            # this work does not claim to address.
            order = [int(c) for c in rng.permutation(len(clusters))]
        elif cluster_pick == 'largest':
            order = sorted(range(len(clusters)), key=lambda c: -len(clusters[c]))
        else:
            raise ValueError("cluster_pick must be 'largest' or 'random', "
                             f"got {cluster_pick!r}")
        chosen = []
        ci = 0
        while ci < len(order) and len(chosen) + len(clusters[order[ci]]) <= num_malfunctioning:
            chosen.extend(int(j) for j in clusters[order[ci]])  # whole cluster -> lies
            ci += 1
        remainder = num_malfunctioning - len(chosen)
        ri = ci
        while remainder > 0 and ri < len(order):
            members = [int(j) for j in clusters[order[ri]]]
            cap = (len(members) - 1) // 2          # keep strictly < half: stays a minority
            take = min(cap, remainder)
            chosen.extend(members[:take])
            remainder -= take
            ri += 1
        if remainder > 0:                          # only if faults exceed minority capacity
            leftover = [int(j) for c in order[ri:] for j in clusters[c]]
            chosen.extend(leftover[:remainder])
        malfunctioning_indices = np.array(chosen, dtype=int)
    elif concentrate_faults and num_malfunctioning > 0:
        pos_arr = np.asarray(pos_list, dtype=float)
        origin = int(rng.integers(number_of_sat))
        d2 = np.sum((pos_arr - pos_arr[origin]) ** 2, axis=1)
        malfunctioning_indices = np.argsort(d2)[:num_malfunctioning]
    else:
        malfunctioning_indices = rng.choice(number_of_sat, num_malfunctioning, replace=False)

    for i in range(number_of_sat):
        # Extract necessary details from the lists
        name = name_list[i]
        pos = pos_list[i]
        velocity = vel_list[i]
        angular_velocity = vel_ang_list[i]
        r = 6806
        pos_lat = np.arcsin(pos_list[i][2] / r) * 180 / np.pi
        pos_lon = np.arctan2(pos_list[i][1], pos_list[i][0]) * 180 / np.pi
        pos_latlon = [pos_lat, pos_lon]

        if i in malfunctioning_indices:
            mean = malfunction_mean
            stddev = malfunction_stddev
            bias = malfunction_drift_bias
        else:
            mean = normal_mean
            stddev = normal_stddev
            bias = 0.0

        # Create satellite dictionary
        satellite = {
            'name': name,
            'position': pos,
            'position_latlon': pos_latlon,
            'velocity': velocity,
            'angular_velocity': angular_velocity,
            'clock': 0,  # Initial clock time, can vary
            'oscillator_mean': mean,  # MHz (assume average frequency)
            'oscillator_stddev': stddev,  # Standard deviation for Gaussian distribution
            'frequency': 0,
            'drift': 0
        }
        satellite['frequency'] = rng.normal(satellite['oscillator_mean'], satellite['oscillator_stddev'])
        # Initial drift based on Gaussian distribution
        satellite['drift'] = satellite['frequency'] / satellite['oscillator_mean'],
        # Coherent frequency offset of a malfunctioning oscillator. drift =
        # freq/mean is zero-mean by construction, so a faulty satellite only
        # jitters around nominal, it never biases its cluster's aggregate,
        # which is what a real off-nominal oscillator does. drift_bias adds
        # that one-directional ppb-scale offset so faulty clusters become
        # clean cross-cluster outliers (Section IV.B "biased measurements").
        satellite['drift_bias'] = bias
        satellites.append(satellite)

    return satellites


def cluster_by_position(satellites, k):
    """Partition the satellites by position with k-means.

    Sizes are whatever the geometry gives; nothing constrains them to be
    equal. At N = 8,192 in 12 clusters a partition runs from about 450 to
    about 810 members, averaging 683.
    """
    positions = np.array([sat['position'] for sat in satellites])
    scaler = StandardScaler()
    scaled_positions = scaler.fit_transform(positions)

    kmeans = KMeans(n_clusters=k, n_init=10, random_state=42)
    kmeans.fit(scaled_positions)

    for i, cluster in enumerate(kmeans.labels_):
        satellites[i]['cluster'] = cluster


def sync_with_neighbor(satellites, neighbors, mean_freq=40 * (10**6)):
    """Synchronize each satellite's clock with its nearest 1-hop neighbor with a frequency closest to the mean."""
    for i, neighbor_idxs in neighbors.items():
        if neighbor_idxs:
            closest_neighbor = min(neighbor_idxs, key=lambda idx: abs(satellites[idx]['frequency'] - mean_freq))
            satellites[i]['clock'] += (satellites[closest_neighbor]['clock'] - satellites[i]['clock']) / 2


# =============================================================================
# Vectorized helpers (numpy-based hot paths)
# =============================================================================

def _extract_arrays(satellites):
    positions = np.array([s['position'] for s in satellites], dtype=float)
    velocities = np.array([s['velocity'] for s in satellites], dtype=float)
    ang_vels = np.array([s['angular_velocity'] for s in satellites], dtype=float)
    drifts = np.array([s['drift'][0] for s in satellites], dtype=float)
    drift_bias = np.array([s.get('drift_bias', 0.0) for s in satellites], dtype=float)
    drifts = drifts + drift_bias
    frequencies = np.array([s['frequency'] for s in satellites], dtype=float)
    clocks = np.array([s['clock'] for s in satellites], dtype=float)
    return positions, velocities, ang_vels, drifts, frequencies, clocks


def compute_neighbors_fast(positions, range_limit=2500.0):
    """KDTree query_ball_point, replaces O(N^2) great_circle pair loop.

    LEO satellites at the same altitude have chord ≈ great-circle within 0.1%
    over a 2500 km range, so 3D Euclidean distance is sufficient.
    """
    tree = KDTree(positions)
    pairs = tree.query_ball_point(positions, r=range_limit)
    return {i: [j for j in pairs[i] if j != i] for i in range(len(positions))}


def _labels_from_clusters(n, cluster_idx_list):
    labels = np.empty(n, dtype=int)
    for ci, idxs in enumerate(cluster_idx_list):
        labels[idxs] = ci
    return labels


def compute_best_neighbor_array(positions, frequencies, range_limit=2500.0,
                                mean_freq=40 * (10 ** 6), labels=None):
    """Per-satellite index of the neighbor with frequency closest to mean_freq.

    Frequencies are static after init, so this can be precomputed once per
    neighbor refresh and reused on every sync call (eliminates the Python loop
    inside sync_with_neighbor at large N).

    When ``labels`` (per-satellite KMeans cluster id) is given, neighbour
    candidates are restricted to the satellite's OWN cluster. This removes the
    cross-cluster peer-averaging "bridge": without it, spatial neighbours that
    straddle cluster boundaries diffuse one cluster's value into the next, so
    the constellation globally aligns through neighbour sync alone and ATS ends
    up as tight as BLT. Intra-cluster sync leaves the global gap to the
    cluster-level mechanism (BLT's BFT consensus vs ATS's non-consensus
    reconcile), which is the point of panel (a).
    """
    tree = KDTree(positions)
    pairs = tree.query_ball_point(positions, r=range_limit)
    n = len(positions)
    best = np.arange(n, dtype=np.int64)
    freq_dev = np.abs(frequencies - mean_freq)
    for i in range(n):
        nbrs = [j for j in pairs[i]
                if j != i and (labels is None or labels[j] == labels[i])]
        if nbrs:
            best[i] = nbrs[int(np.argmin(freq_dev[nbrs]))]
    return best


def sync_with_neighbor_pre(clocks, best, rng=None):
    """One two-way exchange per satellite with its most stable neighbour.

    The measured offset carries the two-way transfer error (blt_links): two
    timestamps and the residual path asymmetry. It enters the measurement, so a
    protocol that averages many exchanges can average it down, adding it to
    the result afterwards would not have that property.
    """
    measured = (clocks[best] - clocks) + blt_links.twoway_noise(clocks.shape, rng)
    clocks += measured / 2


def update_positions_vec(positions, velocities, ang_vels, time_units):
    """Advance each satellite along its circular orbit by one update interval.

    For circular motion at angular rate omega,
        r(t) = r0 * cos(omega t) + (v0 / omega) * sin(omega t)
    The v0/omega term is what converts the velocity (km/s) into the length
    units the position carries; |v|/omega equals the orbital radius to within
    0.02% for this constellation, which is the check that the two terms are
    commensurate.

    Both terms must be carried and the angle must be in radians: dropping the
    1/omega factor mixes km/s into a position in km, and degrees in place of
    radians scales every position by a constant below one on each update, which
    walks the constellation toward the Earth's centre and dissolves the
    neighbour topology the protocols run on.
    """
    theta = ang_vels * time_units * TIME_TICK          # radians
    c = np.cos(theta)[:, None]
    s = np.sin(theta)[:, None]
    # A zero angular rate would be a degenerate (non-orbiting) entry; leave such
    # a satellite where it is rather than dividing by zero.
    omega = np.where(ang_vels == 0.0, 1.0, ang_vels)[:, None]
    radial = np.where(ang_vels[:, None] == 0.0, 0.0, velocities / omega)
    return positions * c + radial * s


# Freeze the FTSP neighbour graph. Recomputing it reshuffles the flood BFS
# tree on an arbitrary tie-break, which steps the FTSP band at every update;
# over a ~30 s snapshot the topology is essentially static anyway.
FTSP_STATIC_GRAPH = False

# Coherent per-hop skew rate that a *faulty* relay stamps into the flood. A
# malfunctioning node mis-timestamps far worse than its steady clock bias
# implies, and concentrate_faults keeps healthy relays on most paths, so
# without this the by-hop signal barely moves. Module level for sweeping.
# It reaches the result only as skew x hop delay, which at this value over an
# 8.4 ms hop is well under a nanosecond.
FTSP_FAULT_SKEW = 1.0e-7


def flood_time_sync_multihop(positions, neighbors, skew_rate, reference_idx,
                             hop_delay=None, rng=None, faulty_relay=None, links=None):
    """Multi-hop flood with per-hop error accumulation (FTSP).

    The reference time is relayed node-to-node along the ISL graph by BFS. Each
    relay contributes two independent error terms, and a node h hops away
    inherits the sum of both along its path:

    1. **Staleness** ``skew_rate[relay] * hop_delay``, the relay's own clock
       has drifted since it last synced. Systematic, so it adds linearly.
       Sub-picosecond at realistic link delays; kept because it is real, not
       because it matters.

    2. **One-way transfer error** ``N(0, blt_links.oneway_sigma_s())``, the
       term that actually makes flooding worse than two-way exchange. A one-way
       message carries clock offset and propagation delay summed together and
       the protocol cannot separate them, so the range-prediction residual
       survives in full. Independent per hop, so it accumulates as a random
       walk and the error grows as sqrt(h). See blt_links for the budget.

    ``hop_delay`` defaults to the physical per-link latency (range/c plus relay
    processing) computed from the actual link length. Satellites in a disconnected component never receive the flood and
    are returned as NaN.
    """
    sigma = blt_links.oneway_sigma_s()
    mis_stamp = blt_params.value('faulty_relay_timestamp_error_s')
    n = len(positions)
    received_offset = np.full(n, np.nan)
    received_offset[reference_idx] = 0.0
    visited = np.zeros(n, dtype=bool)
    visited[reference_idx] = True
    current = [reference_idx]
    while current:
        nxt = []
        for relay in current:
            for nbr in neighbors[relay]:
                if visited[nbr]:
                    continue
                if links is not None and not links.flood_delivers(relay, nbr):
                    continue   # lost; another relay in this layer or the next may deliver
                visited[nbr] = True
                # Physical latency of *this* link, not a constant.
                link_km = float(np.linalg.norm(positions[nbr] - positions[relay]))
                delay = blt_links.hop_delay_s(link_km)
                stale = skew_rate[relay] * delay
                noise = rng.normal(0.0, sigma) if (rng is not None and sigma > 0) else 0.0
                if rng is not None and (MEAS_OUTLIER_P > 0.0 or _MEAS['biased'] is not None):
                    noise += float(_measurement_faults(np.array([relay]), rng)[0])
                # A malfunctioning relay mis-STAMPS. This is the fault channel
                # that actually reaches the result: routing the fault through a
                # larger frequency skew (the previous model) made it invisible,
                # because skew only enters as skew * hop_delay, which is
                # sub-picosecond at real link delays. Coherent in sign, so every
                # downstream path inherits it in the same direction.
                bad = mis_stamp if (faulty_relay is not None and faulty_relay[relay]) else 0.0
                received_offset[nbr] = received_offset[relay] + stale + noise + bad
                nxt.append(nbr)
        current = nxt
    return received_offset


def _ftsp_skew_rate(satellites, drifts):
    """Per-node by-hop skew rate for the FTSP flood: healthy nodes contribute
    their small clock deviation (drift - 1), faulty nodes the larger coherent
    FTSP_FAULT_SKEW, since a malfunctioning relay grossly mis-timestamps."""
    skew = drifts - 1.0
    is_faulty = np.array([s.get('drift_bias', 0.0) != 0.0 for s in satellites])
    skew[is_faulty] = FTSP_FAULT_SKEW
    return skew


def cluster_indices_from_kmeans(positions, k):
    scaler = StandardScaler()
    scaled = scaler.fit_transform(positions)
    km = KMeans(n_clusters=k, n_init=10, random_state=42)
    km.fit(scaled)
    labels = km.labels_
    return [np.where(labels == c)[0] for c in range(k)]


# Re-clustering after a position update. The published engine re-runs KMeans from
# scratch, which can redraw the partition even though the satellites moved only a
# few hundred km, and split one degraded region across two clusters. With
# CLUSTER_WARM_START the new KMeans starts from the previous clusters' centroids
# (recomputed at the new positions), so the partition follows the motion and each
# cluster keeps its index. Off = the published behaviour, bit-identical.
CLUSTER_WARM_START = False


def recluster(positions, k, previous=None):
    if not CLUSTER_WARM_START or previous is None or any(len(idx) == 0 for idx in previous):
        return cluster_indices_from_kmeans(positions, k)
    scaled = StandardScaler().fit_transform(positions)
    init = np.array([scaled[idx].mean(axis=0) for idx in previous])
    km = KMeans(n_clusters=k, init=init, n_init=1)
    km.fit(scaled)
    return [np.where(km.labels_ == c)[0] for c in range(k)]


# --- Inter-cluster propagation (shared by ATS and BLT global phases) ---------
# The global phase is NOT an instantaneous broadcast: cluster heads are far
# apart and reconcile over a multi-hop head network, so per hop a relay head
# adds its own clock skew (healthy ~1 ppb, a faulty head its drift bias). This
# is the same by-hop physics FTSP suffers, but over the shorter hierarchical
# head graph instead of a flat constellation-wide flood, which is exactly why
# the hierarchy is cheaper/more accurate than flooding.
# Derived, not chosen: two heads with a link are within isl_range_km of each
# other, so the hop costs that range over c plus one store-and-forward.
INTERCLUSTER_HOP_DELAY = blt_params.intercluster_hop_delay()


def cluster_head_graph(positions, cluster_idx_list, n_links=3):
    """Head = member nearest the cluster centroid; head adjacency = the n_links
    nearest heads (a connected multi-hop head network)."""
    heads = []
    for idxs in cluster_idx_list:
        c = positions[idxs]
        centroid = c.mean(axis=0)
        heads.append(int(idxs[np.argmin(((c - centroid) ** 2).sum(axis=1))]))
    hpos = positions[np.array(heads)]
    K = len(heads)
    d2 = ((hpos[:, None, :] - hpos[None, :, :]) ** 2).sum(-1)
    nbr = {i: [int(j) for j in np.argsort(d2[i])[1:n_links + 1]] for i in range(K)}
    return heads, nbr


def headnet_byhop(nbr, head_skew, hop_delay, coordinator=0, head_positions=None):
    """BFS over the head graph; each cluster inherits the relay skew accumulated
    along its path.

    `head_positions` makes the per-hop latency physical: propagation over the
    actual head-to-head link plus store-and-forward, via blt_links.hop_delay_s.
    Without it the scalar `hop_delay` applies to every link uniformly, at the
    worst-case value two linked heads can be apart, which is what
    blt_params.intercluster_hop_delay() computes from the ISL range. Either way
    the number comes from the geometry rather than from a choice.
    """
    K = len(nbr)
    off = np.zeros(K)
    visited = np.zeros(K, dtype=bool)
    visited[coordinator] = True
    cur = [coordinator]
    while cur:
        nxt = []
        for r in cur:
            for nb in nbr[r]:
                if visited[nb]:
                    continue
                visited[nb] = True
                if head_positions is not None:
                    link_km = float(np.linalg.norm(head_positions[nb] - head_positions[r]))
                    d = blt_links.hop_delay_s(link_km)
                else:
                    d = hop_delay
                off[nb] = off[r] + head_skew[r] * d
                nxt.append(nb)
        cur = nxt
    return off


def sync_with_cluster_vec(clocks, cluster_idx_list, drift_step=None,
                          window=None, rng=None, reach=None, noise_rng=None, hops=None):
    """ATS local (intra-cluster) phase: plain mean aggregation.

    Carries the same collection window as the BLT local phase, for the same
    reason: ATS heads poll their members too. Applying the window to only one
    of them would charge that one for a cost both incur.
    """
    if window is None:
        window = LOCAL_COLLECT_WINDOW
    for idxs in cluster_idx_list:
        if reach is not None:
            idxs = idxs[reach[idxs]]   # members whose exchange got through
        c = clocks[idxs]
        if window > 0 and drift_step is not None:
            c = c - drift_step[idxs] * _staleness(len(idxs), window, rng)
        if noise_rng is not None:
            noise = _member_noise(len(clocks), idxs, hops, noise_rng)
            # Estimates carry noise; each member keeps its own as a residual.
            clocks[idxs] = (c + noise).mean() - noise
        else:
            clocks[idxs] = c.mean()


# BC global (cross-cluster) sync interval in ticks. Shorter resets faulty
# clocks to the consensus value more often, so their coherent bias accumulates
# over a smaller window and the pre-cliff flat band stays under the 10 ns ISL
# line. Module level so the Fig.5b harness can sweep it.
BC_CLUSTER_CYCLE = 2000

# Fraction of cluster heads that must stay trustworthy for the global BFT
# consensus to commit. The cliff sits where the faulty fraction makes the
# trustworthy heads drop below this. Loosening it (e.g. 2/3) lets BLT-SAND hold
# the consensus past a higher fault ratio, pushing the cliff to the right.
# Two thirds of the heads, counted as ceil(2n/3), 8 of 12. An honest proposal
# is then backed by every honest head, so it commits while wrong heads are at
# most n - ceil(2n/3) = 4, and a wrong proposal needs 8 of them, so it never
# commits below that. 4 of 12 is the 1/3 bound the paper states.
#
# A Byzantine quorum has to satisfy both 2q - n > f (two quorums share an honest
# node) and q <= n - f (the honest nodes can form one). At n = 12 that gives
# q = 8 for f = 3 and no solution for f = 4, which is the n >= 3f+1 bound. So 8
# is the correct Byzantine quorum here for three faults, not a relaxed one.
#
# Tolerating a fourth rests on the fault model, which is benign: a degraded head
# reports a wrong value but follows the protocol and does not equivocate, so the
# requirement is only that liars cannot reach 8 and honest heads can, and both
# hold at f = 4. CometBFT instead commits on more than 2/3 of voting power, 9 of
# 12, and the chain runs that rule unmodified. See BLT_bft_chain/readme.md.
BC_QUORUM = 2 / 3

# Two-phase synchronization cycles (paper Section II.B/C): a frequent LOCAL
# intra-cluster phase suppresses short-term drift, and a less-frequent GLOBAL
# inter-cluster phase removes accumulated cross-cluster discrepancy. Periods
# are set so total message volume is comparable across FTSP/ATS/BLT.
ATS_LOCAL_CYCLE = 200
ATS_GLOBAL_CYCLE = 1500
BC_LOCAL_CYCLE = 200
# BC global inter-cluster (h-PBFT) cycle is BC_CLUSTER_CYCLE above.

# ATS has no consensus: its global phase is a plain multi-hop reconciliation
# among cluster heads that only *partially* equalizes per round (distributed
# averaging converges slowly and is dragged by faulty heads, with no validated
# single value). alpha is the per-round reconciliation strength; (1-alpha) of
# the inter-cluster spread survives each global round. BLT instead reaches a
# single agreed value via h-PBFT and aligns fully (alpha = 1) when quorum holds.
ATS_RECONCILE_ALPHA = 0.5

# h-PBFT agreement tolerance (seconds): two cluster heads are considered to
# agree on the timing state if their references differ by less than this. Set
# above the residual spread among healthy heads but below a faulty head's
# bias-driven offset, so healthy heads form a supermajority while faulty heads
# fall outside it. The value is computed at 3 sigma of the healthy spread
# (blt_params.agree_tol_s).
BC_AGREE_TOL = 3.0e-8

# Anomalous faulty-reading error. A degraded node is NOT malicious, it tries
# to report correctly but, on top of its small steady oscillator drift, suffers
# sensor noise / faulty readings / link disruptions (paper Sec. II.C) that make
# the value it reports in the global phase wrong by a comparatively large,
# erratic amount. This anomalous component (not the small steady drift) is what
# the global phase consumes, and it drives the inter-protocol difference: ATS
# averages it in and FTSP relays it (no anomaly filtering) so both are
# corrupted, while BLT's cluster head rejects it as a robust-statistics outlier
# and never folds it into the committed value. Being a large outlier makes the
# rejection clean and the 1/3 cliff sharp, decoupled from BLT's propagation
# baseline.
FAULTY_REPORT_ERROR = 6.0e-8

# Lightweight diagnostics for the h-PBFT gate (commit/skip/flagged-per-call).
BC_DIAG = {'commit': 0, 'skip': 0, 'bad_commit': 0, 'flagged': [],
           'honest_spread': []}

# What a round that fails to reach quorum does.
#
# Off: the global step is skipped, so the constellation gets no inter-cluster
# correction that round.
#
# On: nothing is written to the ledger, and the heads still reconcile toward
# the median of what they heard. That is the correction the same hierarchy
# would make with no consensus at all, so an arm using it isolates what the
# vote adds rather than what losing the global step costs. The head-fault axis,
# the correlated-fault runs and the ablation ladder turn it on; everything else
# leaves it off.
FAILED_ROUND_FALLBACK = False


# Correlation of the reported error across faulty cluster heads.
#
# The faults here are not adversarial: a satellite whose oscillator degrades is
# still trying to report the truth. But degradation is not independent either.
# OCXO frequency has a large temperature coefficient and satellites in the same
# orbital plane share an eclipse cycle; a production batch shares an aging law;
# similar altitude and inclination means similar accumulated radiation dose. All
# of these push a whole group of oscillators the SAME way at the same time, with
# no malice anywhere. Correlated benign drift produces the signature of
# collusion without a colluder.
#
# It differs from Byzantine collusion in one way that matters: a degraded head
# reports the same wrong value to everybody. It is consistent but wrong, not
# inconsistent. Equivocation, telling different peers different things, is
# what PBFT's prepare/commit rounds and view changes exist to defeat, and it
# cannot arise here. What can arise is a correlated group setting network time,
# and that is what a quorum is actually buying.
#
# None keeps the historic injection (every faulty head offset by exactly
# +FAULTY_REPORT_ERROR), which is the fully-correlated case with a fixed sign.
# A float in [0, 1] selects the stochastic model: each faulty head's error is
#     E * (sqrt(rho) * g + sqrt(1 - rho) * h_i)
# with g drawn once per round and h_i per head, giving unit-variance errors of
# scale E and pairwise correlation rho. rho=0 is independent degradation, rho=1
# is a whole group stressed together.
FAULT_CORRELATION = None


def faulty_report_offsets(liar_mask, magnitude, rng, correlation=None):
    """Reported-error offset for each cluster head, in seconds."""
    if correlation is None:
        return np.where(liar_mask, magnitude, 0.0)
    rho = float(np.clip(correlation, 0.0, 1.0))
    n = len(liar_mask)
    common = rng.standard_normal()
    individual = rng.standard_normal(n)
    err = magnitude * (np.sqrt(rho) * common + np.sqrt(1.0 - rho) * individual)
    return np.where(liar_mask, err, 0.0)


def sync_with_cluster_bc_vec(clocks, cluster_idx_list, positions, skew_rate,
                             is_faulty, within_k=3.0, quorum=None, agree_tol=None,
                             faulty_head=None, round_no=0, require_quorum=True,
                             report_rng=None, head_reach=None):
    """BLT-SAND global inter-cluster phase = hierarchical PBFT consensus.

    Each cluster head reports a robust cluster reference (median after a MAD
    trim, so a few faulty members inside a cluster do not poison it). The heads
    then run a PBFT-style agreement: a block (global reference time) commits
    only if a supermajority (``quorum``) of heads agree on it, i.e. their
    references lie within ``agree_tol`` of the proposed value.

    Healthy heads stay mutually aligned (within agree_tol); a faulty head's
    bias pushes its reference outside the agreement window. So while faulty
    heads are below 1 - quorum of the constellation, the healthy supermajority
    commits a clean reference and all satellites adopt it. Once faulty heads
    exceed that bound, no value gathers a supermajority, the consensus fails to
    commit, and the constellation loses its global anchor, clusters then drift
    apart and RMSE climbs sharply. This is the h-PBFT 1/3 cliff, and unlike a
    MAD-outlier gate it does not break down as the faulty fraction grows.
    """
    if quorum is None:
        quorum = BC_QUORUM
    if agree_tol is None:
        agree_tol = BC_AGREE_TOL

    cluster_avgs = np.empty(len(cluster_idx_list))
    for ci, idxs in enumerate(cluster_idx_list):
        c = clocks[idxs]
        med = np.median(c)
        mad = np.median(np.abs(c - med))
        threshold = max(within_k * 1.4826 * mad, 1e-18)
        valid = np.abs(c - med) <= threshold
        cluster_avgs[ci] = np.median(c[valid]) if valid.any() else med

    # A degraded head reports a wrong value, and the vote sees the reported
    # values, which is all a validator has. What commits is the proposal the
    # quorum approved, not an aggregate over the voters, so a value only
    # becomes the network's time if enough heads independently matched it
    # against their own reference.
    #
    # Which heads misreport is an explicit input (blt_core.head_fault_mask),
    # kept separate from the member fault ratio so that validator integrity is
    # not tied to member oscillator health.
    reported = cluster_avgs.copy()
    if HEAD_FAULT in ('own', 'both') and faulty_head is None:
        liar = is_faulty[select_heads(positions, cluster_idx_list, HEAD_POLICY == 'history')]
        if HEAD_FAULT == 'both':
            liar = liar | blt_core.head_fault_mask(cluster_idx_list, is_faulty)
    else:
        liar = blt_core.head_fault_mask(cluster_idx_list, is_faulty, explicit=faulty_head)
    BC_DIAG.setdefault('liars', []).append(int(np.sum(liar)))
    if report_rng is None:
        report_rng = np.random.default_rng(round_no)
    reported += faulty_report_offsets(liar, FAULTY_REPORT_ERROR, report_rng,
                                      FAULT_CORRELATION)

    # ---- PBFT-style vote ---------------------------------------------------
    #
    # A vote, not a spread test. Taking the median of the reported values and
    # committing when enough of them sit near it would measure agreement rather
    # than consent, and agreement is exactly what a correlated set of degraded
    # heads has: the more of them report alike, the more such a test is
    # satisfied. A BFT round instead has a proposer and voters:
    #
    #   1. the proposer for this round is fixed by rotation, not chosen by the
    #      values, so liars cannot move the candidate by lying harder;
    #   2. every head votes for the proposal only if it matches that head's own
    #      reference within agree_tol;
    #   3. the value commits iff at least `quorum` of the heads voted for it;
    #   4. the committed value IS the proposal, no aggregate over the voters,
    #      so nothing enters the result that the network did not vote on.
    #
    # With f liars out of N and quorum q, an honest proposer is backed only by
    # the N-f honest heads, and a Byzantine proposer only by the f liars. So the
    # round commits an honest value while f <= (1-q)N, commits nothing in
    # between, and commits a lie only once f >= qN. At a 2/3 quorum those bounds
    # are N/3 and 2N/3: the 1/3 fault bound is then a
    # consequence of the protocol rather than an assertion about it.
    #
    # Simplification: a failed round is skipped rather than triggering a view
    # change, so liveness is lost for that round instead of being retried.
    n_heads = len(cluster_avgs)
    proposer = int(round_no) % n_heads
    proposal = float(reported[proposer])

    votes = np.abs(reported - proposal) <= agree_tol
    if head_reach is not None:
        # A head the proposal did not reach casts no vote. The quorum is still
        # counted over all N heads, the validator set is fixed per height, so
        # an unreachable head is an absent vote, not a smaller denominator.
        votes &= head_reach
    needed = int(np.ceil(quorum * n_heads))
    BC_DIAG['flagged'].append(int(n_heads - votes.sum()))

    # Spread among the heads that are NOT lying, recorded because the agreement
    # window is derived with no dependence on cluster size, agree_tol is
    # sigmas x osc_healthy_ppb x bc_local_cycle, while the measured number of
    # honest heads falling outside it doubles between N=500 and N=8192. If this
    # spread grows with cluster size, the window needs a size term and the
    # derivation is incomplete; if it does not, the extra no-votes come from
    # somewhere else. Either way the vote should not be unobservable.
    honest = ~liar
    if honest.sum() > 1:
        BC_DIAG['honest_spread'].append(
            float(reported[honest].max() - reported[honest].min()))

    # One row per round for the cross-cluster check table: was the proposer lying,
    # how many heads voted for it, and did it commit. Diagnostics only.
    BC_DIAG.setdefault('rounds', []).append(
        (bool(liar[proposer]), int(votes.sum()), int(liar.sum()),
         bool(votes.sum() >= needed or not require_quorum)))

    if require_quorum and votes.sum() < needed:
        BC_DIAG['skip'] += 1
        if not FAILED_ROUND_FALLBACK:
            return  # no quorum backs the proposal: this round commits nothing
        # Fallback: the round commits nothing, but the heads can still reconcile
        # toward the MEDIAN of what was reported. A median needs no agreement --
        # every head computes it from the same reports, and it is the same
        # robust aggregate the local phase already uses, so this is the floor the
        # hierarchy provides without consensus. Nothing is written to the ledger
        # and no head is excluded by a vote, so what is lost past the quorum is
        # the guarantee, not the accuracy.
        #
        # The median, because the fallback has to isolate what losing the
        # quorum costs. A mean takes every wrong report at full weight, so an
        # arm using it would score worse than the no-consensus baseline and the
        # difference would be the estimator rather than the missing vote.
        BC_DIAG['fallback'] = BC_DIAG.get('fallback', 0) + 1
        heard = np.ones(n_heads, dtype=bool) if head_reach is None else head_reach
        if not heard.any():
            return
        g = float(np.median(reported[heard]))
        honest_refs = cluster_avgs[~liar] if (~liar).any() else cluster_avgs
        BC_DIAG.setdefault('ref_err', []).append(abs(g - float(np.mean(honest_refs))))
        heads, nbr = cluster_head_graph(positions, cluster_idx_list)
        off = headnet_byhop(nbr, skew_rate[np.array(heads)], INTERCLUSTER_HOP_DELAY,
                            head_positions=positions[np.array(heads)])
        for ci, idxs in enumerate(cluster_idx_list):
            if heard[ci]:
                clocks[idxs] += ATS_RECONCILE_ALPHA * (g + off[ci] - cluster_avgs[ci])
        return

    # require_quorum=False is the "consensus removed" arm of the ablation. The
    # proposal is distributed unconditionally, same proposer, same value, same
    # head network, same correction strength, so what the comparison isolates
    # is the vote itself and not a different aggregate or a different gain.

    BC_DIAG['commit'] += 1
    # How far the reference the network just adopted sits from the one the clusters that
    # did NOT lie actually keep. A relative RMSE cannot see this: the commit shifts every
    # cluster by the same amount, so the satellites stay aligned with each other while
    # the whole constellation moves. This is what a vote buys, measured in the same
    # units, and it is a deviation from the honest cluster references, not from UTC.
    honest_refs = cluster_avgs[~liar] if (~liar).any() else cluster_avgs
    BC_DIAG.setdefault('ref_err', []).append(abs(float(proposal) - float(np.mean(honest_refs))))
    applied = np.ones(n_heads, dtype=bool) if head_reach is None else head_reach
    if liar[proposer]:
        # Safety violation: a lie carried a quorum. Counted separately because
        # "a value committed" and "a correct value committed" are different
        # claims, and only the second one supports a fault-tolerance result.
        BC_DIAG['bad_commit'] += 1
    global_avg = proposal

    heads, nbr = cluster_head_graph(positions, cluster_idx_list)
    head_skew = skew_rate[np.array(heads)]
    off = headnet_byhop(nbr, head_skew, INTERCLUSTER_HOP_DELAY,
                        head_positions=positions[np.array(heads)])
    for ci, idxs in enumerate(cluster_idx_list):
        if not applied[ci]:   # a cluster the commit did not reach keeps its clocks
            continue
        if LOCAL_MEASUREMENT_NOISE:
            clocks[idxs] += global_avg + off[ci] - cluster_avgs[ci]
        else:
            clocks[idxs] = global_avg + off[ci]


# Ticks over which a cluster head collects its members' offsets. 0 reads every
# member's clock at one instant.
#
# That instant does not exist in the design: 683 members at an 8 ms round trip
# is a 5.2 s collection cycle, so the earliest measurement is that old by the
# time the head builds a reference from it, and a member drifting at 1 ppb
# contributes up to 5.2 ns of error for no reason but when its turn came. The
# term applies to BLT and ATS, which both aggregate inside a cluster, and not
# to FTSP, which floods one reference hop by hop with no collection step.
#
# Turning it on does not move BLT and improves ATS, because a median ignores a
# perturbation that is symmetric about the centre and uncorrelated with the
# values, while a mean is pulled by outliers and staleness understates a fast
# drifter: a member polled seconds ago reports a value that much less advanced.
# The default is 0 so the effect is not folded silently into a headline, and
# the option stays because the staleness is physically real and worth being
# able to switch on.
LOCAL_COLLECT_WINDOW = 0


def _staleness(n, window, rng):
    """Age of each member's measurement when the reference is applied.

    Uniform over the collection window: members are polled in some order and
    nothing in the design privileges a position in that order, so the ages
    spread evenly rather than concentrating.
    """
    if rng is None:
        rng = np.random.default_rng(0)
    return rng.uniform(0.0, window, size=n)


def sync_local_robust(clocks, cluster_idx_list, within_k=3.0,
                      drift_step=None, window=None, rng=None, reach=None,
                      noise_rng=None, hops=None):
    """BLT local (intra-cluster) phase: each cluster head aggregates members
    into a robust reference (median after a MAD trim) and aligns its members
    to it. Robust so a few faulty members inside an otherwise-healthy cluster
    do not poison the cluster reference.

    With a collection window the head aggregates what each member reported when
    it was polled, not what its clock reads now. The correction is therefore
    built from stale data, and because each cluster draws its own ages the bias
    differs between clusters, which is inter-cluster spread for the global
    phase to remove.

    ``reach`` (blt_isl) marks the members whose exchange with the head got
    through this round. A member that was not heard is neither counted nor
    corrected; it keeps drifting until a later round reaches it.
    """
    if window is None:
        window = LOCAL_COLLECT_WINDOW
    for idxs in cluster_idx_list:
        if reach is not None:
            idxs = idxs[reach[idxs]]
        c = clocks[idxs]
        if window > 0 and drift_step is not None:
            # Back-date each member's clock to the moment it was polled.
            c = c - drift_step[idxs] * _staleness(len(idxs), window, rng)
        noise = _member_noise(len(clocks), idxs, hops, noise_rng) if noise_rng is not None else 0.0
        c = c + noise
        med = np.median(c)
        mad = np.median(np.abs(c - med))
        threshold = max(within_k * 1.4826 * mad, 1e-18)
        valid = np.abs(c - med) <= threshold
        ref = np.median(c[valid]) if valid.any() else med
        if _LEDGER['score'] is not None:
            resid = np.abs(c - ref)
            if LEDGER_MEMORY == 'all':
                n = _LEDGER['count'][idxs]
                _LEDGER['score'][idxs] = (_LEDGER['score'][idxs] * n + resid) / (n + 1)
                _LEDGER['count'][idxs] = n + 1
            else:
                _LEDGER['score'][idxs] = (LEDGER_DECAY * _LEDGER['score'][idxs]
                                          + (1 - LEDGER_DECAY) * resid)
        if LOCAL_SKIP_FLAGGED and noise_rng is not None:
            # A member whose reported offset the filter flagged is not corrected
            # with that report; it keeps its clock and is measured again next round.
            clocks[idxs[valid]] = ref - noise[valid]
        else:
            clocks[idxs] = ref - noise


def sync_global_ats(clocks, cluster_idx_list, positions, skew_rate, is_faulty,
                    alpha=None, faulty_head=None, head_reach=None):
    """ATS global (inter-cluster) phase: cluster heads reconcile by gossip over
    the multi-hop head network, no consensus, no verification. A Byzantine
    (majority-faulty) head reports a lied value (FAULTY_REPORT_ERROR); with no signed
    block or BFT vote to reject it, the lie enters the local reconciliation and
    spreads to nearby heads, plus healthy by-hop propagation error. The
    resulting residual inter-cluster spread grows with the number of liars."""
    if alpha is None:
        alpha = ATS_RECONCILE_ALPHA
    refs = np.array([clocks[idxs].mean() for idxs in cluster_idx_list])
    heard = np.ones(len(refs), dtype=bool) if head_reach is None else head_reach
    g = float(refs[heard].mean())  # global reconcile target
    heads, nbr = cluster_head_graph(positions, cluster_idx_list)
    off = headnet_byhop(nbr, skew_rate[np.array(heads)], INTERCLUSTER_HOP_DELAY,
                        head_positions=positions[np.array(heads)])
    # Reconcile every cluster toward the global value with healthy by-hop
    # residual. A degraded cluster's anomalous report is neither verified nor
    # excluded, since ATS has no mechanism for either, so it enters the mean
    # and pulls the reconciliation off by itself.
    for ci, idxs in enumerate(cluster_idx_list):
        if not heard[ci]:
            continue
        clocks[idxs] += alpha * (g + off[ci] - refs[ci])


def measure_sync_performance_vec(clocks, normal_mask=None):
    """Per-tick synchronization error. See blt_core.sync_error for the metric
    and reference definitions.

    Returns a SyncError namedtuple whose first two positions are the historic
    (mean_abs_dev, max_abs_dev) pair, so callers indexing [0]/[1] are
    unaffected; RMSE is available as .rmse_all / .rmse_normal.
    """
    return blt_core.sync_error(clocks, normal_mask=normal_mask)


# FTSP re-flood period [ticks]. 750 ticks is 0.45 s, which re-floods 7.3x more
# often than BLT-SAND commits its global round; that is the end of the range
# that suits FTSP, since frequent re-flooding is what gives each relay a fresh
# reference. Named here rather than left as a literal inside simulate_ftsp, so
# it appears in the profile and in the sensitivity sweep.
FTSP_FLOOD_CYCLE = 750

# Distance-dependent ISL availability (blt_isl). Off here and turned on by the
# adopted configuration (`blt_config.py`); off is the contrast arm, a perfect
# link anywhere inside the 2,500 km range. It draws from its own random stream,
# so leaving it off reproduces a run made without it bit for bit. On, exchanges
# fail with range, routes to the head go over relays, and ISL_DIAG holds the
# loss rates of the last run.
ISL_LINK_MODEL = False
ISL_OVERRIDES = None   # parameter overrides for the link model, e.g. a jitter sweep
ISL_DIAG = {}


# Two-way timestamp noise on every member-to-head exchange, accumulated over the
# relay hops of the route (sqrt(hops) x blt_links.twoway_sigma_s()). Off here
# and turned on by the adopted configuration; off means the local phase reads
# every member's clock exactly, leaving drift between rounds as the only floor
# under BLT and ATS. With it on, a member
# corrects its clock by a noisy estimate and keeps that noise as its residual,
# the cluster reference averages it away over hundreds of members, and a global
# commit SHIFTS each cluster instead of overwriting every clock with one value
# (overwriting would erase the member residuals the physics just created).
LOCAL_MEASUREMENT_NOISE = False


# Faulty measurements (the third fault category), applied to every protocol's
# exchanges alike. Off by default. MEAS_OUTLIER_P is the chance that one exchange
# returns an offset wrong by +/-MEAS_OUTLIER_S; MEAS_BIAS_FRAC of the satellites
# carry a persistent timing bias MEAS_BIAS_S on everything they measure or relay
# (e.g. an uncalibrated hardware delay). Member exchanges need
# LOCAL_MEASUREMENT_NOISE on; FTSP relays apply them per hop.
MEAS_OUTLIER_P = 0.0
MEAS_OUTLIER_S = 0.0
MEAS_BIAS_FRAC = 0.0
MEAS_BIAS_S = 0.0
_MEAS = {'biased': None}


def _measurement_setup(n, sim_seed):
    """Choose the biased satellites for one run, from their own random stream."""
    if MEAS_BIAS_FRAC > 0.0:
        rng = np.random.default_rng((sim_seed or 0) + 6007)
        _MEAS['biased'] = rng.random(n) < MEAS_BIAS_FRAC
    else:
        _MEAS['biased'] = None


def _measurement_faults(idxs, rng):
    """Extra error on the exchanges of satellites `idxs` this round, in seconds."""
    extra = np.zeros(len(idxs))
    if MEAS_OUTLIER_P > 0.0:
        hit = rng.random(len(idxs)) < MEAS_OUTLIER_P
        extra += hit * rng.choice((-1.0, 1.0), size=len(idxs)) * MEAS_OUTLIER_S
    if _MEAS['biased'] is not None:
        extra += _MEAS['biased'][idxs] * MEAS_BIAS_S
    return extra


def _member_noise(n, idxs, hops, rng):
    h = np.ones(len(idxs)) if hops is None else np.maximum(hops[idxs], 1)
    noise = rng.normal(0.0, blt_links.twoway_sigma_s(), size=len(idxs)) * np.sqrt(h)
    if MEAS_OUTLIER_P > 0.0 or _MEAS['biased'] is not None:
        noise = noise + _measurement_faults(idxs, rng)
    return noise


# Which satellite heads a cluster, and when a head misreports (history test).
#   HEAD_POLICY 'centroid': the member nearest the cluster centroid (no memory).
#               'history' : among the HEAD_CANDIDATES members nearest the centroid,
#                           the one whose recorded precision is best. The record is
#                           the per-satellite residual each local round leaves on
#                           the ledger, the history a satellite needs, per the
#                           authors: each satellite's precision.
#   HEAD_FAULT  'majority': a head misreports when most of its members are faulty
#                           (the published model).
#               'own'     : a head misreports when its own oscillator is degraded.
#               'both'    : either of the two, the union, so one rule covers an
#                           individually degraded head and a degraded cluster, and
#                           every figure can run under the same rule.
# Defaults reproduce the published behaviour exactly.
HEAD_POLICY = 'centroid'
# Intermittent degradation (history test): None, or a dict with
#   'extra'  per-satellite extra drift step [s/tick] applied while degraded
#            (zero for satellites that never degrade)
#   'period' / 'on' ticks, 'phase' per-satellite tick offset
# A satellite is degraded at tick i when (i + phase) % period < on. The healthy
# metric then covers only satellites whose 'extra' is zero.
FAULT_SCHEDULE = None


def _schedule_state(i, base_step):
    """(drift_step, currently-degraded mask) under FAULT_SCHEDULE at tick i."""
    sch = FAULT_SCHEDULE
    if 'draws' in sch:
        # Memoryless: a pre-drawn (round x satellite) table of independent coin flips,
        # so whether a satellite is degraded now says nothing about the next round.
        k = min(i // sch['round_ticks'], len(sch['draws']) - 1)
        active = (sch['extra'] != 0) & sch['draws'][k]
    else:
        active = (sch['extra'] != 0) & (((i + sch['phase']) % sch['period']) < sch['on'])
    return base_step + np.where(active, sch['extra'], 0.0), active
# BLT local phase: skip the correction for members whose report the MAD filter
# flagged (only meaningful with LOCAL_MEASUREMENT_NOISE). Off by default.
LOCAL_SKIP_FLAGGED = False
HEAD_FAULT = 'majority'
HEAD_CANDIDATES = 10
LEDGER_DECAY = 0.7
# How much of the record the ledger keeps.
#   'ema'  the published behaviour: an exponential average with LEDGER_DECAY, so the
#          weights are 0.3, 0.21, 0.147 ... and the effective memory is 1/(1-decay)
#          = 3.3 rounds. A short memory is what an intermittently degrading satellite
#          needs, a long one would keep condemning one that has recovered.
#   'all'  every measurement since the run began, equally weighted (a running mean).
#          Unlimited memory, which is the strongest a precision record can be. Used to
#          show that what slips through is not a matter of how long the ledger remembers.
# 'ema' is the default and is bit-identical to the published configuration.
LEDGER_MEMORY = 'ema'
_LEDGER = {'score': None, 'count': None}

# Where the per-satellite precision record lives.
#
#   'global'   the committed ledger: one agreed history for the constellation,
#              so a satellite carries its record with it when the clustering
#              moves it to another cluster.
#   'cluster'  bookkeeping held by the cluster that made the measurements. A
#              satellite that changes cluster arrives with no record, and a
#              newcomer with no record is indistinguishable from one with a
#              clean record, which is what "cross-cluster state verification"
#              asks the ledger to provide.
#
# Only 'history' head selection reads the record, so this changes nothing for
# the other policies. 'global' is the published behaviour.
LEDGER_SCOPE = 'global'


def _cluster_of(n, cluster_idx_list):
    """Cluster index per satellite, so a re-clustering can be compared with the
    membership it replaced."""
    out = np.full(n, -1, dtype=int)
    for c, idxs in enumerate(cluster_idx_list):
        out[idxs] = c
    return out


def select_heads(positions, cluster_idx_list, use_history):
    heads = []
    score = _LEDGER['score'] if use_history else None
    for idxs in cluster_idx_list:
        c = positions[idxs]
        order = np.argsort(((c - c.mean(axis=0)) ** 2).sum(axis=1))[:HEAD_CANDIDATES]
        cand = idxs[order]
        heads.append(int(cand[np.argmin(score[cand])]) if score is not None else int(cand[0]))
    return np.array(heads)


def _member_hops(links, n):
    """Relay hops from each member to its head, or None (one hop) without links."""
    if links is None:
        return None
    hops = np.ones(n)
    for tree, idxs in zip(links.local_trees, links.cluster_idx_list):
        hops[idxs] = np.maximum(tree.depth[idxs], 1)
    return hops


def _link_model(n, sim_seed):
    return blt_isl.LinkModel(n, np.random.default_rng((sim_seed or 0) + 7919),
                             overrides=ISL_OVERRIDES)


# Position recompute cycle: LEO satellites at ~7.5 km/s move ~37 km over 5s,
# negligible relative to the 2500 km neighbor range, so neighbor topology is
# essentially stable on simulation timescales.
POSITION_UPDATE_CYCLE = 5000


# =============================================================================
# Simulation functions for each algorithm
# =============================================================================

def simulate_bc(satellites, time_units, k=12, sim_seed=None, faulty_head=None):
    """BLT-SAND: local robust intra-cluster aggregation @BC_LOCAL_CYCLE +
    global h-PBFT inter-cluster consensus @BC_CLUSTER_CYCLE.

    Local phase keeps each cluster internally tight (median+MAD). Global phase
    runs the hierarchical-PBFT consensus among cluster heads: it agrees on a
    single robust reference (median of trustworthy cluster summaries) and
    distributes it to all, provided a quorum of heads is trustworthy. When the
    faulty fraction pushes trustworthy heads below the quorum, the consensus
    fails to commit and the constellation loses its global anchor, the cliff.
    """
    positions, velocities, ang_vels, drifts, frequencies, clocks = _extract_arrays(satellites)
    normal_mask = ~blt_core.fault_mask(satellites)
    cluster_idx_list = cluster_indices_from_kmeans(positions, k)
    drift_step = blt_core.clock_error_step(drifts)
    nbr_rng = np.random.default_rng(sim_seed)
    # Separate stream for the polling order, so adding a collection window does
    # not shift any other random draw and runs stay comparable.
    collect_rng = np.random.default_rng((sim_seed or 0) + 9973)
    skew_rate = drifts - 1.0  # per-node by-hop skew (faulty carry the drift bias)
    is_faulty = np.array([s.get('drift_bias', 0.0) != 0.0 for s in satellites])
    links = _link_model(len(clocks), sim_seed) if ISL_LINK_MODEL else None
    if links is not None:
        links.update(positions, cluster_idx_list, 0.0)
    noise_rng = (np.random.default_rng((sim_seed or 0) + 4241)
                 if LOCAL_MEASUREMENT_NOISE else None)
    _measurement_setup(len(clocks), sim_seed)
    _LEDGER['score'] = np.zeros(len(clocks)) if HEAD_POLICY == 'history' else None
    _LEDGER['count'] = np.zeros(len(clocks)) if HEAD_POLICY == 'history' else None

    base_step = drift_step
    if FAULT_SCHEDULE is not None:
        normal_mask = FAULT_SCHEDULE['extra'] == 0

    performance_data = []
    pos_t = 0
    for i in range(time_units):
        if FAULT_SCHEDULE is not None and i % 1000 == 0:
            drift_step, active = _schedule_state(i, base_step)
            is_faulty[:] = active
        clocks += drift_step
        performance_data.append(measure_sync_performance_vec(clocks, normal_mask))

        if i % BC_LOCAL_CYCLE == 0:
            sync_local_robust(clocks, cluster_idx_list, drift_step=drift_step,
                              rng=collect_rng,
                              reach=links.local_reach() if links is not None else None,
                              noise_rng=noise_rng, hops=_member_hops(links, len(clocks)))
        if i % BC_CLUSTER_CYCLE == 0:
            round_no = i // BC_CLUSTER_CYCLE
            head_reach = (links.head_reach(round_no % len(cluster_idx_list))
                          if links is not None else None)
            sync_with_cluster_bc_vec(clocks, cluster_idx_list, positions, skew_rate, is_faulty,
                                     faulty_head=faulty_head, round_no=round_no,
                                     head_reach=head_reach)

        pos_t += 1
        if pos_t >= POSITION_UPDATE_CYCLE:
            positions = update_positions_vec(positions, velocities, ang_vels, POSITION_UPDATE_CYCLE)
            pos_t = 0
            was = _cluster_of(len(clocks), cluster_idx_list)
            cluster_idx_list = recluster(positions, k, cluster_idx_list)
            moved = was != _cluster_of(len(clocks), cluster_idx_list)
            BC_DIAG.setdefault('migrated', []).append(int(moved.sum()))
            if LEDGER_SCOPE == 'cluster' and _LEDGER['score'] is not None:
                # The record stayed with the old cluster: these satellites are
                # new faces to the cluster that now has to choose a head.
                _LEDGER['score'][moved] = 0.0
                if _LEDGER['count'] is not None:
                    _LEDGER['count'][moved] = 0.0
            if links is not None:
                links.update(positions, cluster_idx_list, (i + 1) * TIME_TICK)

    if links is not None:
        ISL_DIAG.clear()
        ISL_DIAG.update(links.summary())
    return performance_data


def simulate_cluster(satellites, time_units, k=12, sim_seed=None, faulty_head=None):
    """ATS: local intra-cluster aggregation @ATS_LOCAL_CYCLE + global
    inter-cluster reconciliation @ATS_GLOBAL_CYCLE, with no consensus.

    Same two-phase hierarchy as BLT but the global phase is a plain multi-hop
    average among cluster heads (no fault exclusion, no quorum, only partial
    per-round convergence). Faulty cluster references drag the reconciliation
    and residual inter-cluster spread survives, so ATS degrades steadily with
    the faulty ratio instead of staying bounded.
    """
    positions, velocities, ang_vels, drifts, frequencies, clocks = _extract_arrays(satellites)
    normal_mask = ~blt_core.fault_mask(satellites)
    cluster_idx_list = cluster_indices_from_kmeans(positions, k)
    drift_step = blt_core.clock_error_step(drifts)
    nbr_rng = np.random.default_rng(sim_seed)
    # Separate stream for the polling order, so adding a collection window does
    # not shift any other random draw and runs stay comparable.
    collect_rng = np.random.default_rng((sim_seed or 0) + 9973)
    skew_rate = drifts - 1.0  # per-node by-hop skew (faulty carry the drift bias)
    is_faulty = np.array([s.get('drift_bias', 0.0) != 0.0 for s in satellites])

    links = _link_model(len(clocks), sim_seed) if ISL_LINK_MODEL else None
    if links is not None:
        links.update(positions, cluster_idx_list, 0.0)
    noise_rng = (np.random.default_rng((sim_seed or 0) + 4241)
                 if LOCAL_MEASUREMENT_NOISE else None)
    _measurement_setup(len(clocks), sim_seed)

    base_step = drift_step
    if FAULT_SCHEDULE is not None:
        normal_mask = FAULT_SCHEDULE['extra'] == 0

    performance_data = []
    pos_t = 0
    for i in range(time_units):
        if FAULT_SCHEDULE is not None and i % 1000 == 0:
            drift_step, active = _schedule_state(i, base_step)
            is_faulty[:] = active
        clocks += drift_step
        performance_data.append(measure_sync_performance_vec(clocks, normal_mask))

        if i % ATS_LOCAL_CYCLE == 0:
            sync_with_cluster_vec(clocks, cluster_idx_list, drift_step=drift_step,
                                  rng=collect_rng,
                                  reach=links.local_reach() if links is not None else None,
                                  noise_rng=noise_rng, hops=_member_hops(links, len(clocks)))
        if i % ATS_GLOBAL_CYCLE == 0:
            # ATS gossips from the coordinator (head 0) outward, as headnet_byhop does.
            sync_global_ats(clocks, cluster_idx_list, positions, skew_rate, is_faulty,
                            faulty_head=faulty_head,
                            head_reach=links.head_reach(0) if links is not None else None)

        pos_t += 1
        if pos_t >= POSITION_UPDATE_CYCLE:
            positions = update_positions_vec(positions, velocities, ang_vels, POSITION_UPDATE_CYCLE)
            pos_t = 0
            cluster_idx_list = recluster(positions, k, cluster_idx_list)
            if links is not None:
                links.update(positions, cluster_idx_list, (i + 1) * TIME_TICK)

    if links is not None:
        ISL_DIAG.clear()
        ISL_DIAG.update(links.summary())
    return performance_data


def simulate_none(satellites, time_units, k=12, sim_seed=None):
    """Baseline: no synchronization at all, clocks drift unbounded."""
    _, _, _, drifts, _, clocks = _extract_arrays(satellites)
    normal_mask = ~blt_core.fault_mask(satellites)
    drift_step = blt_core.clock_error_step(drifts)
    nbr_rng = np.random.default_rng(sim_seed)
    perf = []
    for _ in range(time_units):
        clocks += drift_step
        perf.append(measure_sync_performance_vec(clocks, normal_mask))
    return perf


def simulate_ftsp(satellites, time_units, k=12, sim_seed=None):
    """FTSP: multi-hop flood @FTSP_FLOOD_CYCLE + pos update @POSITION_UPDATE_CYCLE.

    Flooding relays the reference clock hop-by-hop along the ISL graph; each
    relay adds its own skew, so the post-flood spread grows with the faulty
    relay ratio (see flood_time_sync_multihop), unlike the old single-hop
    oracle flood that pinned every satellite to the reference exactly.
    """
    positions, velocities, ang_vels, drifts, frequencies, clocks = _extract_arrays(satellites)
    normal_mask = ~blt_core.fault_mask(satellites)
    drift_step = blt_core.clock_error_step(drifts)
    nbr_rng = np.random.default_rng(sim_seed)
    neighbors = compute_neighbors_fast(positions, 2500)
    skew_rate = _ftsp_skew_rate(satellites, drifts)
    ftsp_rng = np.random.default_rng(sim_seed)
    _measurement_setup(len(clocks), sim_seed)
    links = _link_model(len(clocks), sim_seed) if ISL_LINK_MODEL else None
    if links is not None:
        # FTSP has no clusters; one all-node group gives the link model a root.
        links.update(positions, [np.arange(len(clocks))], 0.0)
        neighbors = links.neighbors

    performance_data = []
    pos_t = 0
    for i in range(time_units):
        clocks += drift_step
        performance_data.append(measure_sync_performance_vec(clocks, normal_mask))

        pos_t += 1
        if pos_t >= POSITION_UPDATE_CYCLE and not FTSP_STATIC_GRAPH:
            # Recomputing the neighbour graph reshuffles the flood BFS tree
            # (arbitrary tie-break), which steps the FTSP band at each update.
            # Over a ~30 s operating-point snapshot the topology is ~static
            # (sats move <~10% of the 2500 km range), so FTSP_STATIC_GRAPH freezes
            # the graph to keep the band flat; the spiky per-flood ripple
            # (its real weakness) is untouched.
            positions = update_positions_vec(positions, velocities, ang_vels, POSITION_UPDATE_CYCLE)
            pos_t = 0
            if links is not None:
                links.update(positions, [np.arange(len(clocks))], (i + 1) * TIME_TICK)
                neighbors = links.neighbors
            else:
                neighbors = compute_neighbors_fast(positions, 2500)

        if i % FTSP_FLOOD_CYCLE == 0:
            avg_frequency = frequencies.mean()
            reference_idx = int(np.argmin(np.abs(frequencies - avg_frequency)))
            offset = flood_time_sync_multihop(positions, neighbors, skew_rate, reference_idx,
                                              rng=ftsp_rng,
                                              faulty_relay=~normal_mask, links=links)
            synced = ~np.isnan(offset)
            if links is not None:
                links.stats['flood_unreached'].append(float(1.0 - synced.mean()))
            clocks[synced] = clocks[reference_idx] + offset[synced]

    if links is not None:
        ISL_DIAG.clear()
        ISL_DIAG.update(links.summary())
    return performance_data


# =============================================================================
# Main execution
# =============================================================================

if __name__ == '__main__':
    NUM_RUNS = 10
    NUM_SATS = 500
    NUM_MALFUNCTIONING = 0
    TIME_UNITS = 10000
    K = 12

    algorithms = {
        'bc': simulate_bc,
        'cluster': simulate_cluster,
        'ftsp': simulate_ftsp,
    }

    csv_names = {
        'bc': 'sync_performance_bc_nomal_w_neighbor.csv',
        'cluster': 'sync_performance_cluster_nomal.csv',
        'ftsp': 'sync_performance_ftsp_nomal_w_neighbor.csv',
    }

    all_avg = {}  # algorithm -> list of per-tick averages (averaged across runs)

    for alg_name, simulate_fn in algorithms.items():
        print(f"\n{'='*60}")
        print(f"Running {alg_name} algorithm ({NUM_RUNS} runs)")
        print(f"{'='*60}")

        simulation_results = {}

        for run in range(NUM_RUNS):
            print(f"\n--- {alg_name} run {run} ---")
            satellites = initialize_satellites(NUM_SATS, NUM_MALFUNCTIONING)
            performance_data = simulate_fn(satellites, TIME_UNITS, K)
            simulation_results[f'Simulation_{run}_Avg_Error'] = [data[0] for data in performance_data]

        # Save individual CSV
        df_performance = pd.DataFrame(simulation_results)
        df_performance.to_csv(f'./result/{csv_names[alg_name]}', index_label='Time')
        print(f"Saved ./result/{csv_names[alg_name]}")

        # Compute per-tick average across all runs
        all_avg[alg_name] = df_performance.mean(axis=1).tolist()

    # Save combined nomal_all.csv
    df_all = pd.DataFrame({
        'Time': list(range(TIME_UNITS)),
        'bc_nomal': all_avg['bc'],
        'cluster_nomal': all_avg['cluster'],
        'ftsp_nomal': all_avg['ftsp'],
    })
    df_all.to_csv('./result/nomal_all.csv', index=False)
    print(f"\nSaved ./result/nomal_all.csv")
    print("Done.")
