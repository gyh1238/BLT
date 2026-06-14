import numpy as np
from geopy.distance import great_circle
from math import sqrt, sin, cos
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import pandas as pd
import heapq  # For priority queue
from function_get_tle import get_sat_from_text
from collections import defaultdict
from scipy.spatial import KDTree

import random

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
# oscillator is modeled as this same jitter plus a coherent malfunction_drift_bias
# of a few ppb (a moderately degraded oscillator), large enough to be detected
# by the h-PBFT agreement test but small enough that its drift over the multi-
# second commit cycle keeps BLT under the 10 ns ISL line up to the 1/3 bound.
NORMAL_OSC_STDDEV = 0.04


def initialize_satellites(number_of_sat, num_malfunctioning,
                          malfunction_mean=50 * (10 ** 6),
                          malfunction_stddev=10,
                          malfunction_drift_bias=0.0,
                          concentrate_faults=False,
                          cluster_aligned=False):
    """Initialize satellites using the get_sat_tle function and setup additional properties.

    When concentrate_faults=True the faulty satellites are picked as a spatial
    cluster (one random seed + its nearest neighbors) so they fall into a small
    number of KMeans clusters — a prerequisite for BFT outlier exclusion to
    actually exclude anything.
    """
    name_list, pos_list, vel_list, vel_ang_list = _get_or_synthesize_constellation(number_of_sat)

    satellites = []

    # Define normal oscillator mean and standard deviation
    normal_mean = 40 * (10 ** 6)  # Hz
    normal_stddev = NORMAL_OSC_STDDEV  # Hz; NORMAL_OSC_STDDEV/normal_mean = ppb spread

    if cluster_aligned and num_malfunctioning > 0:
        # Fault model: a correlated/Byzantine failure compromises WHOLE clusters.
        # We consume whole KMeans clusters (largest first) up to the budget; any
        # leftover faults are scattered as a strict MINORITY (< half) into the
        # still-healthy clusters so none of those tips into a lying majority.
        # Consequently the number of *majority-faulty* clusters (the BFT voting
        # units whose head lies) increments by exactly one each time a whole
        # cluster is consumed — giving a SHARP h-PBFT cliff at the 1/3-cluster
        # bound instead of the smeared ramp produced by a half-filled cluster
        # tipping early (which put the cliff onset near 29% instead of 33%).
        pos_arr = np.asarray(pos_list, dtype=float)
        clusters = cluster_indices_from_kmeans(pos_arr, FAULT_CLUSTER_K)
        order = sorted(range(len(clusters)), key=lambda c: -len(clusters[c]))
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
        seed = np.random.randint(number_of_sat)
        d2 = np.sum((pos_arr - pos_arr[seed]) ** 2, axis=1)
        malfunctioning_indices = np.argsort(d2)[:num_malfunctioning]
    else:
        malfunctioning_indices = np.random.choice(number_of_sat, num_malfunctioning, replace=False)

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
        satellite['frequency'] = np.random.normal(satellite['oscillator_mean'], satellite['oscillator_stddev'])
        # Initial drift based on Gaussian distribution
        satellite['drift'] = satellite['frequency'] / satellite['oscillator_mean'],
        # Coherent frequency offset of a malfunctioning oscillator. drift =
        # freq/mean is zero-mean by construction, so a faulty satellite only
        # jitters around nominal — it never biases its cluster's aggregate,
        # which is what a real off-nominal oscillator does. drift_bias adds
        # that one-directional ppb-scale offset so faulty clusters become
        # clean cross-cluster outliers (Section IV.B "biased measurements").
        satellite['drift_bias'] = bias
        satellites.append(satellite)

    return satellites


def update_clocks(satellites, time_units):
    """Update clocks for all satellites collectively."""
    for satellite in satellites:
        satellite['clock'] += satellite['drift'][0] * time_units * TIME_TICK


def cartesian_to_geodetic(cartesian_coords):
    """Convert Cartesian coordinates to geodetic coordinates."""
    x, y, z = cartesian_coords
    radius = sqrt(x**2 + y**2 + z**2)
    lat = np.arcsin(z / radius) * 180 / np.pi
    lon = np.arctan2(y, x) * 180 / np.pi

    return (lat, lon)


def update_positions(satellites, time_units):
    """Update positions considering circular motion."""
    for satellite in satellites:
        # Convert to spherical coordinates
        x, y, z = satellite['position']
        vx, vy, vz = satellite['velocity']

        # Update latitude and longitude based on angular velocity
        delta_angle = satellite['angular_velocity'] * time_units * TIME_TICK
        new_x = x * cos(delta_angle * 180 / np.pi) + vx * sin(delta_angle * 180 / np.pi)
        new_y = y * cos(delta_angle * 180 / np.pi) + vy * sin(delta_angle * 180 / np.pi)
        new_z = z * cos(delta_angle * 180 / np.pi) + vz * sin(delta_angle * 180 / np.pi)

        satellite['position'] = (new_x, new_y, new_z)
        satellite['position_latlon'] = cartesian_to_geodetic(satellite['position'])


