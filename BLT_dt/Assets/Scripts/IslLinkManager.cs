using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Rendering;
using Zeptomoby.OrbitTools;

/// <summary>
/// Distance-dependent ISL availability in the digital twin (model: IslLinkModel.cs,
/// same as BLT_simul/model/blt_isl.py).
/// - Every updateInterval: propagate TLEs to ECI, rebuild usable links (with
///   acquisition hysteresis), route each member to its cluster head, and draw one
///   round of exchanges.
/// - Selected cluster: its routing tree is drawn on the 2D map, each uplink coloured
///   by outage probability; uplinks that failed this round are red.
/// - MonitorPanel reads Snapshot for member reach and connected heads.
/// Installs itself when a MapManager is in the scene; no scene edit is needed.
/// </summary>
public class IslLinkManager : MonoBehaviour
{
    public static IslLinkManager Instance { get; private set; }

    [Header("References")]
    public MapManager mapManager;

    [Header("Link model (paper: 2,500 km, 20 urad; rest assumed)")]
    public IslLinkParams parameters = new IslLinkParams();

    [Header("Update")]
    public float updateInterval = 3.5f;
    public int   clusterCount   = 12;
    public int   seed           = 7919;

    [Header("Map overlay")]
    public bool     drawSelectedCluster = true;
    public Material lineMaterial;
    public float    lineZ = -0.08f;
    public Color    colorGood = new Color(0.24f, 0.85f, 0.44f, 0.85f);  // P_out < 1%
    public Color    colorWeak = new Color(1f, 0.65f, 0.10f, 0.90f);     // 1% - 10%
    public Color    colorPoor = new Color(1f, 0.35f, 0.10f, 0.95f);     // >= 10%
    public Color    colorLost = new Color(1f, 0.15f, 0.15f, 1f);        // failed this round

    /// <summary>Result of one update. Arrays are indexed like MapManager._tleList.</summary>
    public sealed class LinkSnapshot
    {
        public DateTime Utc;
        public int Satellites, LinksUsable, LinksAcquiring;
        public int[] Cluster, Head, Parent, Depth;
        public double[] PEdge, RouteSuccess;
        public bool[] ReachedThisRound;
        public int[] ClusterMembers, ClusterReached, ClusterUnroutable;
        public bool[] HeadConnected;          // head has a route to the coordinator head
        public int HeadsConnected;
        public double MeanHops, ExpectedMemberLoss;
    }

    public LinkSnapshot Snapshot { get; private set; }
    public event Action<LinkSnapshot> Updated;

    readonly IslLinkState _state = new IslLinkState();
    System.Random _rng;
    Task<LinkSnapshot> _job;
    float _timer;
    DateTime _startUtc;
    GameObject _overlay;
    Mesh _mesh;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void AutoInstall()
    {
        if (FindObjectOfType<IslLinkManager>() != null) return;
        if (FindObjectOfType<MapManager>() == null) return;
        new GameObject("IslLinkManager").AddComponent<IslLinkManager>();
    }

    void Awake()
    {
        if (Instance != null && Instance != this) { Destroy(this); return; }
        Instance = this;
        _rng = new System.Random(seed);
        _startUtc = DateTime.UtcNow;
    }

    void OnEnable()  => ClusterSelector.OnClusterChanged += OnClusterChanged;
    void OnDisable() => ClusterSelector.OnClusterChanged -= OnClusterChanged;

    void Start()
    {
        if (mapManager == null) mapManager = FindObjectOfType<MapManager>();
        _overlay = new GameObject("IslLinkOverlay");
        _overlay.transform.SetParent(transform, false);
        _mesh = new Mesh { name = "IslLinks", indexFormat = IndexFormat.UInt32 };
        _overlay.AddComponent<MeshFilter>().sharedMesh = _mesh;
        var mr = _overlay.AddComponent<MeshRenderer>();
        // Sprites/Default honours vertex colour in the built-in pipeline.
        mr.sharedMaterial = lineMaterial != null ? lineMaterial : new Material(Shader.Find("Sprites/Default"));
        _timer = updateInterval;   // first update as soon as TLEs exist
    }

