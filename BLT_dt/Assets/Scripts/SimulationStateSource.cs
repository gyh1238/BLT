using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// The twin's link to the synchronization engine (BLT_simul/tools/rmse_server.py).
///
/// The twin builds the geometry itself -- it propagates real TLEs and derives the
/// ISL link set and routing from them (IslLinkManager, IslLinkModel) -- and takes
/// everything else from outside: the blocks from the chain (BlockchainPoller) and
/// the synchronization state from here. Without this the panels fell back to a sum
/// of three sines around 8.8 ns, which looks like the published curve but is not
/// the engine, and the clusters and faulty satellites on screen were decided in
/// Unity by nearest-centre and a shuffle, which is not what the engine ran either.
///
/// Two endpoints, polled at the rate each one changes:
///   GET /rmse   every rmseInterval  -> the live RMSE and the counters
///   GET /state  every stateInterval -> per-satellite cluster and faulty flag,
///                                      keyed by NORAD catalog number
///
/// Every reader is optional: if the server is not running, Connected stays false
/// and each panel keeps the behaviour it had before. Nothing in the scene needs
/// editing -- the component installs itself next to the MapManager.
/// </summary>
public class SimulationStateSource : MonoBehaviour
{
    public static SimulationStateSource Instance { get; private set; }

    [Header("Engine endpoint (BLT_simul/tools/rmse_server.py)")]
    public string endpoint = "http://127.0.0.1:8000";

    [Header("Poll intervals [s]")]
    [Tooltip("The RMSE moves every tick.")]
    public float rmseInterval = 0.5f;
    [Tooltip("The assignment only changes when the engine re-clusters.")]
    public float stateInterval = 6.0f;
    [Tooltip("Seconds to wait before trying again after a failed poll.")]
    public float retryInterval = 5.0f;

    /// <summary>True once a poll has succeeded and while polls keep succeeding.</summary>
    public bool  Connected     { get; private set; }
    public float RmseNs        { get; private set; }
    public int   Tick          { get; private set; }
    public int   Sats          { get; private set; }
    public int   FaultyCount   { get; private set; }
    public int   ClusterCount  { get; private set; }
    public float LocalCycleSec { get; private set; }

    /// <summary>Re-clustering counter from the engine; 0 until an assignment arrives.</summary>
    public int Epoch { get; private set; }

    /// <summary>Raised after a new assignment is taken, so views can rebuild.</summary>
    public static event Action AssignmentChanged;

    readonly Dictionary<string, int> _cluster = new Dictionary<string, int>();
    readonly HashSet<string>         _faulty  = new HashSet<string>();

    /// <summary>True when a per-satellite assignment has been received.</summary>
    public bool HasAssignment => _cluster.Count > 0;

    /// <summary>Cluster of one satellite by NORAD number, or false if the engine has no such satellite.</summary>
    public bool TryGetCluster(string norad, out int cluster)
    {
        cluster = -1;
        return norad != null && _cluster.TryGetValue(norad, out cluster);
    }

    /// <summary>Whether the engine degraded this satellite's oscillator.</summary>
    public bool IsFaulty(string norad) => norad != null && _faulty.Contains(norad);

    // ---------------------------------------------------------------- wire-up

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void AutoInstall()
    {
        if (FindObjectOfType<SimulationStateSource>() != null) return;
        if (FindObjectOfType<MapManager>() == null) return;
        new GameObject("SimulationStateSource").AddComponent<SimulationStateSource>();
    }

    void Awake()
    {
        if (Instance != null && Instance != this) { Destroy(this); return; }
        Instance = this;
    }

    void Start()
    {
        StartCoroutine(PollRmse());
        StartCoroutine(PollState());
    }

    // ---------------------------------------------------------------- polling

    IEnumerator PollRmse()
    {
        while (true)
        {
            bool ok = false;
            yield return Get("/rmse", json =>
            {
                var r = JsonUtility.FromJson<RmseReply>(json);
                if (r == null) return;
                RmseNs        = r.rmse_ns;
                Tick          = r.tick;
                Sats          = r.sats;
                FaultyCount   = r.faulty;
                ClusterCount  = r.clusters;
                LocalCycleSec = r.local_cycle_sec;
                ok = true;
            });
            Connected = ok;
            yield return new WaitForSeconds(ok ? rmseInterval : retryInterval);
        }
    }

    IEnumerator PollState()
    {
        while (true)
        {
            bool ok = false;
            yield return Get("/state", json =>
            {
                var r = JsonUtility.FromJson<StateReply>(json);
                if (r == null || r.norad == null || r.cluster == null) return;
                ok = true;
                if (r.epoch == Epoch) return;          // same assignment, nothing to rebuild
                _cluster.Clear();
                _faulty.Clear();
                int n = Mathf.Min(r.norad.Length, r.cluster.Length);
                for (int i = 0; i < n; i++)
                {
                    _cluster[r.norad[i]] = r.cluster[i];
                    if (r.faulty_mask != null && i < r.faulty_mask.Length && r.faulty_mask[i] != 0)
                        _faulty.Add(r.norad[i]);
                }
                Epoch = r.epoch;
                Debug.Log($"[SimState] assignment epoch {Epoch}: {n} satellites, " +
                          $"{_faulty.Count} degraded, {r.clusters} clusters");
                AssignmentChanged?.Invoke();
            });
            yield return new WaitForSeconds(ok ? stateInterval : retryInterval);
        }
    }

    IEnumerator Get(string path, Action<string> onBody)
    {
        using (var req = UnityWebRequest.Get(endpoint.TrimEnd('/') + path))
        {
            req.timeout = 3;
            yield return req.SendWebRequest();
#if UNITY_2020_1_OR_NEWER
            bool good = req.result == UnityWebRequest.Result.Success;
#else
            bool good = !req.isNetworkError && !req.isHttpError;
#endif
            if (!good) yield break;
            try { onBody(req.downloadHandler.text); }
            catch (Exception e) { Debug.LogWarning($"[SimState] {path}: {e.Message}"); }
        }
    }

    // JsonUtility needs the field names to match the JSON keys exactly.
    [Serializable] class RmseReply
    {
        public float rmse_ns; public int tick; public int sats;
        public int faulty; public int clusters; public float local_cycle_sec;
    }

    [Serializable] class StateReply
    {
        public int epoch; public int clusters;
        public string[] norad; public int[] cluster; public int[] faulty_mask;
    }
}