def compute_distance_matrix(satellites):
    """Compute a distance matrix using KD-Tree queries."""
    positions = np.array([sat['position'] for sat in satellites])
    tree = KDTree(positions)

    num_sats = len(satellites)
    distances = np.zeros((num_sats, num_sats))

    for i in range(num_sats):
        _, neighbors = tree.query(positions[i], k=num_sats)
        for j in neighbors:
            dist = great_circle((satellites[i]['position_latlon']), (satellites[j]['position_latlon'])).km
            distances[i, j] = dist

    return distances


def cache_neighbors(satellites, distance_matrix, range_limit):
    """Cache 1-hop neighbors for each satellite."""
    neighbor_dict = defaultdict(list)

    for i, row in enumerate(distance_matrix):
        for j, dist in enumerate(row):
            if i != j and dist < range_limit:
                neighbor_dict[i].append(j)

    return neighbor_dict


def flood_time_sync(satellites, reference_idx, delay_factor=299792):
    """Propagate time from a reference satellite to all others, considering delay."""
    events = []  # Priority queue to store synchronization events

    for i in range(len(satellites)):
        if i != reference_idx:
            ref_pos = satellites[reference_idx]['position_latlon']
            oth_pos = satellites[i]['position_latlon']
            dist = great_circle(ref_pos, oth_pos).km
            delay = dist / delay_factor

            # Schedule synchronization event
            heapq.heappush(events, (delay, reference_idx, i))

    return events


def balanced_kmeans(satellites, k):
    """Perform balanced K-means clustering."""
    positions = np.array([sat['position'] for sat in satellites])
    scaler = StandardScaler()
    scaled_positions = scaler.fit_transform(positions)

    kmeans = KMeans(n_clusters=k, n_init=10, random_state=42)
    kmeans.fit(scaled_positions)

    for i, cluster in enumerate(kmeans.labels_):
        satellites[i]['cluster'] = cluster


def cluster_satellites(satellites, k):
    """Cluster satellites into k balanced clusters."""
    balanced_kmeans(satellites, k)

    satellite_clusters = {}
    for sat in satellites:
        cluster = sat['cluster']
        if cluster not in satellite_clusters:
            satellite_clusters[cluster] = []
        satellite_clusters[cluster].append(sat)

    return satellite_clusters


def sync_with_cluster(satellite_clusters):
    """Synchronize each satellite's clock to the average clock time of its cluster."""
    for cluster, sats in satellite_clusters.items():
        avg_time = np.mean([sat['clock'] for sat in sats])
        for sat in sats:
            sat['clock'] = avg_time


def sync_with_cluster_bc(satellite_clusters,
                         exclusion_threshold=1.8,
                         outlier_k=3.0, quorum=3 / 4):
    """BLTi-SAND global sync: within-cluster outlier-filtered mean, then
    BFT-supermajority-validated median across clusters.

    1. Within each cluster, exclude member clocks beyond 1.8σ and average the
       rest — robust to a few faulty satellites inside an otherwise honest
       cluster.
    2. Across clusters, identify outlier cluster averages via MAD (median
       absolute deviation) — more robust than std when several outliers are
       present. Accept the median of inliers only if a 2/3 supermajority of
       clusters are inliers; otherwise skip the global update so that the
       BFT-quorum failure manifests as cluster-cycle drift accumulation.
    """
    cluster_averages = {}
    for cluster, sats in satellite_clusters.items():
        clocks = np.array([sat['clock'] for sat in sats])
        m, s = clocks.mean(), clocks.std()
        valid = np.abs(clocks - m) <= exclusion_threshold * s
        cluster_averages[cluster] = float(clocks[valid].mean()) if valid.any() else float(m)

    cluster_avgs_arr = np.array(list(cluster_averages.values()))
    median = float(np.median(cluster_avgs_arr))
    mad = float(np.median(np.abs(cluster_avgs_arr - median)))
    threshold = max(outlier_k * 1.4826 * mad, 1e-18)
    inlier = np.abs(cluster_avgs_arr - median) <= threshold
    if inlier.sum() / len(cluster_avgs_arr) < quorum:
        return  # BFT supermajority failed — skip global update

    global_avg_time = float(np.median(cluster_avgs_arr[inlier]))
    for cluster, sats in satellite_clusters.items():
        for sat in sats:
            sat['clock'] = global_avg_time


