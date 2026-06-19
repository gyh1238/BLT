using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// BLT-SAND x/blt module poller.
///
/// Reads the chain-generated sync epoch over the Tendermint RPC /abci_query
/// endpoint (:26657) and exposes the proposer SAT-ID and network RMSE that the
/// DT used to fabricate locally. The chain is now the single source of truth:
/// these values are produced deterministically in the x/blt EndBlocker
/// (seeded by block height) and merely read back here.
///
/// Queries:
///   /leochain.blt.Query/LatestEpoch  -> epoch_id, proposer, RMSE, counts
///   /leochain.blt.Query/DelegateSet  -> 12 cluster heads (for next proposer)
///
/// abci_query returns the protobuf-encoded gRPC response base64'd in
/// result.response.value, so a tiny wire-format reader is included below.
/// </summary>
public class BltChainPoller : MonoBehaviour
{
    [Header("RPC Settings")]
    public string rpcEndpoint  = "http://localhost:26657";
    public float  pollInterval = 1f;

    // ── Outputs (consumed by MonitorPanel / BlockchainPoller / MissionStatusBar) ──
    public bool   Connected       { get; private set; }
    public uint   EpochId         { get; private set; }
    public long   Height          { get; private set; }
    public string ProposerSat     { get; private set; } = "SAT-?????";
    public string NextProposerSat { get; private set; } = "SAT-?????";
    public float  NetworkRmseNs   { get; private set; }
    public int    ClusterCount    { get; private set; }
    public int    MemberCount     { get; private set; }

    // clusterId-ordered head ids from the delegate set
    private readonly List<uint> _heads = new List<uint>();

    void Start() => StartCoroutine(PollLoop());

    IEnumerator PollLoop()
    {
        while (true)
        {
            yield return StartCoroutine(FetchDelegateSet());
            yield return StartCoroutine(FetchLatestEpoch());
            yield return new WaitForSeconds(pollInterval);
        }
    }

    // path is URL-encoded: %22 = '"', %2F = '/'. Empty request body => data=0x.
    string AbciUrl(string method) =>
        $"{rpcEndpoint}/abci_query?path=%22%2Fleochain.blt.Query%2F{method}%22&data=0x";

    // ── /leochain.blt.Query/DelegateSet ──────────────────────────
    IEnumerator FetchDelegateSet()
    {
        byte[] payload = null;
        yield return AbciQuery("DelegateSet", v => payload = v);
        if (payload == null) yield break;

        // QueryDelegateSetResponse { 1: BltDelegateSet delegate_set }
        var top = Pb.Parse(payload);
        var setBytes = Pb.Bytes(top, 1);
        if (setBytes == null) yield break;

        // BltDelegateSet { 1: repeated BltDelegate delegates }
        var set = Pb.Parse(setBytes);
        var dels = Pb.List(set, 1);

        _heads.Clear();
        // collect (cluster_id, head_id) then order by cluster_id
        var pairs = new List<KeyValuePair<uint, uint>>();
        foreach (var d in dels)
        {
            if (!(d is byte[] db)) continue;
            var dm = Pb.Parse(db);
            uint cluster = (uint)Pb.Varint(dm, 1); // field 1: cluster_id
            uint head    = (uint)Pb.Varint(dm, 2); // field 2: head_id
            pairs.Add(new KeyValuePair<uint, uint>(cluster, head));
        }
        pairs.Sort((a, b) => a.Key.CompareTo(b.Key));
        foreach (var p in pairs) _heads.Add(p.Value);
    }

    // ── /leochain.blt.Query/LatestEpoch ──────────────────────────
    IEnumerator FetchLatestEpoch()
    {
        byte[] payload = null;
        yield return AbciQuery("LatestEpoch", v => payload = v);
        if (payload == null) { Connected = false; yield break; }

        // QueryLatestEpochResponse { 1: BltEpochSnapshot snapshot }
        var top  = Pb.Parse(payload);
        var snapB = Pb.Bytes(top, 1);
        if (snapB == null) { Connected = false; yield break; }

        // BltEpochSnapshot { 1:epoch_id 2:height 3:proposer 5:body }
        var snap = Pb.Parse(snapB);
        EpochId  = (uint)Pb.Varint(snap, 1);
        Height   = (long)Pb.Varint(snap, 2);
        string proposer = Pb.Str(snap, 3);
        if (!string.IsNullOrEmpty(proposer)) ProposerSat = proposer;

        var bodyB = Pb.Bytes(snap, 5);
        if (bodyB != null)
        {
            // BltBlockBody { 1:global 2:repeated cluster_table }
            var body = Pb.Parse(bodyB);

            var globalB = Pb.Bytes(body, 1);
            if (globalB != null)
            {
                var g = Pb.Parse(globalB);
                ClusterCount = (int)Pb.Varint(g, 2); // field 2: cluster_count
                MemberCount  = (int)Pb.Varint(g, 3); // field 3: member_count
            }

            // network RMSE = sqrt(mean cluster variance) / 10  (q01ns -> ns)
            var clusters = Pb.List(body, 2);
            if (clusters.Count > 0)
            {
                double sumVar = 0;
                foreach (var c in clusters)
                {
                    if (!(c is byte[] cb)) continue;
                    var cm = Pb.Parse(cb);
                    sumVar += Pb.Varint(cm, 7); // field 7: member_offset_var_q01ns2
                }
                double meanVar = sumVar / clusters.Count;
                NetworkRmseNs = (float)(Math.Sqrt(meanVar) / 10.0);
            }
        }

        // Next proposer = head at (height+1) % clusterCount, mirroring the chain's
        // height-based proposer rotation over the (cluster-ordered) delegate set.
        if (_heads.Count > 0)
        {
            int nextIdx = (int)((Height + 1) % _heads.Count);
            NextProposerSat = SatLabel(_heads[nextIdx]);
        }

        Connected = true;
    }

