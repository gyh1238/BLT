using System.Collections;
using System.Globalization;
using System.IO;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// Plays back the BLT-SAND network RMSE produced by the offline BLT_simul
/// synchronization-accuracy simulation (paper Fig. 5a, BLT-SAND curve).
///
/// The simulation cannot run inside Unity (heavy Python: 16 runs × 60000 ticks ×
/// 500 satellites), so its committed output curve is exported to
/// StreamingAssets/blt_rmse_timeseries.txt and replayed here in real time. The
/// data is the genuine steady-state segment (2 cluster cycles of 6 s) with the
/// exact paper transform already applied (bc·UNIT_SCALE, EMA span=1250 + centered
/// window), so the DT shows the real simulated 6 s cluster-sync sawtooth instead
/// of a fabricated waveform. This is intentionally independent of the chain — the
/// RMSE comes from the simulation, not from x/blt.
///
/// File format (see the file header):
///   '#' comment lines; one carries "sample_interval_sec: &lt;v&gt;"
///   then one RMSE value (ns) per line.
///
/// CurrentRmseNs and SampleSecondsAgo() loop the segment with circular linear
/// interpolation (the exported window's endpoints match to ~0.02 ns, so the loop
/// seam is invisible).
/// </summary>
public class SimulationRmseSource : MonoBehaviour
{
    [Header("Data")]
    public string fileName = "blt_rmse_timeseries.txt";

    [Header("Playback")]
    [Tooltip("1 = real-time (1 simulated second per real second)")]
    public float playbackSpeed = 1f;

    public bool  Loaded        { get; private set; }
    public float CurrentRmseNs => SampleSecondsAgo(0f);

    private float[] _vals;
    private float   _intervalSec = 0.05f;  // overwritten from header
    private float   _durationSec;

    void Awake() => StartCoroutine(Load());

    IEnumerator Load()
    {
        string path = Path.Combine(Application.streamingAssetsPath, fileName);
        string text = null;

        // On most platforms StreamingAssets is a plain path; on Android it lives
        // inside the APK and must be read via UnityWebRequest. Handle both.
        if (path.Contains("://"))
        {
            using var req = UnityWebRequest.Get(path);
            yield return req.SendWebRequest();
            if (req.result == UnityWebRequest.Result.Success)
                text = req.downloadHandler.text;
        }
        else if (File.Exists(path))
        {
            text = File.ReadAllText(path);
        }

        if (string.IsNullOrEmpty(text))
        {
            Debug.LogWarning($"[SimulationRmseSource] {fileName} not found → RMSE source inactive");
            yield break;
        }

        var vals = new List<float>();
        foreach (var raw in text.Split('\n'))
        {
            var line = raw.Trim();
            if (line.Length == 0) continue;
            if (line[0] == '#')
            {
                int k = line.IndexOf("sample_interval_sec:");
                if (k >= 0 && float.TryParse(line.Substring(k + 20).Trim(),
                        NumberStyles.Float, CultureInfo.InvariantCulture, out float iv) && iv > 0)
                    _intervalSec = iv;
                continue;
            }
            if (float.TryParse(line, NumberStyles.Float, CultureInfo.InvariantCulture, out float v))
                vals.Add(v);
        }

        if (vals.Count < 2)
        {
            Debug.LogWarning("[SimulationRmseSource] not enough samples → inactive");
            yield break;
        }

        _vals        = vals.ToArray();
        _durationSec = _vals.Length * _intervalSec;
        Loaded       = true;
        Debug.Log($"[SimulationRmseSource] loaded {_vals.Length} samples, " +
                  $"{_durationSec:F1}s loop @ {_intervalSec * 1000f:F0}ms");
    }

    /// <summary>
    /// RMSE (ns) at <paramref name="secondsAgo"/> before now. 0 = current value,
    /// positive = into the past (used to pre-fill the graph history). Loops the
    /// segment with circular linear interpolation.
    /// </summary>
    public float SampleSecondsAgo(float secondsAgo)
    {
        if (!Loaded) return 0f;
        float t = Time.time * playbackSpeed - secondsAgo;
        return SampleAtPhase(t);
    }

    private float SampleAtPhase(float tSec)
    {
        float phase = Mod(tSec, _durationSec);
        float fpos  = phase / _intervalSec;
        int   i0    = Mathf.FloorToInt(fpos);
        float frac  = fpos - i0;
        int   a     = ((i0 % _vals.Length) + _vals.Length) % _vals.Length;
        int   b     = (a + 1) % _vals.Length;   // wraps → seamless loop
        return Mathf.Lerp(_vals[a], _vals[b], frac);
    }

    private static float Mod(float x, float m) => ((x % m) + m) % m;
}