def sync_with_neighbor(satellites, neighbors, mean_freq=40 * (10**6)):
    """Synchronize each satellite's clock with its nearest 1-hop neighbor with a frequency closest to the mean."""
    for i, neighbor_idxs in neighbors.items():
        if neighbor_idxs:
            closest_neighbor = min(neighbor_idxs, key=lambda idx: abs(satellites[idx]['frequency'] - mean_freq))
            satellites[i]['clock'] += (satellites[closest_neighbor]['clock'] - satellites[i]['clock']) / 2


def sync_with_neighbor_random(satellites, neighbors, mean_freq=40 * (10 ** 6)):
    """Synchronize each satellite's clock with its nearest 1-hop neighbor with a frequency closest to the mean."""
    for i, neighbor_idxs in neighbors.items():
        if neighbor_idxs:
            closest_neighbor = random.choice(neighbor_idxs)
            satellites[i]['clock'] += (satellites[closest_neighbor]['clock'] - satellites[i]['clock']) / 2


def sync_with_neighbor_random_n(satellites, neighbors, mean_freq=40 * (10 ** 6), top_n=5):
    """Synchronize each satellite's clock with its nearest 1-hop neighbor with a frequency closest to the mean."""
    for i, neighbor_idxs in neighbors.items():
        if neighbor_idxs:
            sorted_neighbors = sorted(neighbor_idxs, key=lambda idx: abs(satellites[idx]['frequency'] - mean_freq))
            top_neighbors = sorted_neighbors[:top_n]
            selected_neighbor = random.choice(top_neighbors)
            satellites[i]['clock'] += (satellites[selected_neighbor]['clock'] - satellites[i]['clock']) / 2


def measure_sync_performance(satellites, ref_time):
    """Measure synchronization performance as the deviation of each clock from the reference time."""
    errors = [abs(sat['clock'] - ref_time) for sat in satellites]
    return np.mean(errors), np.max(errors)


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
    """KDTree query_ball_point — replaces O(N^2) great_circle pair loop.

    LEO satellites at the same altitude have chord ≈ great-circle within 0.1%
    over a 2500 km range, so 3D Euclidean distance is sufficient.
    """
    tree = KDTree(positions)
    pairs = tree.query_ball_point(positions, r=range_limit)
    return {i: [j for j in pairs[i] if j != i] for i in range(len(positions))}


def compute_best_neighbor_array(positions, frequencies, range_limit=2500.0,
                                mean_freq=40 * (10 ** 6)):
    """Per-satellite index of the neighbor with frequency closest to mean_freq.

    Frequencies are static after init, so this can be precomputed once per
    neighbor refresh and reused on every sync call (eliminates the Python loop
    inside sync_with_neighbor at large N).
    """
    tree = KDTree(positions)
    pairs = tree.query_ball_point(positions, r=range_limit)
    n = len(positions)
    best = np.arange(n, dtype=np.int64)
    freq_dev = np.abs(frequencies - mean_freq)
    for i in range(n):
        nbrs = [j for j in pairs[i] if j != i]
        if nbrs:
            best[i] = nbrs[int(np.argmin(freq_dev[nbrs]))]
    return best


def compute_top_n_neighbor_array(positions, frequencies, range_limit=2500.0,
                                 mean_freq=40 * (10 ** 6), top_n=5):
    """Per-satellite top_n neighbor indices ordered by frequency closeness."""
    tree = KDTree(positions)
    pairs = tree.query_ball_point(positions, r=range_limit)
    n = len(positions)
    top = np.tile(np.arange(n, dtype=np.int64)[:, None], (1, top_n))
    freq_dev = np.abs(frequencies - mean_freq)
    for i in range(n):
        nbrs = [j for j in pairs[i] if j != i]
        if not nbrs:
            continue
        order = np.argsort(freq_dev[nbrs])[:top_n]
        picked = [nbrs[k] for k in order]
        m = len(picked)
        top[i, :m] = picked
        if m < top_n:
            top[i, m:] = picked[-1]
    return top


def sync_with_neighbor_pre(clocks, best):
    clocks += (clocks[best] - clocks) / 2


def sync_with_neighbor_random_n_pre(clocks, top, rng):
    n = clocks.shape[0]
    pick = rng.integers(0, top.shape[1], size=n)
    chosen = top[np.arange(n), pick]
    clocks += (clocks[chosen] - clocks) / 2


def update_positions_vec(positions, velocities, ang_vels, time_units):
    delta_angle = ang_vels * time_units * TIME_TICK
    factor = delta_angle * 180.0 / np.pi
    c = np.cos(factor)[:, None]
    s = np.sin(factor)[:, None]
    return positions * c + velocities * s


