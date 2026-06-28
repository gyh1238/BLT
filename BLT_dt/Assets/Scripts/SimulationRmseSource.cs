using System.Collections;
using System.Globalization;
using System.IO;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// Supplies the DT's BLT-SAND network RMSE from the BLT_simul simulation —
/// independent of the chain — with two sources, preferred in this order:
///
///   1. LIVE  : poll the real-time RMSE server (BLT_simul/rmse_server.py) over
///              HTTP. The server steps the actual BLT-SAND sync simulation in
///              wall-clock time and returns the current network RMSE. This is
///              the same UnityWebRequest polling pattern the DT already uses for
///              the Tendermint RPC (:26657).
///   2. FILE  : when no server is reachable, replay the exported steady-state
///              curve from StreamingAssets/blt_rmse_timeseries.txt (paper Fig.5a)
///              as a seamless loop. This is the no-connection fallback.
///
/// Mode = Auto (default) uses LIVE when the server answers and automatically
/// drops to FILE when it stops; Mode = FilePlayback never polls.
///
/// Resolution order for any reading: LIVE value if connected, else FILE loop,
/// else 0 (callers then use their own synthetic fallback).
/// </summary>
public class SimulationRmseSource : MonoBehaviour
{
    public enum Mode { Auto, FilePlayback }

    [Header("Source")]
    public Mode mode = Mode.Auto;

    [Header("Live server (HTTP)")]
    public string serverUrl     = "http://localhost:8000/rmse";
    public float  pollInterval  = 0.5f;   // seconds between polls
    public float  liveTimeoutSec = 2f;    // no OK poll within this → disconnected
    public float  liveSmoothing = 8f;     // lerp speed toward the latest live value

    [Header("File fallback")]
    public string fileName = "blt_rmse_timeseries.txt";

    // ── Public state ────────────────────────────────────────────
    public bool  Loaded    { get; private set; }   // FILE data available
    public bool  IsLive    { get; private set; }   // LIVE server answering
    public bool  Available => IsLive || Loaded;
    public int   LiveTick  { get; private set; }
    public float CurrentRmseNs => IsLive ? _displayLive : SampleSecondsAgo(0f);

    // ── File playback ───────────────────────────────────────────
    private float[] _vals;
    private float   _intervalSec = 0.05f;
    private float   _durationSec;

    // ── Live polling ────────────────────────────────────────────
    private float _liveRmse;        // latest raw value from server
    private float _displayLive;     // smoothed value actually shown
    private float _lastLiveOkTime = -999f;

    [System.Serializable] class RmseMsg { public float rmse_ns; public long tick; }

    void Awake()
    {
        LoadFile();
        if (mode == Mode.Auto)
            StartCoroutine(PollLive());
    }

    void Update()
    {
        if (IsLive)
            _displayLive = Mathf.Lerp(_displayLive, _liveRmse,
                                      Time.deltaTime * liveSmoothing);
    }

    // ── LIVE: poll the real-time RMSE server ────────────────────
    IEnumerator PollLive()
    {
        while (true)
        {
            using (var req = UnityWebRequest.Get(serverUrl))
            {
                req.timeout = 2;
                yield return req.SendWebRequest();

                if (req.result == UnityWebRequest.Result.Success)
                {
                    RmseMsg msg = null;
                    try { msg = JsonUtility.FromJson<RmseMsg>(req.downloadHandler.text); }
                    catch { msg = null; }

                    if (msg != null && msg.rmse_ns > 0f)
                    {
                        _liveRmse = msg.rmse_ns;
                        LiveTick  = (int)msg.tick;
                        if (!IsLive) _displayLive = _liveRmse;  // snap on (re)connect
                        _lastLiveOkTime = Time.time;
                        IsLive = true;
                    }
                }
            }

            if (IsLive && Time.time - _lastLiveOkTime > liveTimeoutSec)
                IsLive = false;   // server went away → fall back to FILE

            yield return new WaitForSeconds(pollInterval);
        }
    }

    // ── FILE: load the exported playback curve ──────────────────
    void LoadFile()
    {
        // Desktop (Windows/Mac/Linux): StreamingAssets is a plain directory, so a
        // direct file read is enough. (Android would need UnityWebRequest because
        // StreamingAssets lives inside the APK — not supported here.)
        string path = Path.Combine(Application.streamingAssetsPath, fileName);
        string text = File.Exists(path) ? File.ReadAllText(path) : null;

        if (string.IsNullOrEmpty(text))
        {
            Debug.LogWarning($"[SimulationRmseSource] {fileName} not found → FILE fallback inactive");
            return;
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
            Debug.LogWarning("[SimulationRmseSource] not enough samples → FILE fallback inactive");
            return;
        }

        _vals        = vals.ToArray();
        _durationSec = _vals.Length * _intervalSec;
        Loaded       = true;
        Debug.Log($"[SimulationRmseSource] FILE loaded {_vals.Length} samples, " +
                  $"{_durationSec:F1}s loop @ {_intervalSec * 1000f:F0}ms");
    }

    /// <summary>
    /// RMSE (ns) at <paramref name="secondsAgo"/> before now, used to pre-fill the
    /// graph history. Always samples the FILE loop (the live server has no past);
    /// returns the live value if no file is loaded, else 0.
    /// </summary>
    public float SampleSecondsAgo(float secondsAgo)
    {
        if (Loaded)
            return SampleAtPhase(Time.time - secondsAgo);
        return IsLive ? _displayLive : 0f;
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
