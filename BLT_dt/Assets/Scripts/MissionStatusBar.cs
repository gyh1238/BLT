using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TMPro;

/// <summary>
/// BLT-SAND Mission Control top status bar (2 lines)
///
/// Line 1: BLT-SAND MISSION CONTROL  |  leo_chain-1  |  MET 003:12:31:48  |  UTC 2026-001 · 12:31:48
/// Line 2: ●×12  |  BLK #17911338  |  RND #4832  |  RMSE 6.0 ns  |  SYNC NOMINAL  |  CLUSTERS 12/12  |  FAULTY 3
///
/// Hierarchy:
///   Canvas > StatusBar > Line1BG > Line1Text
///                      > Line2BG > Line2Text
/// </summary>
public class MissionStatusBar : MonoBehaviour
{
    // ── References ─────────────────────────────────────────────────
    [Header("Data source")]
    public BlockchainPoller blockchainPoller;
    public MapManager        mapManager;    // For displaying total satellite count
    public MonitorPanel     monitorPanel;
    public ClusterSelector  clusterSelector;

    [Header("UI text")]
    public TextMeshProUGUI line1Text;
    public TextMeshProUGUI line2Text;

    [Header("Settings")]
    public float updateInterval      = 0.5f;  // Refresh interval (seconds)
    public int   dotCount            = 12;   // Number of block status dots
    public float metStartOffsetSec   = 0f;    // Auto-set from blockchain height*6s
    public float secPerBlock         = 6f;    // Time per block (seconds)
    bool         _metOffsetSet       = false;
    [Tooltip("Hook: when true, BLK TIME shows the chain's real block timestamp " +
             "(BlockchainPoller.LatestBlockTime) instead of the simulated mission clock.")]
    public bool  useChainBlockTime   = false;

    // ── Colors (hex for TMP rich text) ──────────────────────────
    const string C_ACCENT  = "00b4ff";  // Cyan — accent
    const string C_TEXT    = "7ec8e3";  // Light blue-white — default
    const string C_OK      = "00c87a";  // Green — nominal
    const string C_WARN    = "ff9f1c";  // Orange — warning
    const string C_DIM     = "2a4a6a";  // Dark blue — dim

    // ── Internal state ────────────────────────────────────────────
    private System.DateTime _appStartUtc;
    private Queue<float>    _blockArrivalTimes = new Queue<float>(); // Arrival times of the last 12 blocks
    private long            _lastKnownHeight   = 0;
    private string          _cachedBlkTime     = "--:--:--";
    private string          _cachedProposer    = "SAT-?";
    private float           _simBlockTimer     = 0f;
    public  float           simBlockInterval   = 3.5f;  // Simulation block interval (seconds)
    private long            _simBlockHeight    = 17901829L;  // Simulation block height
    private long            _roundNumber       = 0;  // blockHeight ≈ round

    void Start()
    {
        _appStartUtc = System.DateTime.UtcNow;
        // BLK TIME initial value (shown until the first block arrives)
        _cachedBlkTime  = System.DateTime.UtcNow.AddSeconds(-4f).ToString("HH:mm:ss");
        _cachedProposer = $"SAT-{UnityEngine.Random.Range(40000, 69999):D5}";
        StartCoroutine(UpdateLoop());
    }

    IEnumerator UpdateLoop()
    {
        while (true)
        {
            Refresh();
            yield return new WaitForSeconds(updateInterval);
        }
    }

    void Refresh()
    {
        TrackBlockArrival();
        if (line1Text) line1Text.text = BuildLine1();
        if (line2Text) line2Text.text = BuildLine2();
    }