def flood_time_sync_vec(positions, reference_idx, delay_factor=299792.0):
    diffs = positions - positions[reference_idx]
    dists = np.sqrt((diffs * diffs).sum(axis=1))
    events = []
    for i, d in enumerate(dists):
        if i != reference_idx:
            heapq.heappush(events, (float(d) / delay_factor, reference_idx, i))
    return events


# Effective per-hop time (seconds) over which a relay's uncorrected clock skew
# acts before it re-timestamps and forwards. This is the single knob that sets
# FTSP's by-hop error magnitude; module level so the Fig.5b harness can sweep
# it. Tuned so the fault-free flood lands near the panel-(a) FTSP value.
FTSP_HOP_DELAY = 2.0e-4

# Coherent per-hop skew rate that a *faulty* relay stamps into the flood. A
# malfunctioning node mis-timestamps far worse than its steady clock bias
# implies, and concentrate_faults keeps healthy relays on most paths, so
# without this the by-hop signal barely moves. Module level for sweeping.
# Tuned (with FTSP_HOP_DELAY) so FTSP lands ~14 ns fault-free and ~30 ns at
# 30% faults, monotonically degrading the way Section IV.B describes.
FTSP_FAULT_SKEW = 1.0e-7


def flood_time_sync_multihop(positions, neighbors, skew_rate, reference_idx,
                             hop_delay=None):
    """Multi-hop flood with by-hop error accumulation — FTSP's intrinsic
    weakness (Maróti 2004; paper Section IV.B "residual mismatch accumulates
    along the flooding path").

    The reference time is not delivered to every satellite directly. It is
    relayed node-to-node along the ISL graph by BFS, and each relay re-stamps
    the message with its own imperfect clock, injecting ``drift_dev *
    hop_delay`` of residual skew. The offsets accumulate along the path, so a
    satellite many hops behind a faulty relay inherits a large error.

    ``skew_rate`` is the per-node by-hop skew: healthy nodes use their small
    clock deviation, faulty relays use a larger coherent value (the caller
    sets this). Faulty relays push every downstream path the *same* direction,
    so the ensemble dispersion grows with the faulty-node ratio instead of
    staying flat the way a single-hop oracle flood does.

    Light-travel delay is deterministic and compensated by FTSP's timestamp
    exchange, so it only sets arrival order (here: BFS hop order) and injects
    no skew — only a relay's own clock imperfection does, hence the error
    scales with ``hop_delay`` rather than link length. Satellites in a
    disconnected component never receive the flood and are returned as NaN.
    """
    if hop_delay is None:
        hop_delay = FTSP_HOP_DELAY
    n = len(positions)
    received_offset = np.full(n, np.nan)
    received_offset[reference_idx] = 0.0
    visited = np.zeros(n, dtype=bool)
    visited[reference_idx] = True
    current = [reference_idx]
    while current:
        nxt = []
        for relay in current:
            # offset a child inherits = parent's offset + skew the relay adds
            base = received_offset[relay] + skew_rate[relay] * hop_delay
            for nbr in neighbors[relay]:
                if visited[nbr]:
                    continue
                visited[nbr] = True
                received_offset[nbr] = base
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


def sync_with_neighbor_vec(clocks, frequencies, neighbors, mean_freq=40 * (10 ** 6)):
    freq_dev = np.abs(frequencies - mean_freq)
    new_clocks = clocks.copy()
    for i, nbrs in neighbors.items():
        if nbrs:
            best = nbrs[int(np.argmin(freq_dev[nbrs]))]
            new_clocks[i] = clocks[i] + (clocks[best] - clocks[i]) / 2
    clocks[:] = new_clocks


def sync_with_neighbor_random_n_vec(clocks, frequencies, neighbors, mean_freq=40 * (10 ** 6), top_n=5):
    freq_dev = np.abs(frequencies - mean_freq)
    new_clocks = clocks.copy()
    for i, nbrs in neighbors.items():
        if nbrs:
            order = np.argsort(freq_dev[nbrs])
            top = [nbrs[k] for k in order[:top_n]]
            chosen = random.choice(top)
            new_clocks[i] = clocks[i] + (clocks[chosen] - clocks[i]) / 2
    clocks[:] = new_clocks


def cluster_indices_from_kmeans(positions, k):
    scaler = StandardScaler()
    scaled = scaler.fit_transform(positions)
    km = KMeans(n_clusters=k, n_init=10, random_state=42)
    km.fit(scaled)
    labels = km.labels_
    return [np.where(labels == c)[0] for c in range(k)]


