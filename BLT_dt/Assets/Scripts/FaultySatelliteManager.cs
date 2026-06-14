using System.Collections;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Faulty satellite visualization
/// - Randomly designates satellites equal to MonitorPanel.faultyNodes (fixed per session)
/// - 2D map: red ring + blinking on the corresponding satellite
/// - 3D globe: changes the corresponding satellite dot to red
/// Add this to Manager_Root
/// </summary>
public class FaultySatelliteManager : MonoBehaviour
{
    [Header("References")]
    public MapManager   mapManager;
    public MonitorPanel monitorPanel;
    public GlobeManager globeManager;

    [Header("2D Ring Settings")]
    public Material ringMaterial;       // Unlit/Color material (red)
    public float    ringRadius  = 0.06f;
    public int      ringPoints  = 24;
    public float    blinkSpeed  = 2.5f; // Blink period

    [Header("Fault Ratio")]
    [Range(0f, 0.5f)]
    public float faultyRatio = 0.03f;  // Fault ratio relative to total satellites (3%)

    // ── Internal ─────────────────────────────────────────────────
    private List<int>          _faultyIndices = new List<int>();
    private List<LineRenderer> _rings         = new List<LineRenderer>();

    // Color
    private static readonly Color RING_COLOR = new Color(1f, 0.2f, 0.2f, 1f); // Red

    void Start()
    {
        StartCoroutine(InitWhenReady());
    }

    IEnumerator InitWhenReady()
    {
        // Wait for MapManager satellite spawn to complete
        yield return new WaitForSeconds(3f);

        if (mapManager == null || mapManager.SatTransforms == null ||
            mapManager.SatTransforms.Count == 0) yield break;

        AssignFaultySatellites();
        CreateRings();
        ColorGlobeDots();
        StartCoroutine(BlinkLoop());
    }

    // ── Random faulty satellite designation ──────────────────────────────────
    // Returns the list of faulty satellite indices (for MonitorPanel)
    public System.Collections.Generic.IEnumerable<int> GetFaultyIndices()
        => _faultyIndices;

    void AssignFaultySatellites()
    {
        _faultyIndices.Clear();
        int total  = mapManager.SatTransforms.Count;
        // Determine fault count as total satellite count × faultyRatio
        int fCount = Mathf.Max(1, Mathf.RoundToInt(total * faultyRatio));
        fCount = Mathf.Clamp(fCount, 0, total);
        // Reflect the actual fault count in MonitorPanel
        if (monitorPanel != null) monitorPanel.faultyNodes = fCount;

        // Reproducible random (fixed per session)
        var rng     = new System.Random(42);
        var indices = new List<int>();
        for (int i = 0; i < total; i++) indices.Add(i);

        // After Fisher-Yates shuffle, select the first fCount entries
        for (int i = indices.Count - 1; i > 0; i--)
        {
            int j   = rng.Next(0, i + 1);
            int tmp = indices[i]; indices[i] = indices[j]; indices[j] = tmp;
        }
        for (int i = 0; i < fCount; i++)
            _faultyIndices.Add(indices[i]);

        Debug.Log($"[FaultySat] Designated {fCount} faulty satellites: {string.Join(", ", _faultyIndices)}");
    }

    // ── 2D map ring creation ────────────────────────────────────────
    void CreateRings()
    {
        foreach (var lr in _rings) if (lr != null) Destroy(lr.gameObject);
        _rings.Clear();

        foreach (int idx in _faultyIndices)
        {
            if (idx >= mapManager.SatTransforms.Count) continue;
            var satT = mapManager.SatTransforms[idx];
            if (satT == null) continue;

            var go = new GameObject($"FaultyRing_{idx}");
            go.transform.SetParent(mapManager.satelliteContainer);

            var lr  = go.AddComponent<LineRenderer>();
            // Sprites/Default: supports LineRenderer vertex color in Built-In RP
            var mat = ringMaterial != null
                ? ringMaterial
                : new Material(Shader.Find("Sprites/Default"));
            lr.material = mat;
            lr.startColor    = RING_COLOR;
            lr.endColor      = RING_COLOR;
            lr.startWidth    = 0.015f;
            lr.endWidth      = 0.015f;
            lr.positionCount = ringPoints + 1;
            lr.loop          = false;
            lr.useWorldSpace = true;

            UpdateRingPosition(lr, satT.position);
            _rings.Add(lr);
        }
    }

    // ── Ring position update ─────────────────────────────────────────
    void UpdateRingPosition(LineRenderer lr, Vector3 center)
    {
        for (int i = 0; i <= ringPoints; i++)
        {
            float angle = i / (float)ringPoints * Mathf.PI * 2f;
            lr.SetPosition(i, new Vector3(
                center.x + Mathf.Cos(angle) * ringRadius,
                center.y + Mathf.Sin(angle) * ringRadius,
                center.z - 0.02f));  // In front of the satellite
        }
    }

    // ── Add red dots on globe faulty satellites ──────────────────
    void ColorGlobeDots()
    {
        if (globeManager == null) return;
        var dots = globeManager.GetSatDots();
        if (dots == null) return;

        foreach (int idx in _faultyIndices)
        {
            if (idx >= dots.Count) continue;
            var dot = dots[idx];
            if (dot == null) continue;

            // Place a red sphere on top of the faulty satellite
            var marker = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            marker.name = $"GlobeFaultyMarker_{idx}";
            Destroy(marker.GetComponent<Collider>());

            marker.transform.SetParent(dot);
            marker.transform.localPosition = Vector3.zero;
            // Marker size proportional to dot size
            marker.transform.localScale = Vector3.one * 2.5f;

            var rend = marker.GetComponent<Renderer>();
            var mat  = new Material(Shader.Find("Sprites/Default"));
            mat.color = new Color(1f, 0.15f, 0.15f, 1f);
            rend.material = mat;

            // Layer Settings (the layer that GlobeCamera sees)
            marker.layer = dot.gameObject.layer;
        }
    }

    // ── Blink loop ──────────────────────────────────────────
    IEnumerator BlinkLoop()
    {
        while (true)
        {
            float t     = Time.time * blinkSpeed;
            float alpha = (Mathf.Sin(t) * 0.5f + 0.5f); // 0~1 sine wave
            alpha = Mathf.Lerp(0.2f, 1f, alpha);

            Color col = new Color(RING_COLOR.r, RING_COLOR.g, RING_COLOR.b, alpha);

            for (int i = 0; i < _rings.Count; i++)
            {
                var lr = _rings[i];
                if (lr == null) continue;

                // Since satellites move, update ring positions every frame too
                if (i < _faultyIndices.Count)
                {
                    int idx = _faultyIndices[i];
                    if (idx < mapManager.SatTransforms.Count &&
                        mapManager.SatTransforms[idx] != null)
                        UpdateRingPosition(lr, mapManager.SatTransforms[idx].position);
                }

                lr.startColor = col;
                lr.endColor   = col;
            }

            yield return null; // Every frame
        }
    }
}
