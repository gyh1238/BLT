using System;
using System.Collections.Generic;

/// <summary>
/// Distance-dependent optical ISL availability, port of BLT_simul/model/blt_isl.py.
/// Pure C# (no UnityEngine) so it can run on a worker thread and be checked
/// against the Python model outside the editor (BLT_simul/tools/isl_parity.py).
///
/// Three layers:
///  1. Geometry: a link exists inside rangeKm when the ray clears the atmosphere.
///  2. Pointing fade: P_out(d) = (d / d_max)^k, k = (div/2)^2 / (2 jitter^2).
///     The range limit is where boresight power equals receiver sensitivity, so
///     margin is (d_max/d)^2; a Gaussian beam with Rayleigh pointing error loses
///     an exchange when the fade eats that margin.
///  3. Acquisition: a pair entering range is usable only acquisitionSec later.
/// Routes to the head minimise -ln(1 - P_out) + hopCost per hop.
/// </summary>
[Serializable]
public class IslLinkParams
{
    public double rangeKm           = 2500.0;  // paper
    public double divergenceFullRad = 20e-6;   // paper
    public double pointingJitterRad = 2e-6;    // assumed
    public double grazingAltitudeKm = 100.0;   // assumed
    public double acquisitionSec    = 30.0;    // assumed
    public double routeHopCost      = 0.01;    // design

    public double OutageExponent
    {
        get
        {
            double half = divergenceFullRad / 2.0;
            return half * half / (2.0 * pointingJitterRad * pointingJitterRad);
        }
    }
}

public static class IslLinkModel
{
    public const double EarthRadiusKm = 6371.0;

    public static double OutageProb(double distanceKm, IslLinkParams p)
    {
        double r = distanceKm / p.rangeKm;
        if (r >= 1.0) return 1.0;
        if (r <= 0.0) return 0.0;
        return Math.Pow(r, p.OutageExponent);
    }

    /// <summary>True when the straight ray a→b clears Earth plus the grazing altitude.</summary>
    public static bool LineOfSight(double ax, double ay, double az,
                                   double bx, double by, double bz, IslLinkParams p)
    {
        double sx = bx - ax, sy = by - ay, sz = bz - az;
        double s2 = sx * sx + sy * sy + sz * sz;
        double t = s2 > 0 ? -(ax * sx + ay * sy + az * sz) / s2 : 0.0;
        if (t < 0) t = 0; else if (t > 1) t = 1;
        double cx = ax + t * sx, cy = ay + t * sy, cz = az + t * sz;
        double floor = EarthRadiusKm + p.grazingAltitudeKm;
        return Math.Sqrt(cx * cx + cy * cy + cz * cz) >= floor;
    }

    /// <summary>
    /// Every pair (i &lt; j) inside the range with a clear ray, sorted by (i, j).
    /// pos holds x,y,z per satellite in km; entries with valid[i] == false are skipped.
    /// Uses a spatial hash with cells one range wide, so only 27 cells are scanned.
    /// </summary>
    public static void GeometricLinks(double[] pos, bool[] valid, int n, IslLinkParams p,
                                      out long[] keys, out double[] dist)
    {
        double cell = p.rangeKm;
        var grid = new Dictionary<long, List<int>>();
        var cx = new int[n]; var cy = new int[n]; var cz = new int[n];
        for (int i = 0; i < n; i++)
        {
            if (valid != null && !valid[i]) continue;
            cx[i] = (int)Math.Floor(pos[3 * i] / cell);
            cy[i] = (int)Math.Floor(pos[3 * i + 1] / cell);
            cz[i] = (int)Math.Floor(pos[3 * i + 2] / cell);
            long key = CellKey(cx[i], cy[i], cz[i]);
            if (!grid.TryGetValue(key, out var list)) grid[key] = list = new List<int>();
            list.Add(i);
        }

        var k = new List<long>();
        var d = new List<double>();
        double r2 = p.rangeKm * p.rangeKm;
        for (int i = 0; i < n; i++)
        {
            if (valid != null && !valid[i]) continue;
            double ax = pos[3 * i], ay = pos[3 * i + 1], az = pos[3 * i + 2];
            for (int dx = -1; dx <= 1; dx++)
            for (int dy = -1; dy <= 1; dy++)
            for (int dz = -1; dz <= 1; dz++)
            {
                if (!grid.TryGetValue(CellKey(cx[i] + dx, cy[i] + dy, cz[i] + dz), out var list))
                    continue;
                foreach (int j in list)
                {
                    if (j <= i) continue;
                    double ex = pos[3 * j] - ax, ey = pos[3 * j + 1] - ay, ez = pos[3 * j + 2] - az;
                    double dd = ex * ex + ey * ey + ez * ez;
                    if (dd >= r2) continue;
                    if (!LineOfSight(ax, ay, az, pos[3 * j], pos[3 * j + 1], pos[3 * j + 2], p))
                        continue;
                    k.Add((long)i * n + j);
                    d.Add(Math.Sqrt(dd));
                }
            }
        }
        keys = k.ToArray();
        dist = d.ToArray();
        Array.Sort(keys, dist);
    }