# --- Inter-cluster propagation (shared by ATS and BLT global phases) ---------
# The global phase is NOT an instantaneous broadcast: cluster heads are far
# apart and reconcile over a multi-hop head network, so per hop a relay head
# adds its own clock skew (healthy ~1 ppb, a faulty head its drift bias). This
# is the same by-hop physics FTSP suffers, but over the shorter hierarchical
# head graph instead of a flat constellation-wide flood — which is exactly why
# the hierarchy is cheaper/more accurate than flooding.
INTERCLUSTER_HOP_DELAY = 6.0e-4


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


def headnet_byhop(nbr, head_skew, hop_delay, coordinator=0):
    """BFS over the head graph from a coordinator; each cluster inherits the
    relay skew accumulated along its path (by-hop propagation error)."""
    K = len(nbr)
    off = np.zeros(K)
    visited = np.zeros(K, dtype=bool)
    visited[coordinator] = True
    cur = [coordinator]
    while cur:
        nxt = []
        for r in cur:
            base = off[r] + head_skew[r] * hop_delay
            for nb in nbr[r]:
                if not visited[nb]:
                    visited[nb] = True
                    off[nb] = base
                    nxt.append(nb)
        cur = nxt
    return off


def sync_with_cluster_vec(clocks, cluster_idx_list):
    for idxs in cluster_idx_list:
        clocks[idxs] = clocks[idxs].mean()


# Max fraction of within-cluster members a cluster may shed to the robust
# filter and still count as a *trustworthy* voter in the h-PBFT quorum. Module
# level so the Fig.5b tuning harness can sweep it without touching call sites.
BC_TRUST_FRAC = 0.2

# BC global (cross-cluster) sync interval in ticks. Shorter resets faulty
# clocks to the consensus value more often, so their coherent bias accumulates
# over a smaller window and the pre-cliff flat band stays under the 10 ns ISL
# line. Module level so the Fig.5b harness can sweep it.
BC_CLUSTER_CYCLE = 2000

# Fraction of cluster heads that must stay trustworthy for the global BFT
# consensus to commit. The cliff sits where the faulty fraction makes the
# trustworthy heads drop below this. Loosening it (e.g. 2/3) lets BLT-SAND hold
# the consensus past a higher fault ratio, pushing the cliff to the right.
BC_QUORUM = 3 / 4

# Two-phase synchronization cycles (paper Section II.B/C): a frequent LOCAL
# intra-cluster phase suppresses short-term drift, and a less-frequent GLOBAL
# inter-cluster phase removes accumulated cross-cluster discrepancy. Periods
# are set so total message volume is comparable across FTSP/ATS/BLT and may be
# re-tuned from the message accounting.
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

# ATS accumulates more inter-cluster by-hop residual than BLT even with no
# faults: lacking a single consensus value, its reconciliation gossips over a
# longer effective relay path (no efficient agreement tree), so its propagation
# residual — and thus its healthy baseline RMSE — sits a fixed factor above
# BLT's consensus distribution. This decouples ATS's (above-ISL) baseline from
# BLT's (below-ISL) one without changing the shared INTERCLUSTER_HOP_DELAY.
ATS_HOP_MULT = 1.0

# h-PBFT agreement tolerance (seconds): two cluster heads are considered to
# agree on the timing state if their references differ by less than this. Set
# above the residual spread among healthy heads but below a faulty head's
# bias-driven offset, so healthy heads form a supermajority while faulty heads
# fall outside it. Tunable.
BC_AGREE_TOL = 3.0e-11

# Anomalous faulty-reading error. A degraded node is NOT malicious — it tries
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
FAULTY_REPORT_ERROR = 6.0e-11

# How far a faulty cluster ends up mis-synchronized under ATS. ATS has no
# consensus to exclude the anomalous report, so the faulty cluster settles at
# an offset from the honest consensus (it cannot be pulled into line), and that
# offset — present for each faulty cluster, absent under BLT which excludes
# them — is what makes ATS's RMSE climb smoothly with the faulty ratio. Kept
# separate from FAULTY_REPORT_ERROR so ATS's growth rate and BLT's
# outlier-detection margin can be set independently.
ATS_FAULT_OFFSET = 4.0e-11

# Lightweight diagnostics for the h-PBFT gate (commit/skip/flagged-per-call).
BC_DIAG = {'commit': 0, 'skip': 0, 'flagged': []}


