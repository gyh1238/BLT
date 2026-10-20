"""Distance-dependent optical ISL availability: when a link degrades and when it breaks.

The paper states 2.5 W, 1,550 nm and 20 urad, and those numbers set exactly one
thing: the 2,500 km range. Every protocol then treated any pair inside that range
as a perfect link and any pair outside it as nonexistent. A real optical link
does neither. It closes with less and less margin as the range grows, so it
starts dropping exchanges well before the limit, and a pair that comes back into
range is not usable until its terminals re-acquire each other.

Three layers, each from one physical argument:

1. **Geometry (hard).** A link exists only if the pair is inside the range limit
   and the ray between them clears the atmosphere (``isl_grazing_altitude_km``).

2. **Pointing fade (per exchange).** The range limit is where the received power
   at perfect pointing just equals the receiver sensitivity, that is what a
   range derived from transmit power, wavelength and divergence means. Received
   power falls as 1/d^2, so the margin at range d is

       M(d) = (d_max / d)^2.

   A Gaussian beam of 1/e^2 half-width w = divergence/2 delivers a fraction
   exp(-2 theta^2 / w^2) of its peak at pointing error theta. With a per-axis RMS
   pointing error sigma, theta is Rayleigh distributed and the exchange fails when
   the fade eats the margin:

       P_out(d) = P[ exp(-2 theta^2 / w^2) < 1/M(d) ] = (d / d_max)^k,
       k = w^2 / (2 sigma^2).

   One exponent, no free scale: at d = d_max every exchange fails, at d = 0 none
   does, and the jitter decides how sharp the knee is. At the defaults (20 urad,
   2 urad) k = 12.5. Jitter is kHz and an exchange lasts milliseconds, so
   successive exchanges fade independently.

3. **Acquisition (hysteresis).** A pair that newly enters range becomes usable
   only ``isl_acquisition_s`` later. A link that leaves range is lost at once.

Routing. Cluster diameters in a 12-cluster global shell are ~8,000 km, so members
reach their head over 1-3 ISL hops, not directly. Each
member's route minimises -ln(1 - P_out) plus a per-hop cost (``isl_route_hop_cost``)
-- without that cost the most reliable route chains 7-20 short links, and a
relay's failure takes down everything behind it in the same round, because the
routes form a tree.

Nothing here reads a random stream unless the engine enables the model, so runs
with ``main_all.ISL_LINK_MODEL = False`` are bit-identical to before.
"""

from __future__ import annotations

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

import blt_params as params

EARTH_RADIUS_KM = 6371.0


# ---------------------------------------------------------------------------
# Per-link physics
# ---------------------------------------------------------------------------

def outage_exponent(overrides=None) -> float:
    """k = w^2 / (2 sigma^2), with w the 1/e^2 half-width of the beam."""
    half = params.value('isl_divergence_full_rad', overrides) / 2.0
    sigma = params.value('isl_pointing_jitter_rad', overrides)
    return half * half / (2.0 * sigma * sigma)


def exchange_outage_prob(distance_km, overrides=None):
    """Probability that one exchange over a link of this length fails."""
    d_max = params.value('isl_range_km', overrides)
    r = np.asarray(distance_km, dtype=float) / d_max
    out = np.power(np.clip(r, 0.0, 1.0), outage_exponent(overrides))
    return np.where(r >= 1.0, 1.0, out)


def line_of_sight(p_a, p_b, overrides=None):
    """True where the straight ray between the two positions clears the
    atmosphere. Positions in km, Earth-centred."""
    p_a = np.atleast_2d(np.asarray(p_a, dtype=float))
    p_b = np.atleast_2d(np.asarray(p_b, dtype=float))
    seg = p_b - p_a
    seg2 = np.einsum('ij,ij->i', seg, seg)
    safe = np.where(seg2 > 0, seg2, 1.0)
    t = np.where(seg2 > 0, -np.einsum('ij,ij->i', p_a, seg) / safe, 0.0)
    t = np.clip(t, 0.0, 1.0)
    closest = p_a + t[:, None] * seg
    floor = EARTH_RADIUS_KM + params.value('isl_grazing_altitude_km', overrides)
    return np.linalg.norm(closest, axis=1) >= floor


def geometric_links(positions, overrides=None):
    """Every pair (i < j) inside the range limit with a clear ray.

    Returns (i, j, distance_km)."""
    positions = np.asarray(positions, dtype=float)
    d_max = params.value('isl_range_km', overrides)
    pairs = cKDTree(positions).query_pairs(r=d_max, output_type='ndarray')
    if len(pairs) == 0:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty, np.zeros(0)
    i, j = pairs[:, 0].astype(np.int64), pairs[:, 1].astype(np.int64)
    d = np.linalg.norm(positions[i] - positions[j], axis=1)
    keep = (d < d_max) & line_of_sight(positions[i], positions[j], overrides)
    order = np.lexsort((j[keep], i[keep]))
    return i[keep][order], j[keep][order], d[keep][order]