    static long CellKey(int x, int y, int z) =>
        ((long)(x + 512) << 20) | ((long)(y + 512) << 10) | (long)(z + 512);
}

/// <summary>Usable links as a compressed adjacency list with per-link outage.</summary>
public sealed class IslLinkGraph
{
    public readonly int N;
    public readonly long[] Keys;      // i*N + j, i < j, sorted
    public readonly double[] Dist;
    public readonly double[] POut;
    public readonly int[] Offsets;    // CSR over both directions
    public readonly int[] Neighbor;
    public readonly int[] EdgeOf;     // CSR slot -> index into Keys

    public IslLinkGraph(int n, long[] keys, double[] dist, IslLinkParams p)
    {
        N = n; Keys = keys; Dist = dist;
        POut = new double[keys.Length];
        var deg = new int[n + 1];
        for (int e = 0; e < keys.Length; e++)
        {
            POut[e] = IslLinkModel.OutageProb(dist[e], p);
            deg[(int)(keys[e] / n)]++;
            deg[(int)(keys[e] % n)]++;
        }
        Offsets = new int[n + 1];
        for (int i = 0; i < n; i++) Offsets[i + 1] = Offsets[i] + deg[i];
        Neighbor = new int[Offsets[n]];
        EdgeOf = new int[Offsets[n]];
        var fill = new int[n];
        Array.Copy(Offsets, fill, n);
        for (int e = 0; e < keys.Length; e++)
        {
            int i = (int)(keys[e] / n), j = (int)(keys[e] % n);
            Neighbor[fill[i]] = j; EdgeOf[fill[i]++] = e;
            Neighbor[fill[j]] = i; EdgeOf[fill[j]++] = e;
        }
    }
}

/// <summary>
/// Link set with acquisition hysteresis. Links present at the first update are up;
/// a link that appears later becomes usable acquisitionSec after it appeared; a link
/// that disappears is dropped at once.
/// </summary>
public sealed class IslLinkState
{
    long[] _keys;
    double[] _since;
    public int Acquiring { get; private set; }

    public IslLinkGraph Update(double[] pos, bool[] valid, int n, double tSec, IslLinkParams p)
    {
        IslLinkModel.GeometricLinks(pos, valid, n, p, out long[] keys, out double[] dist);
        var since = new double[keys.Length];
        for (int e = 0; e < keys.Length; e++)
        {
            if (_keys == null) { since[e] = double.NegativeInfinity; continue; }
            int at = Array.BinarySearch(_keys, keys[e]);
            since[e] = at >= 0 ? _since[at] : tSec;
        }
        _keys = keys; _since = since;

        int usable = 0;
        for (int e = 0; e < keys.Length; e++) if (tSec - since[e] >= p.acquisitionSec) usable++;
        Acquiring = keys.Length - usable;
        var uk = new long[usable]; var ud = new double[usable];
        for (int e = 0, u = 0; e < keys.Length; e++)
        {
            if (tSec - since[e] < p.acquisitionSec) continue;
            uk[u] = keys[e]; ud[u++] = dist[e];
        }
        return new IslLinkGraph(n, uk, ud, p);
    }
}

