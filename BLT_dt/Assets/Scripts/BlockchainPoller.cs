using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;
using TMPro;

/// <summary>
/// BLT-SAND Block Explorer
/// Tendermint RPC (leo_chain-1) polling -> uGUI table refresh
/// </summary>
public class BlockchainPoller : MonoBehaviour
{
    [Header("RPC Settings")]
    public string rpcEndpoint   = "http://localhost:26657";
    public float  pollInterval  = 1f;
    public int    displayRows   = 10;

    [Header("UI — Top Summary")]
    public TextMeshProUGUI txtLatestHeight;
    public TextMeshProUGUI txtNetworkName;

    [Header("UI — Table")]
    public GameObject  rowPrefab;      // BlockRow prefab
    public Transform   rowContainer;   // ScrollView > Viewport > Content

    [Header("Satellite List (NORAD ID)")]
    public MapManager mapManager;  // MapManager reference

    [Header("BLT chain data (proposer source)")]
    public BltChainPoller bltPoller;  // x/blt epoch poller — real proposer SAT-ID

    // ── Public properties (referenced by MissionStatusBar) ──────
    public long   LatestHeight    => _lastHeight;
    public string ChainId         => _chainId;
    public string LatestBlockTime => _latestBlockTime;
    public string LatestProposer  => _latestProposer;
    public string NextProposer    => _nextProposer;
    [Tooltip("true = proposer_address hash method / false = block height method (default)")]
    public bool   useBlockchainProposer = false;
    private string   _nextProposer    = "SAT-?????";

    // ── Internal ───────────────────────────────────────────
    private long              _lastHeight = 0;
    private string            _chainId          = "leo_chain-1";
    private string            _latestBlockTime  = "--:--:--";
    private string            _latestProposer   = "SAT-?????";
    private List<GameObject>  _rows       = new List<GameObject>();

    // ── JSON classes ────────────────────────────────────
    [System.Serializable] class StatusResp   { public StatusResult  result; }
    [System.Serializable] class StatusResult { public NodeInfo node_info; public SyncInfo sync_info; }
    [System.Serializable] class NodeInfo     { public string network; public string moniker; }
    [System.Serializable] class SyncInfo     { public string latest_block_height; }

    [System.Serializable] class ChainResp    { public ChainResult   result; }
    [System.Serializable] class ChainResult  { public BlockMeta[]   block_metas; }
    [System.Serializable] class BlockMeta    { public BMHeader header; public int num_txs; }
    [System.Serializable] class BMHeader
    {
        public string height;
        public string time;
        public string proposer_address;
        public int    num_txs;
    }

    // ── Lifecycle ────────────────────────────────────
    void Start()
    {
        // Pre-create the row pool
        for (int i = 0; i < displayRows; i++)
        {
            var go = Instantiate(rowPrefab, rowContainer);
            go.SetActive(false);
            _rows.Add(go);
        }
        StartCoroutine(PollLoop());
    }

    IEnumerator PollLoop()
    {
        while (true)
        {
            yield return StartCoroutine(FetchStatus());   // Obtain the latest height each cycle
            yield return StartCoroutine(FetchBlocks());
            yield return new WaitForSeconds(pollInterval);
        }
    }

    // ── /status ────────────────────────────────────────
    IEnumerator FetchStatus()
    {
        using var req = UnityWebRequest.Get(rpcEndpoint + "/status");
        req.timeout = 5;
        yield return req.SendWebRequest();
        if (req.result != UnityWebRequest.Result.Success) yield break;

        var resp = JsonUtility.FromJson<StatusResp>(req.downloadHandler.text);
        if (resp?.result == null) yield break;

        _chainId = resp.result.node_info.network;
        if (txtNetworkName) txtNetworkName.text = _chainId;
        if (long.TryParse(resp.result.sync_info.latest_block_height, out long h))
            _lastHeight = h;
    }
    // ── Pre-fetch the next block's proposer ────────────────────