# ---------------------------------------------------------------------------
# Routing trees
# ---------------------------------------------------------------------------

class RouteTree:
    """Most-reliable routes from one root to a set of nodes.

    ``parent[v]`` is the next hop toward the root (-1 at the root and at nodes
    with no route), ``depth[v]`` the hop count (-1 when unreachable) and
    ``p_edge[v]`` the outage probability of the link from v to its parent.
    Arrays are indexed by global satellite id.
    """

    def __init__(self, n, root, nodes, i, j, p, hop_cost):
        self.root = int(root)
        self.parent = np.full(n, -1, dtype=np.int64)
        self.depth = np.full(n, -1, dtype=np.int64)
        self.p_edge = np.ones(n)

        nodes = np.asarray(nodes, dtype=np.int64)
        local = np.full(n, -1, dtype=np.int64)
        local[nodes] = np.arange(len(nodes))
        inside = (local[i] >= 0) & (local[j] >= 0) & (p < 1.0)
        li, lj, lp = local[i[inside]], local[j[inside]], p[inside]
        m = len(nodes)
        rows = np.concatenate([li, lj])
        cols = np.concatenate([lj, li])
        # The hop cost also keeps a zero-outage edge from vanishing as a sparse zero.
        w = -np.log1p(-lp) + hop_cost
        graph = coo_matrix((np.concatenate([w, w]), (rows, cols)), shape=(m, m)).tocsr()
        root_local = int(local[self.root])
        _, pred = dijkstra(graph, directed=False, indices=root_local,
                           return_predecessors=True)
        reached = pred >= 0

        self.parent[nodes[reached]] = nodes[pred[reached]]
        self.depth[self.root] = 0
        self.p_edge[self.root] = 0.0

        # Hop depth by relaxation; trees here are a few hops deep.
        pending = nodes[reached]
        while len(pending):
            ready = self.depth[self.parent[pending]] >= 0
            if not ready.any():
                break
            v = pending[ready]
            self.depth[v] = self.depth[self.parent[v]] + 1
            pending = pending[~ready]

        # Outage of each node's uplink, looked up from the edge list.
        pmat = coo_matrix((np.concatenate([lp, lp]), (rows, cols)), shape=(m, m)).tocsr()
        v_local = np.flatnonzero(reached)
        if len(v_local):
            self.p_edge[nodes[v_local]] = np.asarray(
                pmat[v_local, pred[v_local]]).ravel()

    @property
    def max_depth(self) -> int:
        return int(self.depth.max())

    def draw(self, rng) -> np.ndarray:
        """One round of exchanges along the tree. True where the node's whole
        route to the root succeeded. A failed relay fails its subtree."""
        ok = rng.random(len(self.parent)) >= self.p_edge
        reach = np.zeros(len(self.parent), dtype=bool)
        reach[self.root] = True
        for d in range(1, self.max_depth + 1):
            v = np.flatnonzero(self.depth == d)
            reach[v] = reach[self.parent[v]] & ok[v]
        return reach

    def path_success(self) -> np.ndarray:
        """Expected route success per node (product of hop successes)."""
        succ = np.zeros(len(self.parent))
        succ[self.root] = 1.0
        for d in range(1, self.max_depth + 1):
            v = np.flatnonzero(self.depth == d)
            succ[v] = succ[self.parent[v]] * (1.0 - self.p_edge[v])
        return succ


# ---------------------------------------------------------------------------
# Constellation link state
# ---------------------------------------------------------------------------

def cluster_heads(positions, cluster_idx_list):
    """Head = member nearest its cluster centroid (same rule as
    main_all.cluster_head_graph, repeated so this module has no engine import)."""
    heads = []
    for idxs in cluster_idx_list:
        c = positions[idxs]
        heads.append(int(idxs[np.argmin(((c - c.mean(axis=0)) ** 2).sum(axis=1))]))
    return heads