    void Update()
    {
        if (_job != null)
        {
            if (!_job.IsCompleted) return;
            if (_job.IsFaulted) Debug.LogWarning($"[IslLinkManager] update failed: {_job.Exception?.GetBaseException().Message}");
            else Apply(_job.Result);
            _job = null;
        }

        _timer += Time.deltaTime;
        if (_timer < updateInterval || mapManager == null || mapManager._tleList.Count == 0) return;
        _timer = 0f;

        // Snapshot inputs on the main thread; the job touches nothing Unity-owned.
        var tles = mapManager._tleList.ToArray();
        var cluster = new int[tles.Length];
        for (int i = 0; i < tles.Length; i++) cluster[i] = mapManager.GetSatClusterIdx(i);
        var utc = DateTime.UtcNow;   // MapManager propagates at UtcNow as well
        double tSec = (utc - _startUtc).TotalSeconds;
        var p = parameters;
        int k = clusterCount;
        var rng = _rng;
        var state = _state;
        _job = Task.Run(() => Compute(tles, cluster, utc, tSec, p, k, rng, state));
    }

    static LinkSnapshot Compute(Tle[] tles, int[] cluster, DateTime utc, double tSec,
                                IslLinkParams p, int k, System.Random rng, IslLinkState state)
    {
        int n = tles.Length;
        var pos = new double[3 * n];
        var valid = new bool[n];
        for (int i = 0; i < n; i++)
        {
            try
            {
                var sat = new Satellite(tles[i]);
                double mpe = utc.Subtract(tles[i].EpochJulian.ToTime()).TotalMinutes;
                var eci = sat.PositionEci(mpe);
                double x = eci.Position.X, y = eci.Position.Y, z = eci.Position.Z;
                double alt = Math.Sqrt(x * x + y * y + z * z) - IslLinkModel.EarthRadiusKm;
                // Same plausibility band as BLT_simul's TLE loader: SGP4 past a
                // TLE's validity returns positions inside the Earth, not NaN.
                valid[i] = !double.IsNaN(x) && alt >= 200.0 && alt <= 2000.0 && cluster[i] >= 0 && cluster[i] < k;
                pos[3 * i] = x; pos[3 * i + 1] = y; pos[3 * i + 2] = z;
            }
            catch { valid[i] = false; }
        }

        var g = state.Update(pos, valid, n, tSec, p);
        var snap = new LinkSnapshot
        {
            Utc = utc, Satellites = n, LinksUsable = g.Keys.Length, LinksAcquiring = state.Acquiring,
            Cluster = cluster, Head = new int[k], Parent = new int[n], Depth = new int[n],
            PEdge = new double[n], RouteSuccess = new double[n], ReachedThisRound = new bool[n],
            ClusterMembers = new int[k], ClusterReached = new int[k], ClusterUnroutable = new int[k],
            HeadConnected = new bool[k],
        };
        for (int i = 0; i < n; i++) { snap.Parent[i] = -1; snap.Depth[i] = -1; snap.PEdge[i] = 1.0; }

        // Head = valid member nearest its cluster centroid (same rule as the simulator).
        var sum = new double[3 * k];
        for (int i = 0; i < n; i++)
        {
            if (!valid[i]) continue;
            int c = cluster[i];
            snap.ClusterMembers[c]++;
            sum[3 * c] += pos[3 * i]; sum[3 * c + 1] += pos[3 * i + 1]; sum[3 * c + 2] += pos[3 * i + 2];
        }
        for (int c = 0; c < k; c++)
        {
            snap.Head[c] = -1;
            if (snap.ClusterMembers[c] == 0) continue;
            double best = double.PositiveInfinity;
            double mx = sum[3 * c] / snap.ClusterMembers[c], my = sum[3 * c + 1] / snap.ClusterMembers[c], mz = sum[3 * c + 2] / snap.ClusterMembers[c];
            for (int i = 0; i < n; i++)
            {
                if (!valid[i] || cluster[i] != c) continue;
                double dx = pos[3 * i] - mx, dy = pos[3 * i + 1] - my, dz = pos[3 * i + 2] - mz;
                double d2 = dx * dx + dy * dy + dz * dz;
                if (d2 < best) { best = d2; snap.Head[c] = i; }
            }
        }

        var member = new bool[n];
        var reach = new bool[n];
        double hopSum = 0, lossSum = 0; int routed = 0;
        for (int c = 0; c < k; c++)
        {
            int h = snap.Head[c];
            if (h < 0) continue;
            for (int i = 0; i < n; i++) member[i] = valid[i] && cluster[i] == c;
            var tree = new IslRouteTree(g, h, member, p.routeHopCost);
            var succ = tree.PathSuccess();
            tree.Draw(rng, reach);
            for (int i = 0; i < n; i++)
            {
                if (!member[i]) continue;
                snap.Parent[i] = tree.Parent[i]; snap.Depth[i] = tree.Depth[i];
                snap.PEdge[i] = tree.PEdge[i]; snap.RouteSuccess[i] = succ[i];
                snap.ReachedThisRound[i] = reach[i];
                if (reach[i]) snap.ClusterReached[c]++;
                if (i == h) continue;
                if (tree.Depth[i] < 0) { snap.ClusterUnroutable[c]++; continue; }
                routed++; hopSum += tree.Depth[i]; lossSum += 1.0 - succ[i];
            }
        }
        snap.MeanHops = routed > 0 ? hopSum / routed : 0;
        snap.ExpectedMemberLoss = routed > 0 ? lossSum / routed : 0;

        // Head network: can every head reach the coordinator head over any relays?
        int coord = Array.FindIndex(snap.Head, h => h >= 0);
        if (coord >= 0)
        {
            var global = new IslRouteTree(g, snap.Head[coord], valid, p.routeHopCost);
            for (int c = 0; c < k; c++)
            {
                snap.HeadConnected[c] = snap.Head[c] >= 0 && global.Depth[snap.Head[c]] >= 0;
                if (snap.HeadConnected[c]) snap.HeadsConnected++;
            }
        }
        return snap;
    }