    // ── Block arrival tracking (for dot status) ───────────────────────────
    void TrackBlockArrival()
    {
        // When the blockchain is not connected, generate a virtual block every simBlockInterval
        _simBlockTimer += updateInterval;
        if (GetLatestHeight() <= 0 && _simBlockTimer >= simBlockInterval)
        {
            _simBlockTimer = 0f;
            _simBlockHeight++;
            OnNewBlock(_simBlockHeight);
        }

        long h = GetLatestHeight();
        // Auto-set the MET offset when the first height is received
        if (!_metOffsetSet && h > 0)
        {
            metStartOffsetSec = h * secPerBlock;
            _metOffsetSet = true;
        }
        if (h > _lastKnownHeight)
        {
            _blockArrivalTimes.Enqueue(Time.realtimeSinceStartup);
            while (_blockArrivalTimes.Count > dotCount)
                _blockArrivalTimes.Dequeue();
            _lastKnownHeight = h;
            _roundNumber     = h;

            // Block creation time = current SimulatedUtc - 3~5 seconds (propagation delay simulation)
            float delay = UnityEngine.Random.Range(3f, 5f);
            var blkUtc = (mapManager != null ? mapManager.SimulatedUtcNow : System.DateTime.UtcNow)
                         .AddSeconds(-delay);
            _cachedBlkTime  = blkUtc.ToString("HH:mm:ss");
            // Proposer: actual value when the blockchain is connected, random satellite ID when not connected
            if (blockchainPoller != null)
                _cachedProposer = blockchainPoller.LatestProposer;
            else
                _cachedProposer = $"SAT-{UnityEngine.Random.Range(40000, 69999):D5}";
        }
    }

    // ── Build Line 1 ──────────────────────────────────────────
    string BuildLine1()
    {
        string met   = FormatMET();
        string utc   = FormatUTC();
        string chain = GetChainId();
        int    sats  = mapManager != null ? mapManager.SatTransforms.Count : 0;
        string satStr = sats > 0
            ? $"SATS  <color=#{C_ACCENT}>{sats:N0}</color>"
            : "";

        string sep = $"<color=#{C_DIM}>   │   </color>";
        string line = $"<color=#{C_ACCENT}><b>BLT-SAND MISSION CONTROL</b></color>" +
            sep + $"<color=#{C_TEXT}>{chain}</color>" +
            sep + $"<color=#{C_TEXT}>MET  </color><color=#{C_ACCENT}>{met}</color>" +
            sep + $"<color=#{C_TEXT}>UTC  </color><color=#{C_ACCENT}>{utc}</color>";
        if (sats > 0)
            line += sep + $"<color=#{C_TEXT}>{satStr}</color>";
        return line;
    }

    // ── Build Line 2 ──────────────────────────────────────────
    string BuildLine2()
    {
        string dots     = BuildDots();
        string blk      = $"BLK <color=#{C_ACCENT}>#{GetLatestHeight()}</color>";
        string rnd      = $"RND <color=#{C_ACCENT}>#{GetLatestHeight() + 1}</color>";
        string epoch    = BuildEpoch();  // BLK TIME
        string proposer = BuildProposer();
        string sync     = BuildSync();
        string clusters = BuildClusters();
        string faulty   = BuildFaulty();

        string sep = $"<color=#{C_DIM}>  │  </color>";
        return $"<color=#{C_TEXT}>{dots}{sep}{blk}{sep}{rnd}{sep}{epoch}{sep}{proposer}{sep}{sync}{sep}{clusters}{sep}{faulty}</color>";
    }

    // ── EPOCH (latest block creation time) ──────────────────────────
    void OnNewBlock(long height)
    {
        float delay = UnityEngine.Random.Range(3f, 5f);
        var blkUtc = (mapManager != null ? mapManager.SimulatedUtcNow : System.DateTime.UtcNow)
                     .AddSeconds(-delay);
        _cachedBlkTime  = blkUtc.ToString("HH:mm:ss");
        // PROP = next round (N+1) proposer
        _cachedProposer = (blockchainPoller != null)
            ? blockchainPoller.NextProposer
            : $"SAT-{40000 + UnityEngine.Random.Range(0, 29999):D5}";
        _roundNumber = height;
    }

    string BuildEpoch()
    {
        // Default: the simulated mission time (kept in sync with the UTC line and
        // day/night shading). Hook: flip useChainBlockTime to show the chain's
        // real block timestamp (BlockchainPoller.LatestBlockTime) instead.
        string t = _cachedBlkTime;
        if (useChainBlockTime && blockchainPoller != null
            && !string.IsNullOrEmpty(blockchainPoller.LatestBlockTime)
            && blockchainPoller.LatestBlockTime != "--:--:--")
            t = blockchainPoller.LatestBlockTime;
        return $"BLK TIME  <color=#{C_ACCENT}>{t}</color>";
    }