class LinkModel:
    """Link availability for one run, updated whenever positions change."""

    def __init__(self, n, rng, overrides=None):
        self.n = int(n)
        self.rng = rng
        self.overrides = overrides
        self._keys = None
        self._since = None
        self.stats = {'local_attempts': 0, 'local_lost': 0,
                      'head_attempts': 0, 'head_lost': 0,
                      'flood_attempts': 0, 'flood_lost': 0,
                      'acquiring': [], 'unroutable': [], 'hops': [],
                      'flood_unreached': []}

    #, topology ------------------------------------------------------------
    def update(self, positions, cluster_idx_list, t_s):
        positions = np.asarray(positions, dtype=float)
        i, j, d = geometric_links(positions, self.overrides)
        keys = i * self.n + j
        if self._keys is None:
            since = np.full(len(keys), -np.inf)      # every link is up at start
        elif len(self._keys) == 0:
            since = np.full(len(keys), float(t_s))   # nothing was up: all new
        else:
            pos = np.minimum(np.searchsorted(self._keys, keys), len(self._keys) - 1)
            found = self._keys[pos] == keys
            since = np.where(found, self._since[pos], float(t_s))
        self._keys, self._since = keys, since
        usable = (float(t_s) - since) >= params.value('isl_acquisition_s', self.overrides)
        self.stats['acquiring'].append(int((~usable).sum()))

        self.i, self.j, self.d = i[usable], j[usable], d[usable]
        self.p = exchange_outage_prob(self.d, self.overrides)

        self.cluster_idx_list = cluster_idx_list
        self.heads = cluster_heads(positions, cluster_idx_list)
        self.hop_cost = params.value('isl_route_hop_cost', self.overrides)
        self.local_trees = [RouteTree(self.n, h, idxs, self.i, self.j, self.p, self.hop_cost)
                            for h, idxs in zip(self.heads, cluster_idx_list)]
        depths = np.concatenate([t.depth[idxs] for t, idxs
                                 in zip(self.local_trees, cluster_idx_list)])
        self.stats['unroutable'].append(int((depths < 0).sum()))
        self.stats['hops'].append(depths[depths > 0])
        self._global_trees = {}
        self._pair_p = None
        self._neighbors = None

    @property
    def neighbors(self):
        """Usable-link adjacency, built on first use (only FTSP needs it)."""
        if self._neighbors is None:
            nbrs = [[] for _ in range(self.n)]
            for a, b in zip(self.i.tolist(), self.j.tolist()):
                nbrs[a].append(b)
                nbrs[b].append(a)
            self._neighbors = dict(enumerate(nbrs))
            self._pair_p = dict(zip((self.i * self.n + self.j).tolist(), self.p.tolist()))
        return self._neighbors

    #, per round -----------------------------------------------------------
    def local_reach(self):
        """Members whose exchange with their own head succeeded this round."""
        reach = np.zeros(self.n, dtype=bool)
        for tree, idxs in zip(self.local_trees, self.cluster_idx_list):
            r = tree.draw(self.rng)
            reach[idxs] = r[idxs]
            self.stats['local_attempts'] += len(idxs) - 1
            self.stats['local_lost'] += int((~r[idxs]).sum())
        return reach

    def head_reach(self, root_cluster):
        """Per cluster: whether its head exchanged with the head of
        ``root_cluster`` this round, over any satellites as relays."""
        root = self.heads[root_cluster]
        tree = self._global_trees.get(root)
        if tree is None:
            tree = RouteTree(self.n, root, np.arange(self.n), self.i, self.j, self.p,
                             self.hop_cost)
            self._global_trees[root] = tree
        got = tree.draw(self.rng)[np.array(self.heads)]
        self.stats['head_attempts'] += len(self.heads) - 1
        self.stats['head_lost'] += int((~got).sum())
        return got

    def flood_delivers(self, a, b):
        """One FTSP transmission from a to b."""
        if self._pair_p is None:
            self.neighbors  # builds the pair table
        p = self._pair_p.get(min(a, b) * self.n + max(a, b), 1.0)
        self.stats['flood_attempts'] += 1
        lost = self.rng.random() < p
        self.stats['flood_lost'] += int(lost)
        return not lost

    def summary(self) -> dict:
        s = self.stats

        def rate(lost, att):
            return lost / att if att else float('nan')
        hops = np.concatenate(s['hops']) if s['hops'] else np.zeros(0)
        return {
            'local_loss': rate(s['local_lost'], s['local_attempts']),
            'head_loss': rate(s['head_lost'], s['head_attempts']),
            # Per transmission, counting every neighbour a relay tried. Most of
            # it is redundant: the node is usually delivered by another relay.
            'flood_loss': rate(s['flood_lost'], s['flood_attempts']),
            # What a flood actually failed to deliver.
            'flood_unreached': (float(np.mean(s['flood_unreached']))
                                if s['flood_unreached'] else float('nan')),
            'acquiring_links_mean': float(np.mean(s['acquiring'])) if s['acquiring'] else 0.0,
            'unroutable_members_mean': float(np.mean(s['unroutable'])) if s['unroutable'] else 0.0,
            'member_hops_mean': float(hops.mean()) if len(hops) else float('nan'),
            'member_hops_max': int(hops.max()) if len(hops) else 0,
        }


if __name__ == '__main__':
    k = outage_exponent()
    print(f"outage exponent k = {k:.2f}  (divergence "
          f"{params.value('isl_divergence_full_rad') * 1e6:.0f} urad, jitter "
          f"{params.value('isl_pointing_jitter_rad') * 1e6:.1f} urad)")
    for dist in (500, 1000, 1250, 1500, 1750, 2000, 2250, 2400, 2500, 2600):
        print(f"  {dist:5d} km  P_out = {float(exchange_outage_prob(dist)):.4f}")