    // SAT-ID formatting — identical to the chain's keeper.SatLabel.
    public static string SatLabel(uint headID) => $"SAT-{40000 + headID:D5}";

    // ── abci_query plumbing ──────────────────────────────────────
    [Serializable] class AbciResp     { public AbciResult result; }
    [Serializable] class AbciResult   { public AbciResponse response; }
    [Serializable] class AbciResponse { public int code; public string value; public string height; }

    IEnumerator AbciQuery(string method, Action<byte[]> onResult)
    {
        using var req = UnityWebRequest.Get(AbciUrl(method));
        req.timeout = 5;
        yield return req.SendWebRequest();
        if (req.result != UnityWebRequest.Result.Success) yield break;

        AbciResp resp;
        try { resp = JsonUtility.FromJson<AbciResp>(req.downloadHandler.text); }
        catch { yield break; }

        if (resp?.result?.response == null) yield break;
        if (resp.result.response.code != 0) yield break;             // e.g. NotFound until first epoch
        string b64 = resp.result.response.value;
        if (string.IsNullOrEmpty(b64)) yield break;

        byte[] bytes;
        try { bytes = Convert.FromBase64String(b64); }
        catch { yield break; }
        onResult(bytes);
    }
}

/// <summary>
/// Minimal protobuf wire-format reader — just enough to walk the known x/blt
/// query responses. Parses one message level into field -> list of values,
/// where a value is a ulong (varint / 32- / 64-bit) or a byte[] (length-delim).
/// </summary>
internal static class Pb
{
    public static Dictionary<int, List<object>> Parse(byte[] data) => Parse(data, 0, data.Length);

    public static Dictionary<int, List<object>> Parse(byte[] data, int off, int end)
    {
        var map = new Dictionary<int, List<object>>();
        int i = off;
        while (i < end)
        {
            ulong tag = ReadVarint(data, ref i);
            int field = (int)(tag >> 3);
            int wire  = (int)(tag & 7);
            object val;
            switch (wire)
            {
                case 0: val = ReadVarint(data, ref i); break;          // varint
                case 1: val = ReadFixed(data, ref i, 8); break;        // 64-bit
                case 5: val = ReadFixed(data, ref i, 4); break;        // 32-bit
                case 2:                                                 // length-delimited
                {
                    int len = (int)ReadVarint(data, ref i);
                    if (i + len > end) return map;                     // malformed → stop
                    var sub = new byte[len];
                    Array.Copy(data, i, sub, 0, len);
                    i += len;
                    val = sub;
                    break;
                }
                default: return map;                                   // unsupported wire type
            }
            if (!map.TryGetValue(field, out var list)) { list = new List<object>(); map[field] = list; }
            list.Add(val);
        }
        return map;
    }

    public static ulong Varint(Dictionary<int, List<object>> m, int field)
        => (m.TryGetValue(field, out var l) && l.Count > 0 && l[0] is ulong u) ? u : 0UL;

    public static byte[] Bytes(Dictionary<int, List<object>> m, int field)
        => (m.TryGetValue(field, out var l) && l.Count > 0 && l[0] is byte[] b) ? b : null;

    public static string Str(Dictionary<int, List<object>> m, int field)
    {
        var b = Bytes(m, field);
        return b == null ? null : System.Text.Encoding.UTF8.GetString(b);
    }

    public static List<object> List(Dictionary<int, List<object>> m, int field)
        => (m.TryGetValue(field, out var l)) ? l : new List<object>();

    static ulong ReadVarint(byte[] data, ref int i)
    {
        ulong result = 0;
        int shift = 0;
        while (i < data.Length && shift < 64)
        {
            byte b = data[i++];
            result |= (ulong)(b & 0x7F) << shift;
            if ((b & 0x80) == 0) break;
            shift += 7;
        }
        return result;
    }

    static ulong ReadFixed(byte[] data, ref int i, int n)
    {
        ulong result = 0;
        for (int k = 0; k < n && i < data.Length; k++)
            result |= (ulong)data[i++] << (8 * k);
        return result;
    }
}