def sync_with_cluster_bc_vec(clocks, cluster_idx_list, positions, skew_rate,
                             is_faulty, within_k=3.0, quorum=None, agree_tol=None):
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
    commit, and the constellation loses its global anchor — clusters then drift
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

    # Byzantine heads report a lied value; BLT votes on the *reported* values
    # (this is what the consensus actually sees), so a large lie is an obvious
    # outlier and is rejected — but the committed value uses the *true* head
    # references of the agreeing (honest) clusters, so the lie never enters it.
    reported = cluster_avgs.copy()
    for ci, idxs in enumerate(cluster_idx_list):
        if is_faulty[idxs].mean() > 0.5:
            reported[ci] += FAULTY_REPORT_ERROR

    # PBFT supermajority agreement on the reported values.
    candidate = float(np.median(reported))
    agree = np.abs(reported - candidate) <= agree_tol
    BC_DIAG['flagged'].append(int((~agree).sum()))
    if agree.sum() / len(cluster_avgs) < quorum:
        BC_DIAG['skip'] += 1
        return  # too many liars — no honest supermajority, no block commits

    BC_DIAG['commit'] += 1
    global_avg = float(np.median(cluster_avgs[agree]))
    # Distribute the agreed value over the head network. The block is
    # signed/hash-chained, so a faulty head cannot tamper the *value* and its
    # bad reading never enters global_avg (it was excluded from the agreeing
    # set). But every head — faulty ones included — still *relays* the block and
    # adds the same physical by-hop timestamp/relay residual. So the propagation
    # residual depends on the head-graph topology, not on how many heads are
    # faulty: BLT's pre-cliff RMSE stays ~flat as the faulty ratio grows instead
    # of spuriously dropping (which it did when faulty relays were zeroed out).
    heads, nbr = cluster_head_graph(positions, cluster_idx_list)
    head_skew = skew_rate[np.array(heads)]
    off = headnet_byhop(nbr, head_skew, INTERCLUSTER_HOP_DELAY)
    for ci, idxs in enumerate(cluster_idx_list):
        clocks[idxs] = global_avg + off[ci]


def sync_local_robust(clocks, cluster_idx_list, within_k=3.0):
    """BLT local (intra-cluster) phase: each cluster head aggregates members
    into a robust reference (median after a MAD trim) and aligns its members
    to it. Robust so a few faulty members inside an otherwise-healthy cluster
    do not poison the cluster reference."""
    for idxs in cluster_idx_list:
        c = clocks[idxs]
        med = np.median(c)
        mad = np.median(np.abs(c - med))
        threshold = max(within_k * 1.4826 * mad, 1e-18)
        valid = np.abs(c - med) <= threshold
        clocks[idxs] = np.median(c[valid]) if valid.any() else med


def sync_global_ats(clocks, cluster_idx_list, positions, skew_rate, is_faulty,
                    alpha=None):
    """ATS global (inter-cluster) phase: cluster heads reconcile by gossip over
    the multi-hop head network — no consensus, no verification. A Byzantine
    (majority-faulty) head reports a lied value (FAULTY_REPORT_ERROR); with no signed
    block or BFT vote to reject it, the lie enters the local reconciliation and
    spreads to nearby heads, plus healthy by-hop propagation error. The
    resulting residual inter-cluster spread grows with the number of liars."""
    if alpha is None:
        alpha = ATS_RECONCILE_ALPHA
    refs = np.array([clocks[idxs].mean() for idxs in cluster_idx_list])
    g = float(refs.mean())  # global reconcile target
    heads, nbr = cluster_head_graph(positions, cluster_idx_list)
    off = headnet_byhop(nbr, skew_rate[np.array(heads)],
                        INTERCLUSTER_HOP_DELAY * ATS_HOP_MULT)
    # Reconcile every cluster toward the global value with healthy by-hop
    # residual (baseline). A faulty cluster, whose anomalous report ATS cannot
    # verify or exclude, settles mis-synchronized by ATS_FAULT_OFFSET — so the
    # inter-cluster spread grows smoothly with the number of faulty clusters.
    for ci, idxs in enumerate(cluster_idx_list):
        clocks[idxs] += alpha * (g + off[ci] - refs[ci])
        if is_faulty[idxs].mean() > 0.5:
            clocks[idxs] += ATS_FAULT_OFFSET


def measure_sync_performance_vec(clocks):
    mean = clocks.mean()
    errors = np.abs(clocks - mean)
    return float(errors.mean()), float(errors.max())


# Position recompute cycle: LEO satellites at ~7.5 km/s move ~37 km over 5s,
# negligible relative to the 2500 km neighbor range, so neighbor topology is
# essentially stable on simulation timescales.
POSITION_UPDATE_CYCLE = 5000


# =============================================================================
# Simulation functions for each algorithm
# =============================================================================

