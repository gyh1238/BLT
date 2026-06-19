using System.Collections;
using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// Draws a real-time RMSE graph onto the RawImage inside Cell_RMSE
/// - X axis: time (last 60 seconds)
/// - Y axis: RMSE (ns), 0 ~ yMax
/// - Yellow reference line: 10ns (ISL requirement)
/// - Orange warning line:  8ns (entering DEGRADED)
///
/// Hierarchy:
///   Cell_RMSE > GraphImage (RawImage) ← rawImage reference
/// Manager_Root > RmseGraphPanel (this)
/// </summary>
public class RmseGraphPanel : MonoBehaviour
{
    [Header("References")]
    public MonitorPanel monitorPanel;
    public RawImage     graphImage;      // Cell_RMSE > GraphImage

    [Header("Graph Settings")]
    public float updateInterval = 0.5f; // sample period (seconds)
    public int   bufferSize     = 120;  // sample count (120 × 0.5s = 60 seconds)
    public float yMax           = 15f;  // Y axis maximum (ns)
    public float yMin           = 0f;

    [Header("Reference Lines")]
    public float limitLine  = 10f;  // ISL requirement (yellow line)
    public float warnLine   = 8f;   // warning threshold (orange line)

    // ── Colors ─────────────────────────────────────────────────
    private static readonly Color32 BG         = new Color32(  3, 12, 24, 255); // #030c18
    private static readonly Color32 GRID       = new Color32( 10, 58,110,  60); // #0a3a6e dim
    private static readonly Color32 LINE_LIMIT = new Color32(255,159, 28, 200); // #ff9f1c yellow line
    private static readonly Color32 LINE_WARN  = new Color32(255,159, 28,  90); // orange semi-transparent
    private static readonly Color32 LINE_GRAPH = new Color32(  0,180,255, 255); // #00b4ff
    private static readonly Color32 FILL_GRAPH = new Color32(  0,180,255,  35); // fill semi-transparent
    private static readonly Color32 LABEL_OK   = new Color32(  0,200,122, 255); // #00c87a
    private static readonly Color32 LABEL_WARN = new Color32(255,159, 28, 255); // #ff9f1c

    // ── Internal ─────────────────────────────────────────────────
    private float[]   _buffer;
    private int       _head   = 0;    // ring buffer head
    private int       _count  = 0;    // current number of filled samples
    private Texture2D _tex;
    private Color32[] _pixels;
    private int       _texW, _texH;

    void Start()
    {
        _buffer = new float[bufferSize];

        // pre-fill: same formula as real-time, based on past time
        float interval = updateInterval;
        for (int i = 0; i < bufferSize; i++)
        {
            float t = (i - bufferSize) * interval; // negative = past
            _buffer[i] = RmseWave(t);
        }
        _head  = 0;
        _count = bufferSize;

        // create texture using the RawImage size
        if (graphImage == null) { Debug.LogError("[RmseGraphPanel] GraphImage not connected"); return; }
        var rect = graphImage.rectTransform.rect;
        _texW = Mathf.Max(1, Mathf.RoundToInt(rect.width));
        _texH = Mathf.Max(1, Mathf.RoundToInt(rect.height));

        // fall back to defaults if the size cannot be read
        if (_texW < 4) _texW = 480;
        if (_texH < 4) _texH = 260;

        _tex    = new Texture2D(_texW, _texH, TextureFormat.RGBA32, false);
        _tex.filterMode = FilterMode.Bilinear;
        _pixels = new Color32[_texW * _texH];
        graphImage.texture = _tex;

        StartCoroutine(SampleLoop());
    }

    // ── Sample collection loop ────────────────────────────────────────
    IEnumerator SampleLoop()
    {
        while (true)
        {
            // Prefer the real network RMSE (chain-driven via MonitorPanel); fall
            // back to the synthetic wave only when no live value is available.
            float rmse = (monitorPanel != null && monitorPanel.rmseNs > 0f)
                ? monitorPanel.rmseNs
                : RmseWave(Time.time);
            _buffer[_head] = rmse;
            _head = (_head + 1) % bufferSize;
            if (_count < bufferSize) _count++;
            Redraw();
            yield return new WaitForSeconds(updateInterval);
        }
    }

