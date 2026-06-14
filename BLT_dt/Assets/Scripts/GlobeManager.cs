using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using Zeptomoby.OrbitTools;

public class GlobeManager : MonoBehaviour
{
    [Header("References")]
    public Transform  globeSphere;
    public MapManager mapManager;

    [Header("Orbit ring")]
    public Material orbitRingMaterial;
    public Color    orbitRingColor  = new Color(0.4f, 0.8f, 1f, 0.5f);
    public float    orbitRingRadius = 5.5f;
    public int      orbitPoints     = 120;

    [Header("Cluster circle")]
    public Material clusterCircleMaterial;
    public Color    clusterCircleColor    = new Color(1f, 0.85f, 0.3f, 0.8f);
    public float    clusterAngularRadius  = 22f;   // degrees
    public int      clusterCount         = 12;
    public int      clusterPoints        = 80;
    public float    clusterRadius        = 5.45f;  // sphere surface

    [Header("Satellite dot")]
    public GameObject satDotPrefab;
    public float      satDotRadius = 5.6f;
    public float      satDotScale  = 0.08f;

    // ── Shared cluster centers (read by MapManager to draw 2D ellipses) ──
    public static List<Vector3> ClusterCenters = new List<Vector3>();

    private List<LineRenderer> _orbitRings     = new List<LineRenderer>();
    private List<LineRenderer> _clusterCircles = new List<LineRenderer>();
    private List<Transform>    _satDots        = new List<Transform>();

    void Start()
    {
        ComputeClusterCenters();
        // DrawOrbitRings();   // Orbit ring disabled
        DrawClusterCircles();
        StartCoroutine(WaitAndUpdateSats());
    }

    void Update()
    {
        UpdateSatDots();
    }

    // ── Compute cluster centers (golden spiral — evenly across the globe) ──
    void ComputeClusterCenters()
    {
        ClusterCenters.Clear();
        float golden = Mathf.PI * (3f - Mathf.Sqrt(5f));

        for (int i = 0; i < clusterCount; i++)
        {
            // y: -0.85 ~ +0.85 (excluding polar regions, actual satellite distribution)
            float y   = 1f - (i / (float)(clusterCount - 1)) * 2f;
            y        *= 0.85f;
            float r2  = Mathf.Sqrt(1f - y * y);
            float phi = golden * i;
            ClusterCenters.Add(new Vector3(
                r2 * Mathf.Cos(phi),
                y,
                r2 * Mathf.Sin(phi)).normalized);
        }
    }

    // ── Orbit ring ───────────────────────────────────────────────
    void DrawOrbitRings()
    {
        foreach (var g in _orbitRings) if (g) Destroy(g.gameObject);
        _orbitRings.Clear();

        float[] incs   = { 53f, 53.2f, 70f, 97.6f };
        float[] phases = { 0f, 45f, 20f, 80f };

        for (int ri = 0; ri < incs.Length; ri++)
        {
            var lr = MakeLine("OrbitRing_" + ri, orbitRingColor, 0.04f, orbitPoints, true);
            float inc   = incs[ri]   * Mathf.Deg2Rad;
            float phase = phases[ri] * Mathf.Deg2Rad;
            var pts = new Vector3[orbitPoints];
            for (int i = 0; i < orbitPoints; i++)
            {
                float t  = i / (float)orbitPoints * Mathf.PI * 2f;
                float ox = Mathf.Cos(t);
                float oy = Mathf.Sin(t) * Mathf.Cos(inc);
                float oz = Mathf.Sin(t) * Mathf.Sin(inc);
                float rx = ox * Mathf.Cos(phase) - oz * Mathf.Sin(phase);
                float rz = ox * Mathf.Sin(phase) + oz * Mathf.Cos(phase);
                pts[i]   = new Vector3(rx, oy, rz) * orbitRingRadius;
            }
            lr.SetPositions(pts);
            _orbitRings.Add(lr);
        }
    }

    // ── Draw cluster circles ────────────────────────────────────
    void DrawClusterCircles()
    {
        foreach (var g in _clusterCircles) if (g) Destroy(g.gameObject);
        _clusterCircles.Clear();

        foreach (var center in ClusterCenters)
        {
            var lr = MakeLine("ClusterCircle", clusterCircleColor, 0.06f, clusterPoints, true);
            DrawSmallCircle(lr, center, clusterAngularRadius, clusterRadius);
            _clusterCircles.Add(lr);
        }
    }