    // ── PROPOSER (satellite that proposed the latest block) ───────────────────────
    string BuildProposer()
    {
        // NextProposer = next round (N+1); use _cachedProposer when there is no blockchain
        string p = (blockchainPoller != null && blockchainPoller.NextProposer != "SAT-?")
            ? blockchainPoller.NextProposer
            : _cachedProposer;
        return $"PROP  <color=#{C_ACCENT}>{p}</color>";
    }

    // ── 12 cluster status dots ────────────────────────────────
    // Green for the number of active clusters, dim for the rest
    string BuildDots()
    {
        int    active = GetActiveClusters();
        var    sb     = new System.Text.StringBuilder();

        for (int i = 0; i < dotCount; i++)
        {
            string col = i < active ? C_OK : C_DIM;
            sb.Append($"<color=#{col}>●</color>");
            if (i < dotCount - 1) sb.Append(' ');
        }
        return sb.ToString();
    }

    // ── RMSE ─────────────────────────────────────────────────
    string BuildRmse()
    {
        float rmse = GetRmse();
        // Per paper: < 8ns green, 8~10ns orange, > 10ns red
        string col = rmse < 8f ? C_OK : (rmse < 10f ? C_WARN : "ff4444");
        return $"RMSE  <color=#{col}>{rmse:F1} ns</color>";
    }

    // ── SYNC NOMINAL / DEGRADED / ANOMALY ────────────────────
    string BuildSync()
    {
        bool   synced = GetSynced();
        float  rmse   = GetRmse();
        string label, col;

        if (!synced)          { label = "ANOMALY";  col = "ff4444"; }
        else if (rmse >= 10f) { label = "DEGRADED"; col = C_WARN;   }
        else                  { label = "NOMINAL";  col = C_OK;     }

        return $"SYNC  <color=#{col}><b>{label}</b></color>";
    }

    // ── CLUSTERS ──────────────────────────────────────────────
    string BuildClusters()
    {
        int active = GetActiveClusters();
        // Clusters are always green while operating normally
        string col = active > 0 ? C_OK : C_WARN;
        return $"CLUSTERS  <color=#{col}>{active} / 12</color>";
    }

    // ── FAULTY ───────────────────────────────────────────────
    string BuildFaulty()
    {
        int f   = GetFaultyNodes();
        string col = f == 0 ? C_OK : C_WARN;
        return $"FAULTY  <color=#{col}>{f}</color>";
    }

    // ── Time formatting ────────────────────────────────────────────

    // MET: DDD:HH:MM:SS (Day of Mission : HH : MM : SS)
    string FormatMET()
    {
        var elapsed = System.DateTime.UtcNow - _appStartUtc;
        var offset  = elapsed.Add(System.TimeSpan.FromSeconds(metStartOffsetSec));
        return $"{(int)offset.TotalDays:D3}:{offset.Hours:D2}:{offset.Minutes:D2}:{offset.Seconds:D2}";
    }

    // UTC: YYYY-DDD · HH:MM:SS  (DOY format)
    string FormatUTC()
    {
        // Uses mapManager.SimulatedUtcNow — synced with the day/night shading
        var now = mapManager != null
            ? mapManager.SimulatedUtcNow
            : System.DateTime.UtcNow;
        int doy = now.DayOfYear;
        return $"{now.Year}-{doy:D3} · {now:HH:mm:ss}";
    }

    // ── Data access helpers (null-safe) ─────────────────────────
    long  GetLatestHeight()   => blockchainPoller != null ? blockchainPoller.LatestHeight   : 0;
    string GetChainId()       => blockchainPoller != null ? blockchainPoller.ChainId         : "leo_chain-1";
    float GetRmse()           => monitorPanel     != null ? monitorPanel.rmseNs              : 0f;
    bool  GetSynced()         => monitorPanel     != null ? monitorPanel.IsSynced            : true;
    int   GetActiveClusters() => monitorPanel     != null ? monitorPanel.activeClusters      : 12;
    int   GetFaultyNodes()    => monitorPanel     != null ? monitorPanel.faultyNodes         : 0;
}