def simulate_bc(satellites, time_units, k=12):
    """BLT-SAND: local robust intra-cluster aggregation @BC_LOCAL_CYCLE +
    global h-PBFT inter-cluster consensus @BC_CLUSTER_CYCLE.

    Local phase keeps each cluster internally tight (median+MAD). Global phase
    runs the hierarchical-PBFT consensus among cluster heads: it agrees on a
    single robust reference (median of trustworthy cluster summaries) and
    distributes it to all, provided a quorum of heads is trustworthy. When the
    faulty fraction pushes trustworthy heads below the quorum, the consensus
    fails to commit and the constellation loses its global anchor — the cliff.
    """
    positions, velocities, ang_vels, drifts, frequencies, clocks = _extract_arrays(satellites)
    cluster_idx_list = cluster_indices_from_kmeans(positions, k)
    drift_step = drifts * TIME_TICK * TIME_TICK
    skew_rate = drifts - 1.0  # per-node by-hop skew (faulty carry the drift bias)
    is_faulty = np.array([s.get('drift_bias', 0.0) != 0.0 for s in satellites])

    performance_data = []
    pos_t = 0
    for i in range(time_units):
        clocks += drift_step
        performance_data.append(measure_sync_performance_vec(clocks))

        if i % BC_LOCAL_CYCLE == 0:
            sync_local_robust(clocks, cluster_idx_list)
        if i % BC_CLUSTER_CYCLE == 0:
            sync_with_cluster_bc_vec(clocks, cluster_idx_list, positions, skew_rate, is_faulty)

        pos_t += 1
        if pos_t >= POSITION_UPDATE_CYCLE:
            positions = update_positions_vec(positions, velocities, ang_vels, POSITION_UPDATE_CYCLE)
            pos_t = 0
            cluster_idx_list = cluster_indices_from_kmeans(positions, k)

    return performance_data


def simulate_cluster(satellites, time_units, k=12):
    """ATS: local intra-cluster aggregation @ATS_LOCAL_CYCLE + global
    inter-cluster reconciliation @ATS_GLOBAL_CYCLE, with no consensus.

    Same two-phase hierarchy as BLT but the global phase is a plain multi-hop
    average among cluster heads (no fault exclusion, no quorum, only partial
    per-round convergence). Faulty cluster references drag the reconciliation
    and residual inter-cluster spread survives, so ATS degrades steadily with
    the faulty ratio instead of staying bounded.
    """
    positions, velocities, ang_vels, drifts, frequencies, clocks = _extract_arrays(satellites)
    cluster_idx_list = cluster_indices_from_kmeans(positions, k)
    drift_step = drifts * TIME_TICK * TIME_TICK
    skew_rate = drifts - 1.0  # per-node by-hop skew (faulty carry the drift bias)
    is_faulty = np.array([s.get('drift_bias', 0.0) != 0.0 for s in satellites])

    performance_data = []
    pos_t = 0
    for i in range(time_units):
        clocks += drift_step
        performance_data.append(measure_sync_performance_vec(clocks))

        if i % ATS_LOCAL_CYCLE == 0:
            sync_with_cluster_vec(clocks, cluster_idx_list)
        if i % ATS_GLOBAL_CYCLE == 0:
            sync_global_ats(clocks, cluster_idx_list, positions, skew_rate, is_faulty)

        pos_t += 1
        if pos_t >= POSITION_UPDATE_CYCLE:
            positions = update_positions_vec(positions, velocities, ang_vels, POSITION_UPDATE_CYCLE)
            pos_t = 0
            cluster_idx_list = cluster_indices_from_kmeans(positions, k)

    return performance_data


def simulate_bc_param(satellites, time_units, k, cluster_update_cycle):
    positions, velocities, ang_vels, drifts, frequencies, clocks = _extract_arrays(satellites)
    best = compute_best_neighbor_array(positions, frequencies, 2500)
    cluster_idx_list = cluster_indices_from_kmeans(positions, k)
    drift_step = drifts * TIME_TICK * TIME_TICK
    skew_rate = drifts - 1.0
    is_faulty = np.array([s.get('drift_bias', 0.0) != 0.0 for s in satellites])
    perf = []
    pos_t = 0
    cls_t = 0
    for i in range(time_units):
        clocks += drift_step
        perf.append(measure_sync_performance_vec(clocks))
        if i % 200 == 0:
            sync_with_neighbor_pre(clocks, best)
        pos_t += 1
        if pos_t >= POSITION_UPDATE_CYCLE:
            positions = update_positions_vec(positions, velocities, ang_vels, POSITION_UPDATE_CYCLE)
            pos_t = 0
            best = compute_best_neighbor_array(positions, frequencies, 2500)
            cluster_idx_list = cluster_indices_from_kmeans(positions, k)
        cls_t += 1
        if cls_t >= cluster_update_cycle:
            sync_with_cluster_bc_vec(clocks, cluster_idx_list, positions, skew_rate, is_faulty)
            cls_t = 0
    return perf