    // ── Small circle on the sphere ──────────────────────────────────────────
    void DrawSmallCircle(LineRenderer lr, Vector3 c, float angDeg, float radius)
    {
        float r  = angDeg * Mathf.Deg2Rad;
        Vector3 b1 = Vector3.Cross(c, Vector3.up).normalized;
        if (b1.magnitude < 0.01f) b1 = Vector3.Cross(c, Vector3.right).normalized;
        Vector3 b2 = Vector3.Cross(c, b1).normalized;
        var pts = new Vector3[clusterPoints];
        for (int i = 0; i < clusterPoints; i++)
        {
            float t = i / (float)clusterPoints * Mathf.PI * 2f;
            Vector3 pt = Mathf.Cos(r) * c
                       + Mathf.Sin(r) * (Mathf.Cos(t) * b1 + Mathf.Sin(t) * b2);
            pts[i] = pt.normalized * radius;
        }
        lr.SetPositions(pts);
    }

    // ── Satellite dot ───────────────────────────────────────────────
    IEnumerator WaitAndUpdateSats()
    {
        yield return new WaitForSeconds(2f);
    }

    void UpdateSatDots()
    {
        if (satDotPrefab == null || mapManager == null) return;
        var lls = mapManager._latLonList;
        if (lls == null) return;

        while (_satDots.Count < lls.Count)
        {
            var go = Instantiate(satDotPrefab, globeSphere != null ? globeSphere : transform);
            go.layer = LayerMask.NameToLayer("GlobeLayer");
            float _gsScale = (globeSphere != null) ? globeSphere.lossyScale.x : 1f;
            go.transform.localScale = Vector3.one * (satDotScale / _gsScale);
            _satDots.Add(go.transform);
        }

        for (int i = 0; i < lls.Count && i < _satDots.Count; i++)
        {
            if (_satDots[i] == null) continue;
            // Compensate by dividing by globeSphere's scale (if Globe3D scale=10, then /10)
            float gsScale = (globeSphere != null) ? globeSphere.lossyScale.x : 1f;
            _satDots[i].localPosition = LatLonToSphere(lls[i].x, lls[i].y) * (satDotRadius / gsScale);
        }
    }

    // ── LineRenderer creation helper ────────────────────────────────
    LineRenderer MakeLine(string name, Color col, float width, int count, bool loop)
    {
        var go = new GameObject(name);
        go.layer = LayerMask.NameToLayer("GlobeLayer");
        go.transform.SetParent(globeSphere != null ? globeSphere : transform);
        var lr = go.AddComponent<LineRenderer>();
        lr.material = clusterCircleMaterial != null
            ? clusterCircleMaterial
            : new Material(Shader.Find("Unlit/Color"));
        lr.startColor = col; lr.endColor = col;
        lr.startWidth = width; lr.endWidth = width;
        lr.positionCount = count;
        lr.loop = loop;
        lr.useWorldSpace = false;
        return lr;
    }

    // ── Lat/Lon → sphere vector ───────────────────────────────────
    public static Vector3 LatLonToSphere(float lat, float lon)
    {
        float latR = lat * Mathf.Deg2Rad;
        float lonR = lon * Mathf.Deg2Rad;
        return new Vector3(
            Mathf.Cos(latR) * Mathf.Cos(lonR),
            Mathf.Sin(latR),
            Mathf.Cos(latR) * Mathf.Sin(lonR));
    }

    // ── satDots accessor for FaultySatelliteManager ─────────────
    public List<Transform> GetSatDots() => _satDots;

    // ── [Phase2] Apply cluster filter ──────────────────────────
    // ClusterSelector.OnClusterChanged → ClusterSelector → called here
    public void ApplyClusterFilter(int selectedIdx)
    {
        bool all = selectedIdx < 0;

        for (int i = 0; i < _clusterCircles.Count; i++)
        {
            if (_clusterCircles[i] == null) continue;
            bool  active = all || i == selectedIdx;
            Color col    = active
                ? ClusterSelector.ColorGlobeSel
                : ClusterSelector.ColorGlobeDim;
            _clusterCircles[i].startColor = col;
            _clusterCircles[i].endColor   = col;
            // Make the selected circle slightly thicker
            float w = active ? 0.09f : 0.04f;
            _clusterCircles[i].startWidth = w;
            _clusterCircles[i].endWidth   = w;
        }
    }
}