/// <summary>
/// Routes from a root over the nodes where member[v] is true (null = all nodes).
/// Parent[v] is the next hop toward the root, Depth[v] the hop count (-1 = no route),
/// PEdge[v] the outage of v's uplink.
/// </summary>
public sealed class IslRouteTree
{
    public readonly int Root;
    public readonly int[] Parent;
    public readonly int[] Depth;
    public readonly double[] PEdge;
    public int MaxDepth { get; private set; }
    readonly int[] _order;   // routed nodes sorted by depth

    public IslRouteTree(IslLinkGraph g, int root, bool[] member, double hopCost)
    {
        int n = g.N;
        Root = root;
        Parent = new int[n]; Depth = new int[n]; PEdge = new double[n];
        var cost = new double[n];
        var done = new bool[n];
        for (int v = 0; v < n; v++) { Parent[v] = -1; Depth[v] = -1; PEdge[v] = 1.0; cost[v] = double.PositiveInfinity; }
        cost[root] = 0; Depth[root] = 0; PEdge[root] = 0;

        var heap = new MinHeap();
        heap.Push(0.0, root);
        while (heap.Count > 0)
        {
            heap.Pop(out double c, out int u);
            if (done[u]) continue;
            done[u] = true;
            for (int s = g.Offsets[u]; s < g.Offsets[u + 1]; s++)
            {
                int v = g.Neighbor[s];
                if (done[v] || (member != null && !member[v])) continue;
                double pe = g.POut[g.EdgeOf[s]];
                if (pe >= 1.0) continue;
                double nc = c + (-Math.Log(1.0 - pe)) + hopCost;
                if (nc < cost[v])
                {
                    cost[v] = nc; Parent[v] = u; PEdge[v] = pe; Depth[v] = Depth[u] + 1;
                    heap.Push(nc, v);
                }
            }
        }

        var routed = new List<int>();
        for (int v = 0; v < n; v++) if (Depth[v] > 0) routed.Add(v);
        routed.Sort((a, b) => Depth[a].CompareTo(Depth[b]));
        _order = routed.ToArray();
        MaxDepth = _order.Length > 0 ? Depth[_order[_order.Length - 1]] : 0;
    }

    /// <summary>Expected route success per node (product of hop successes).</summary>
    public double[] PathSuccess()
    {
        var s = new double[Parent.Length];
        s[Root] = 1.0;
        foreach (int v in _order) s[v] = s[Parent[v]] * (1.0 - PEdge[v]);
        return s;
    }

    /// <summary>One round of exchanges; a failed relay fails its subtree.</summary>
    public void Draw(Random rng, bool[] reach)
    {
        Array.Clear(reach, 0, reach.Length);
        reach[Root] = true;
        foreach (int v in _order) reach[v] = reach[Parent[v]] && rng.NextDouble() >= PEdge[v];
    }

    sealed class MinHeap
    {
        readonly List<double> _k = new List<double>();
        readonly List<int> _v = new List<int>();
        public int Count => _k.Count;

        public void Push(double key, int value)
        {
            _k.Add(key); _v.Add(value);
            int i = _k.Count - 1;
            while (i > 0)
            {
                int parent = (i - 1) / 2;
                if (_k[parent] <= _k[i]) break;
                Swap(i, parent); i = parent;
            }
        }

        public void Pop(out double key, out int value)
        {
            key = _k[0]; value = _v[0];
            int last = _k.Count - 1;
            _k[0] = _k[last]; _v[0] = _v[last];
            _k.RemoveAt(last); _v.RemoveAt(last);
            int i = 0;
            while (true)
            {
                int l = 2 * i + 1, r = l + 1, m = i;
                if (l < _k.Count && _k[l] < _k[m]) m = l;
                if (r < _k.Count && _k[r] < _k[m]) m = r;
                if (m == i) break;
                Swap(i, m); i = m;
            }
        }

        void Swap(int a, int b)
        {
            double tk = _k[a]; _k[a] = _k[b]; _k[b] = tk;
            int tv = _v[a]; _v[a] = _v[b]; _v[b] = tv;
        }
    }
}