    void Apply(LinkSnapshot snap)
    {
        Snapshot = snap;
        Updated?.Invoke(snap);
        RebuildOverlay();
    }

    void OnClusterChanged(int idx) => RebuildOverlay();

    void RebuildOverlay()
    {
        if (_mesh == null) return;
        _mesh.Clear();
        var snap = Snapshot;
        int sel = ClusterSelector.Instance != null ? ClusterSelector.Instance.SelectedIndex : -1;
        if (!drawSelectedCluster || snap == null || sel < 0 || mapManager == null) return;

        var ll = mapManager._latLonList;
        var verts = new List<Vector3>();
        var cols = new List<Color>();
        var idx = new List<int>();
        for (int i = 0; i < snap.Satellites && i < ll.Count; i++)
        {
            int par = snap.Parent[i];
            if (snap.Cluster[i] != sel || par < 0 || par >= ll.Count) continue;
            Vector2 a = ll[i], b = ll[par];
            if (Mathf.Abs(a.y - b.y) > 180f) continue;   // skip segments across the date line
            Color col = !snap.ReachedThisRound[i] && snap.ReachedThisRound[par] ? colorLost
                      : snap.PEdge[i] < 0.01 ? colorGood
                      : snap.PEdge[i] < 0.10 ? colorWeak : colorPoor;
            idx.Add(verts.Count); verts.Add(mapManager.LatLonToWorld(a.x, a.y, lineZ)); cols.Add(col);
            idx.Add(verts.Count); verts.Add(mapManager.LatLonToWorld(b.x, b.y, lineZ)); cols.Add(col);
        }
        _mesh.SetVertices(verts);
        _mesh.SetColors(cols);
        _mesh.SetIndices(idx, MeshTopology.Lines, 0);
        _mesh.RecalculateBounds();
    }
}