    // ── Graph redraw ──────────────────────────────────────
    void Redraw()
    {
        for (int i = 0; i < _pixels.Length; i++) _pixels[i] = BG;

        for (float ns = 0f; ns <= yMax; ns += 5f)
            DrawHLine(NsToY(ns), GRID);

        DrawHLine(NsToY(warnLine),  LINE_WARN);
        DrawHLine(NsToY(limitLine), LINE_LIMIT);

        if (_count > 1)
        {
            for (int xi = 0; xi < _count; xi++)
            {
                int   bufIdx = (_head - _count + xi + bufferSize) % bufferSize;
                float val    = _buffer[bufIdx];
                int   px     = Mathf.RoundToInt((float)xi / (bufferSize - 1) * (_texW - 1));
                int   py     = NsToY(val);

                for (int fy = 0; fy <= py && fy < _texH; fy++)
                    BlendPixel(px, fy, FILL_GRAPH);

                if (xi > 0)
                {
                    int prevIdx = (_head - _count + xi - 1 + bufferSize) % bufferSize;
                    int px0     = Mathf.RoundToInt((float)(xi - 1) / (bufferSize - 1) * (_texW - 1));
                    int py0     = NsToY(_buffer[prevIdx]);
                    DrawLine(px0, py0, px, py, LINE_GRAPH);
                }
            }
        }

        DrawHLine(NsToY(limitLine), LINE_LIMIT);
        _tex.SetPixels32(_pixels);
        _tex.Apply(false);
    }

    // ── Y coordinate conversion ────────────────────────────────────────────
    int NsToY(float ns)
    {
        float t = Mathf.InverseLerp(yMin, yMax, ns);
        return Mathf.Clamp(Mathf.RoundToInt(t * (_texH - 1)), 0, _texH - 1);
    }

    // ── Horizontal line ────────────────────────────────────────────────
    void DrawHLine(int py, Color32 col)
    {
        if (py < 0 || py >= _texH) return;
        for (int x = 0; x < _texW; x++)
            _pixels[py * _texW + x] = col;
    }

    // ── Bresenham line ────────────────────────────────────────
    void DrawLine(int x0, int y0, int x1, int y1, Color32 col)
    {
        int dx =  Mathf.Abs(x1 - x0), sx = x0 < x1 ? 1 : -1;
        int dy = -Mathf.Abs(y1 - y0), sy = y0 < y1 ? 1 : -1;
        int err = dx + dy;
        while (true)
        {
            SetPixel(x0, y0, col);
            // line thickness +1
            SetPixel(x0, y0 + 1, col);
            if (x0 == x1 && y0 == y1) break;
            int e2 = 2 * err;
            if (e2 >= dy) { err += dy; x0 += sx; }
            if (e2 <= dx) { err += dx; y0 += sy; }
        }
    }

    void SetPixel(int x, int y, Color32 col)
    {
        if (x < 0 || x >= _texW || y < 0 || y >= _texH) return;
        _pixels[y * _texW + x] = col;
    }

    void BlendPixel(int x, int y, Color32 src)
    {
        if (x < 0 || x >= _texW || y < 0 || y >= _texH) return;
        int   idx = y * _texW + x;
        Color32 dst = _pixels[idx];
        float a = src.a / 255f;
        _pixels[idx] = new Color32(
            (byte)(src.r * a + dst.r * (1 - a)),
            (byte)(src.g * a + dst.g * (1 - a)),
            (byte)(src.b * a + dst.b * (1 - a)),
            255);
    }

    void OnDestroy()
    {
        if (_tex != null) Destroy(_tex);
    }

    // ── Shared RMSE wave formula ────────────────────────────────
    // pre-fill and real-time use the same formula → continuous graph
    static float RmseWave(float t)
    {
        return 8.8f
            + Mathf.Sin(t * 0.29f) * 0.30f
            + Mathf.Sin(t * 0.71f) * 0.14f
            + Mathf.Sin(t * 1.37f) * 0.06f;
    }
}
