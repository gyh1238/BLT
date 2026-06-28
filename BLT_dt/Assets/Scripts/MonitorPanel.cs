using System.Collections;
using UnityEngine;
using UnityEngine.Networking;
using TMPro;

/// <summary>
/// BLT-SAND real-time monitoring panel
/// 0: Network RMSE   1: Global Sync
/// 2: Active Clusters 3: Faulty Nodes
/// 4: Block Interval  5: Local Cycle
/// </summary>
public class MonitorPanel : MonoBehaviour
{
    [Header("References")]
    public MapManager mapManager;   // Used to query cluster member count
    public BltChainPoller bltPoller; // x/blt chain data (cluster count, sync state)
    public SimulationRmseSource rmseSource; // BLT_simul RMSE curve (Fig.5a playback)

    [Header("RPC Settings")]
    public string rpcEndpoint  = "http://localhost:26657";
    public float  pollInterval = 3.5f;

    [Header("Cell Value Text (0~5)")]
    public TextMeshProUGUI[] valueTexts;
    public TextMeshProUGUI[] labelTexts;  // Label TMP (optional)

    [Header("Simulation values (temporary)")]
    public float rmseNs         = 8.8f;
    public int   activeClusters = 12;
    public int   faultyNodes    = 3;
    public float localCycleSec  = 2.7f;

    // ── Public properties (referenced by MissionStatusBar) ──────
    public bool IsSynced => _synced;

    // Selected cluster state
    private int _selectedCluster = -1;  // -1 = ALL

    // Internal
    private float  _lastBlockTime = 0f;
    private long   _lastHeight    = 0;
    private float  _blockInterval = 3.5f;
    private bool   _synced        = true;

    [System.Serializable] class StatusResp   { public StatusResult result; }
    [System.Serializable] class StatusResult { public SyncInfo sync_info; }
    [System.Serializable] class SyncInfo
    {
        public string latest_block_height;
        public string catching_up;
    }

    void OnEnable()  => ClusterSelector.OnClusterChanged += OnClusterChanged;
    void OnDisable() => ClusterSelector.OnClusterChanged -= OnClusterChanged;

    void OnClusterChanged(int idx)
    {
        _selectedCluster = idx;
        UpdateUI();  // Refresh immediately
    }

    void Start() => StartCoroutine(PollLoop());

    IEnumerator PollLoop()
    {
        while (true)
        {
            yield return StartCoroutine(FetchStatus());
            UpdateUI();
            yield return new WaitForSeconds(pollInterval);
        }
    }

    IEnumerator FetchStatus()
    {
        using var req = UnityWebRequest.Get(rpcEndpoint + "/status");
        req.timeout = 5;
        yield return req.SendWebRequest();
        if (req.result != UnityWebRequest.Result.Success) yield break;

        var resp = JsonUtility.FromJson<StatusResp>(req.downloadHandler.text);
        if (resp?.result == null) yield break;

        _synced = resp.result.sync_info.catching_up != "true";

        if (long.TryParse(resp.result.sync_info.latest_block_height, out long h))
        {
            if (_lastHeight > 0 && h > _lastHeight)
            {
                float now = Time.realtimeSinceStartup;
                if (_lastBlockTime > 0)
                    _blockInterval = (now - _lastBlockTime) / (h - _lastHeight);
                _lastBlockTime = now;
            }
            _lastHeight = h;
        }

        // RMSE comes from the BLT_simul simulation curve (paper Fig.5a), replayed
        // by SimulationRmseSource — independent of the chain. Fall back to the
        // local fluctuation formula only when the simulation data is unavailable.
        if (rmseSource != null && rmseSource.Loaded)
            rmseNs = rmseSource.CurrentRmseNs;
        else
            rmseNs = 8.8f
                + Mathf.Sin(Time.time * 0.29f) * 0.30f
                + Mathf.Sin(Time.time * 0.71f) * 0.14f
                + Mathf.Sin(Time.time * 1.37f) * 0.06f;

        // Cluster count is still a chain (x/blt) quantity when connected.
        if (bltPoller != null && bltPoller.Connected && bltPoller.ClusterCount > 0)
            activeClusters = bltPoller.ClusterCount;
    }

    void UpdateUI()
    {
        if (valueTexts == null || valueTexts.Length < 6) return;

        var green  = new Color(0.24f, 0.85f, 0.44f);
        var orange = new Color(1f, 0.65f, 0.1f);
        var cyan   = new Color(0f, 0.706f, 1f);
        var white  = Color.white;
        var dim    = new Color(0.48f, 0.78f, 0.89f);

        // ── Fixed 3: always shown (regardless of cluster) ─────────────────
        // 0: Network RMSE
        Set(0, rmseNs.ToString("F1") + " ns",
            rmseNs < 10f ? green : orange);
        // 4: Block Interval
        Set(4, _blockInterval.ToString("F1") + " s", white);
        // 5: Local Cycle
        Set(5, localCycleSec.ToString("F1") + " s", white);

        // ── Variable 3: switch between ALL / cluster mode ───────────────────────
        if (_selectedCluster >= 0)
        {
            int memberCount   = mapManager != null
                ? mapManager.GetClusterMemberCount(_selectedCluster) : 0;
            int clusterFaulty = CountClusterFaulty(_selectedCluster);
            float faultyRatio = memberCount > 0
                ? (float)clusterFaulty / memberCount * 100f : 0f;

            // 1: Cluster ID
            SetLabel(1, "Cluster");
            Set(1, $"C-{_selectedCluster + 1:D2}", cyan);
            // 2: Cluster satellite count
            SetLabel(2, "Members");
            Set(2, $"{memberCount} sats", white);
            // 3: Cluster faulty ratio
            SetLabel(3, "Faulty");
            Set(3, $"{clusterFaulty}  ({faultyRatio:F1}%)",
                clusterFaulty > 0 ? orange : green);
        }
        else
        {
            // 1: Global Sync
            SetLabel(1, "Global Sync");
            Set(1, _synced ? "OK" : "Catch up",
                _synced ? green : orange);
            // 2: Active Clusters
            SetLabel(2, "Active Clusters");
            Set(2, activeClusters + " / 12", white);
            // 3: Faulty Nodes
            SetLabel(3, "Faulty Nodes");
            Set(3, faultyNodes.ToString(),
                faultyNodes > 0 ? orange : green);
        }
    }

    // Count faulty satellites within the selected cluster
    int CountClusterFaulty(int clusterIdx)
    {
        if (mapManager == null) return 0;
        // Get faulty satellite indices from FaultySatelliteManager and filter by cluster
        var fsm = FindObjectOfType<FaultySatelliteManager>();
        if (fsm == null) return 0;
        int count = 0;
        foreach (int idx in fsm.GetFaultyIndices())
        {
            if (mapManager.GetSatClusterIdx(idx) == clusterIdx)
                count++;
        }
        return count;
    }

    void SetLabel(int i, string text)
    {
        if (labelTexts == null || i >= labelTexts.Length || labelTexts[i] == null) return;
        labelTexts[i].text = text;
    }

    void Set(int i, string text, Color color)
    {
        if (i >= valueTexts.Length || valueTexts[i] == null) return;
        valueTexts[i].text  = text;
        valueTexts[i].color = color;
    }
}