    // ── /blockchain ────────────────────────────────────
    IEnumerator FetchBlocks()
    {
        // _lastHeight is already obtained from the initial FetchStatus() in PollLoop
        // Removed the redundant FetchStatus call inside FetchBlocks (RPC calls 2 -> 1 per cycle)
        if (_lastHeight == 0) { yield break; }

        long max = _lastHeight;
        long min = System.Math.Max(1, max - displayRows + 1);
        string url = $"{rpcEndpoint}/blockchain?minHeight={min}&maxHeight={max}";

        using var req = UnityWebRequest.Get(url);
        req.timeout = 5;
        yield return req.SendWebRequest();

        if (req.result != UnityWebRequest.Result.Success)
        { yield break; }

        var resp = JsonUtility.FromJson<ChainResp>(req.downloadHandler.text);
        if (resp?.result?.block_metas == null)
        { yield break; }

        // Sort by height in descending order
        var metas = resp.result.block_metas;
        System.Array.Sort(metas, (a, b) =>
            long.Parse(b.header.height).CompareTo(long.Parse(a.header.height)));

        // Update _lastHeight directly from the block response (no redundant FetchStatus call needed)
        if (metas.Length > 0 && long.TryParse(metas[0].header.height, out long latestH))
        {
            _lastHeight = latestH;
            // Parse block timestamp (ISO8601 -> HH:mm:ss)
            if (!string.IsNullOrEmpty(metas[0].header.time))
            {
                if (System.DateTime.TryParse(metas[0].header.time,
                    null, System.Globalization.DateTimeStyles.RoundtripKind,
                    out System.DateTime bt))
                    _latestBlockTime = bt.ToUniversalTime().ToString("HH:mm:ss");
            }
            // Proposer source priority:
            //   1) BLT chain (x/blt epoch) — the real chain-generated proposer
            //   2) proposer_address hash    — when explicitly requested
            //   3) block-height seed (DT)   — offline fallback
            if (bltPoller != null && bltPoller.Connected)
            {
                _latestProposer = bltPoller.ProposerSat;
                _nextProposer   = bltPoller.NextProposerSat;
            }
            else if (!string.IsNullOrEmpty(metas[0].header.proposer_address))
            {
                string addr = metas[0].header.proposer_address;
                if (useBlockchainProposer)
                {
                    // [Blockchain method] based on proposer_address hash
                    _latestProposer = AddressToSatId(addr);
                    _nextProposer   = AddressToSatId(addr); // Not predictable, fallback
                }
                else
                {
                    // [DT method] based on block height — PROP is always one step ahead
                    _latestProposer = HeightToSatId(_lastHeight);
                    _nextProposer   = HeightToSatId(_lastHeight + 1);
                }
            }
        }

        UpdateTable(metas);
        if (txtLatestHeight && metas.Length > 0)
            txtLatestHeight.text = metas[0].header.height;
        // And remove the condition from PollLoop
    }

    // ── Table refresh ────────────────────────────────────
    // Block-height-based SAT ID (DT internal naming — unrelated to the blockchain)
    public static string HeightToSatId(long height)
    {
        var rng = new System.Random((int)(height * 2654435761L & 0x7FFFFFFF));
        return $"SAT-{40000 + rng.Next(0, 29999):D5}";
    }

    string AddressToSatId(string addr)
    {
        if (string.IsNullOrEmpty(addr)) return "SAT-?????";
        int seed = 0;
        foreach (char c in addr) seed = seed * 31 + c;
        var rng = new System.Random(System.Math.Abs(seed));
        return $"SAT-{40000 + rng.Next(0, 29999):D5}";
    }

    void UpdateTable(BlockMeta[] metas)
    {
        for (int i = 0; i < _rows.Count; i++)
        {
            if (i < metas.Length)
            {
                _rows[i].SetActive(true);
                var txts = _rows[i].GetComponentsInChildren<TextMeshProUGUI>();
                if (txts.Length >= 4)
                {
                    var m = metas[i];

                    // Height
                    txts[0].text = "#" + m.header.height;

                    // Tx
                    txts[1].text = "leo-sync";

                    // Select SAT ID mode
                    if (long.TryParse(m.header.height, out long bh))
                    {
                        if (useBlockchainProposer)
                            // [Blockchain method] based on proposer_address hash
                            txts[2].text = AddressToSatId(m.header.proposer_address);
                        else
                            // [DT method] based on block height (default)
                            txts[2].text = HeightToSatId(bh);
                    }
                    else txts[2].text = "SAT-?????";

                    // Time
                    txts[3].text = FormatTime(m.header.time);
                }
            }
            else
            {
                _rows[i].SetActive(false);
            }
        }
    }

    // ── Utilities ───────────────────────────────────────────
    string FormatTime(string iso)
    {
        if (System.DateTime.TryParse(iso, null,
            System.Globalization.DateTimeStyles.RoundtripKind, out var dt))
            return dt.ToString("HH:mm:ss");
        return iso;
    }

    string ShortenAddr(string addr)
    {
        // Get a random satellite NORAD ID from MapManager
        if (mapManager != null && mapManager._tleList != null
            && mapManager._tleList.Count > 0)
        {
            int idx = Random.Range(0, mapManager._tleList.Count);
            return mapManager._tleList[idx].NoradNumber;
        }
        return "SAT-" + Random.Range(40000, 60000);
    }
}