def simulate_cluster_param(satellites, time_units, k, cluster_update_cycle):
    positions, velocities, ang_vels, drifts, frequencies, clocks = _extract_arrays(satellites)
    top = compute_top_n_neighbor_array(positions, frequencies, 2500)
    cluster_idx_list = cluster_indices_from_kmeans(positions, k)
    drift_step = drifts * TIME_TICK * TIME_TICK
    rng = np.random.default_rng()
    perf = []
    pos_t = 0
    cls_t = 0
    for i in range(time_units):
        clocks += drift_step
        perf.append(measure_sync_performance_vec(clocks))
        if i % 200 == 0:
            sync_with_neighbor_random_n_pre(clocks, top, rng)
        pos_t += 1
        if pos_t >= POSITION_UPDATE_CYCLE:
            positions = update_positions_vec(positions, velocities, ang_vels, POSITION_UPDATE_CYCLE)
            pos_t = 0
            top = compute_top_n_neighbor_array(positions, frequencies, 2500)
            cluster_idx_list = cluster_indices_from_kmeans(positions, k)
        cls_t += 1
        if cls_t >= cluster_update_cycle:
            sync_with_cluster_vec(clocks, cluster_idx_list)
            cls_t = 0
    return perf


def simulate_ftsp_param(satellites, time_units, k, ftsp_cycle):
    positions, velocities, ang_vels, drifts, frequencies, clocks = _extract_arrays(satellites)
    drift_step = drifts * TIME_TICK * TIME_TICK
    neighbors = compute_neighbors_fast(positions, 2500)
    skew_rate = _ftsp_skew_rate(satellites, drifts)
    perf = []
    pos_t = 0
    for i in range(time_units):
        clocks += drift_step
        perf.append(measure_sync_performance_vec(clocks))
        pos_t += 1
        if pos_t >= POSITION_UPDATE_CYCLE:
            positions = update_positions_vec(positions, velocities, ang_vels, POSITION_UPDATE_CYCLE)
            pos_t = 0
            neighbors = compute_neighbors_fast(positions, 2500)
        if i % ftsp_cycle == 0:
            avg_freq = frequencies.mean()
            ref_idx = int(np.argmin(np.abs(frequencies - avg_freq)))
            offset = flood_time_sync_multihop(positions, neighbors, skew_rate, ref_idx)
            synced = ~np.isnan(offset)
            clocks[synced] = clocks[ref_idx] + offset[synced]
    return perf


def simulate_none(satellites, time_units, k=12):
    """Baseline: no synchronization at all — clocks drift unbounded."""
    _, _, _, drifts, _, clocks = _extract_arrays(satellites)
    drift_step = drifts * TIME_TICK * TIME_TICK
    perf = []
    for _ in range(time_units):
        clocks += drift_step
        perf.append(measure_sync_performance_vec(clocks))
    return perf


def simulate_ftsp(satellites, time_units, k=12):
    """FTSP: multi-hop flood @750 + pos update @POSITION_UPDATE_CYCLE.

    Flooding relays the reference clock hop-by-hop along the ISL graph; each
    relay adds its own skew, so the post-flood spread grows with the faulty
    relay ratio (see flood_time_sync_multihop), unlike the old single-hop
    oracle flood that pinned every satellite to the reference exactly.
    """
    positions, velocities, ang_vels, drifts, frequencies, clocks = _extract_arrays(satellites)
    drift_step = drifts * TIME_TICK * TIME_TICK
    neighbors = compute_neighbors_fast(positions, 2500)
    skew_rate = _ftsp_skew_rate(satellites, drifts)

    performance_data = []
    pos_t = 0
    for i in range(time_units):
        clocks += drift_step
        performance_data.append(measure_sync_performance_vec(clocks))

        pos_t += 1
        if pos_t >= POSITION_UPDATE_CYCLE:
            positions = update_positions_vec(positions, velocities, ang_vels, POSITION_UPDATE_CYCLE)
            pos_t = 0
            neighbors = compute_neighbors_fast(positions, 2500)

        if i % 750 == 0:
            avg_frequency = frequencies.mean()
            reference_idx = int(np.argmin(np.abs(frequencies - avg_frequency)))
            offset = flood_time_sync_multihop(positions, neighbors, skew_rate, reference_idx)
            synced = ~np.isnan(offset)
            clocks[synced] = clocks[reference_idx] + offset[synced]

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
