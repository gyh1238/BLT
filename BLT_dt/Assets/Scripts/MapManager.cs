using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;
using Zeptomoby.OrbitTools;

public class MapManager : MonoBehaviour
{
    [Header("Earth Background Material")]
    public Material earthMaterial;

    [Header("Satellite Prefab")]
    public GameObject satellitePrefab;
    public Transform  satelliteContainer;

    [Header("Orbit Path")]
    public Material orbitLineMaterial;
    public Color    orbitLineColor       = new Color(0.4f, 0.8f, 1f, 0.4f);
    public int      orbitPoints          = 60;
    public float    orbitMinutes         = 45f;
    // Number of orbit lines to display per Cluster in ALL mode (performance cap)
    // When a Cluster is selected, all orbit lines belonging to that Cluster are displayed
    public int      orbitLinesPerCluster = 3;

    [Header("Map Size")]
    public float mapWidth  = 20f;
    public float mapHeight = 10f;
    public float satZ      = -0.1f;
    public float orbitZ    = -0.05f;
    public float satScale  = 0.03f;

    [Header("Settings")]
    public int   maxSatellites  = 8000;
    public bool  autoDownloadTle = true;   // Automatically download the latest TLE from Space-Track on start

    [Header("Space-Track Authentication (space-track.org)")]
    public string spaceTrackUser = "";
    public string spaceTrackPass = "";
    public float updateInterval = 3.5f;
    public float  maxTleAgeDays     = 365f;
    [Tooltip("UTC reference for day/night. Format: yyyy-MM-dd HH:mm:ss")]
    public string simulatedUtcStart = "";  // e.g. "2026-05-21 00:30:00"
    System.DateTime _simUtcBase;
    float           _simUtcRealBase;

    // ── Satellites ─────────────────────────────────────────────────
    private List<Transform> _satTransforms = new List<Transform>();
    public System.DateTime SimulatedUtcNow =>
        (simulatedUtcStart.Length > 0)
            ? _simUtcBase.AddSeconds(Time.realtimeSinceStartup - _simUtcRealBase)
            : System.DateTime.UtcNow;

    public List<Transform> SatTransforms => _satTransforms;
    private List<int>       _satClusterIdx = new List<int>();
    public  List<Vector2>   _latLonList    = new List<Vector2>();
    public  List<Tle>       _tleList       = new List<Tle>();
    private float           _timer         = 0f;

    // ── Orbit Lines ───────────────────────────────────────────────
    private struct OrbitEntry { public LineRenderer lr; public int clusterIdx; }
    private List<OrbitEntry> _orbitLines = new List<OrbitEntry>();

    // ── Cluster Ellipses (grouped by index) ────────────────────────
    private List<List<LineRenderer>> _clusterEllipseGroups = new List<List<LineRenderer>>();
    public Material clusterEllipseMaterial;
    public Color    clusterEllipseColor  = new Color(1f, 0.85f, 0.3f, 0.6f);
    public float    clusterAngularRadius = 30f;
    public int      clusterEllipsePoints = 80;

    // ── Color Constants ─────────────────────────────────────────────
    private static readonly Color _colorSelected = new Color(0f, 0.706f, 1f,   1f   );
    private static readonly Color _colorDimmed   = new Color(1f, 0.85f,  0.3f, 0.08f);
    private static readonly Color _colorNormal   = new Color(1f, 0.85f,  0.3f, 0.6f );

    // ── Lifecycle ─────────────────────────────────────────
    void Start()
    {
        if (!string.IsNullOrEmpty(simulatedUtcStart) &&
            System.DateTime.TryParseExact(simulatedUtcStart,
                "yyyy-MM-dd HH:mm:ss",
                System.Globalization.CultureInfo.InvariantCulture,
                System.Globalization.DateTimeStyles.None,
                out _simUtcBase))
            _simUtcRealBase = Time.realtimeSinceStartup;
        StartCoroutine(DownloadAndInit());
    }

    // ── Initialize after TLE download ────────────────────────────────
    IEnumerator DownloadAndInit()
    {
        if (autoDownloadTle)
            yield return StartCoroutine(DownloadTle());
        yield return StartCoroutine(LoadAndInit());
    }

    IEnumerator DownloadTle()
    {
        string savePath = System.IO.Path.Combine(
            Application.streamingAssetsPath, "STARLINK_TLE.txt");

        if (string.IsNullOrEmpty(spaceTrackUser) || string.IsNullOrEmpty(spaceTrackPass))
        {
            Debug.LogWarning("[MapManager] Space-Track account not configured → using existing file");
            yield break;
        }

        // Step 1: login (obtain cookie)
        string loginUrl  = "https://www.space-track.org/ajaxauth/login";
        string loginBody = $"identity={UnityWebRequest.EscapeURL(spaceTrackUser)}" +
                           $"&password={UnityWebRequest.EscapeURL(spaceTrackPass)}";

        Debug.Log("[MapManager] Logging in to Space-Track...");
        string cookie = "";

        using (var loginReq = new UnityWebRequest(loginUrl, "POST"))
        {
            byte[] bodyBytes = System.Text.Encoding.UTF8.GetBytes(loginBody);
            loginReq.uploadHandler   = new UploadHandlerRaw(bodyBytes);
            loginReq.downloadHandler = new DownloadHandlerBuffer();
            loginReq.SetRequestHeader("Content-Type", "application/x-www-form-urlencoded");
            loginReq.timeout = 15;
            yield return loginReq.SendWebRequest();

            if (loginReq.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"[MapManager] login failed: {loginReq.error}");
                yield break;
            }
            // Extract the session cookie from the Set-Cookie header
            cookie = loginReq.GetResponseHeader("Set-Cookie") ?? "";
            Debug.Log("[MapManager] login success");
        }

        // Step 2: download Starlink TLE
        string tleUrl = "https://www.space-track.org/basicspacedata/query/" +
                        "class/gp/OBJECT_NAME/STARLINK~~/FORMAT/tle/orderby/NORAD_CAT_ID";

        Debug.Log("[MapManager] Downloading Starlink TLE...");
        using (var tleReq = UnityWebRequest.Get(tleUrl))
        {
            tleReq.timeout = 30;
            if (!string.IsNullOrEmpty(cookie))
                tleReq.SetRequestHeader("Cookie", cookie);
            yield return tleReq.SendWebRequest();

            if (tleReq.result == UnityWebRequest.Result.Success &&
                tleReq.downloadHandler.text.Length > 1000)
            {
                string tleText = tleReq.downloadHandler.text;
                int count = tleText.Split(new string[]{"\n","\r\n"}, System.StringSplitOptions.RemoveEmptyEntries).Length / 2;
                System.IO.File.WriteAllText(savePath, tleText);
                Debug.Log($"[MapManager] Saved {count} Starlink TLEs");
            }
            else
            {
                Debug.LogWarning($"[MapManager] TLE download failed: {tleReq.error}");
            }
        }

        // Step 3: logout
        using (var logout = UnityWebRequest.Get("https://www.space-track.org/auth/logout"))
        {
            if (!string.IsNullOrEmpty(cookie))
                logout.SetRequestHeader("Cookie", cookie);
            yield return logout.SendWebRequest();
        }
    }

    // ── TLE parsing (auto-detect 2-line/3-line format) ────────────────────
    void ParseTleLines(string[] lines, System.DateTime now, bool checkAge)
    {
        int i = 0;
        int count = 0;
        while (i < lines.Length && _tleList.Count < maxSatellites)
        {
            string a = lines[i].Trim();
            if (string.IsNullOrEmpty(a)) { i++; continue; }

            string name = "", l1 = "", l2 = "";

            // 3-line format: the name line does not start with '1 ' or '2 '
            if (!a.StartsWith("1 ") && !a.StartsWith("2 "))
            {
                // name line
                name = a;
                if (i + 2 >= lines.Length) break;
                l1 = lines[i + 1].Trim();
                l2 = lines[i + 2].Trim();
                i += 3;
            }
            else if (a.StartsWith("1 "))
            {
                // 2-line format
                l1 = a;
                if (i + 1 >= lines.Length) break;
                l2 = lines[i + 1].Trim();
                name = $"STARLINK-{count + 1}";
                i += 2;
            }
            else { i++; continue; }

            if (l1.Length < 60 || l2.Length < 60) continue;
            if (!l1.StartsWith("1 ") || !l2.StartsWith("2 ")) continue;

            try
            {
                var tle = new Tle(name, l1, l2);
                if (checkAge)
                {
                    double age = System.Math.Abs(
                        now.Subtract(tle.EpochJulian.ToTime()).TotalDays);
                    if (age > maxTleAgeDays) continue;
                }
                _tleList.Add(tle);
                count++;
            }
            catch { }
        }
    }

    IEnumerator LoadAndInit()
    {
        // [Race condition prevention] There is no guarantee that GlobeManager.Start()'s
        // ComputeClusterCenters() runs first, so wait until it is populated (up to 3 seconds)
        float waited = 0f;
        while ((GlobeManager.ClusterCenters == null ||
                GlobeManager.ClusterCenters.Count == 0) && waited < 3f)
        {
            yield return null;
            waited += Time.deltaTime;
        }
        if (GlobeManager.ClusterCenters == null || GlobeManager.ClusterCenters.Count == 0)
            Debug.LogWarning("[MapManager] ClusterCenters wait timed out — Cluster assignment not possible");

        // Load TLE
        string path = System.IO.Path.Combine(
            Application.streamingAssetsPath, "STARLINK_TLE.txt");

        if (!System.IO.File.Exists(path))
        {
            Debug.LogWarning("[MapManager] STARLINK_TLE.txt not found → placeholder");
            CreatePlaceholderSats();
            yield break;
        }

        // Read with ReadAllLines to handle both \r\n and \n
        string[] lines = System.IO.File.ReadAllLines(path);
        var now = System.DateTime.UtcNow;

        // Auto-detect 3-line format (name+L1+L2) vs 2-line format (L1+L2)
        // Line 1 starts with '1 ', Line 2 starts with '2 '
        ParseTleLines(lines, now, true);

        if (_tleList.Count < 50)
        {
            Debug.LogWarning("[MapManager] Not enough valid TLEs → lifting age limit");
            _tleList.Clear();
            ParseTleLines(lines, now, false);
        }

        Debug.Log($"[MapManager] Loaded {_tleList.Count} TLEs");

        UpdateLatLon();
        SpawnSatellites();
        StartCoroutine(WaitAndDrawEllipses());
        DrawOrbitPaths();
        yield return null;
    }

    // ── Latitude/longitude computation ───────────────────────────────────────────
    void UpdateLatLon()
    {
        var prev = new List<Vector2>(_latLonList);
        _latLonList.Clear();
        var now = System.DateTime.UtcNow;

        for (int idx = 0; idx < _tleList.Count; idx++)
        {
            try
            {
                var    sat = new Satellite(_tleList[idx]);
                double mpe = now.Subtract(_tleList[idx].EpochJulian.ToTime()).TotalMinutes;
                var    eci = sat.PositionEci(mpe);
                double r   = System.Math.Sqrt(
                    eci.Position.X * eci.Position.X +
                    eci.Position.Y * eci.Position.Y +
                    eci.Position.Z * eci.Position.Z);
                float lat = (float)(System.Math.Asin(eci.Position.Z / r) * Mathf.Rad2Deg);
                float lon = (float)(System.Math.Atan2(eci.Position.Y, eci.Position.X) * Mathf.Rad2Deg);

                if (prev.Count > idx)
                {
                    float dLat = Mathf.Abs(lat - prev[idx].x);
                    float dLon = Mathf.Abs(lon - prev[idx].y);
                    if (dLon > 180f) dLon = 360f - dLon;
                    if (dLat > 30f || dLon > 30f) { _latLonList.Add(prev[idx]); continue; }
                }
                _latLonList.Add(new Vector2(lat, lon));
            }
            catch { _latLonList.Add(prev.Count > idx ? prev[idx] : Vector2.zero); }
        }
    }

    // ── Spawn satellites + clusterIdx ────────────────────────────────
    void SpawnSatellites()
    {
        foreach (Transform c in satelliteContainer) Destroy(c.gameObject);
        _satTransforms.Clear();
        _satClusterIdx.Clear();

        for (int i = 0; i < _latLonList.Count; i++)
        {
            var go = Instantiate(satellitePrefab, satelliteContainer);
            go.transform.localScale = Vector3.one * satScale;
            go.transform.position   = LatLonToWorld(_latLonList[i].x, _latLonList[i].y, satZ);
            _satTransforms.Add(go.transform);
            _satClusterIdx.Add(GetNearestCluster(_latLonList[i].x, _latLonList[i].y));
        }

        // Log of satellite count per Cluster
        var cnt = new int[12];
        foreach (var ci in _satClusterIdx) if (ci >= 0 && ci < 12) cnt[ci]++;
        var sb = new System.Text.StringBuilder("[MapManager] Satellite count per Cluster: ");
        for (int i = 0; i < 12; i++) sb.Append($"C{i+1:D2}={cnt[i]} ");
        Debug.Log(sb.ToString());
    }

    // ── Nearest Cluster index ──────────────────────────
    int GetNearestCluster(float lat, float lon)
    {
        if (GlobeManager.ClusterCenters == null ||
            GlobeManager.ClusterCenters.Count == 0) return 0;
        Vector3 v   = GlobeManager.LatLonToSphere(lat, lon);
        int   best  = 0;
        float bDot  = -2f;
        for (int c = 0; c < GlobeManager.ClusterCenters.Count; c++)
        {
            float d = Vector3.Dot(v, GlobeManager.ClusterCenters[c]);
            if (d > bDot) { bDot = d; best = c; }
        }
        return best;
    }

    // ── Orbit lines (N evenly per Cluster) ─────────────────────────
    void DrawOrbitPaths()
    {
        foreach (var e in _orbitLines) if (e.lr != null) Destroy(e.lr.gameObject);
        _orbitLines.Clear();

        var now          = System.DateTime.UtcNow;
        int clusterCount = (GlobeManager.ClusterCenters != null)
            ? GlobeManager.ClusterCenters.Count : 12;

        // Classify TLEs per Cluster
        var groups = new List<List<Tle>>();
        for (int i = 0; i < clusterCount; i++) groups.Add(new List<Tle>());
        foreach (var tle in _tleList)
        {
            int ci = GetClusterIdxForTle(tle, now);
            if (ci >= 0 && ci < clusterCount) groups[ci].Add(tle);
        }

        // Draw orbits for all TLEs (the ALL mode display cap is controlled in ApplyClusterFilter)
        for (int ci = 0; ci < clusterCount; ci++)
            foreach (var tle in groups[ci])
                DrawSingleOrbit(tle, ci, now);

        Debug.Log($"[MapManager] {_orbitLines.Count} orbit lines complete (ALL display cap: {orbitLinesPerCluster} per Cluster)");
    }

    void DrawSingleOrbit(Tle tle, int clusterIdx, System.DateTime now)
    {
        try
        {
            var   sat    = new Satellite(tle);
            var   pts    = new List<Vector3>();
            float step   = orbitMinutes / orbitPoints;

            for (int i = 0; i <= orbitPoints; i++)
            {
                double mpe = now.Subtract(tle.EpochJulian.ToTime()).TotalMinutes + i * step;
                var    eci = sat.PositionEci(mpe);
                double r   = System.Math.Sqrt(
                    eci.Position.X * eci.Position.X +
                    eci.Position.Y * eci.Position.Y +
                    eci.Position.Z * eci.Position.Z);
                float lat = (float)(System.Math.Asin(eci.Position.Z / r) * Mathf.Rad2Deg);
                float lon = (float)(System.Math.Atan2(eci.Position.Y, eci.Position.X) * Mathf.Rad2Deg);
                pts.Add(LatLonToWorld(lat, lon, orbitZ));
            }

            foreach (var seg in SplitAtWrap(pts))
            {
                if (seg.Count < 2) continue;
                var go = new GameObject($"Orbit_C{clusterIdx:D2}");
                go.transform.SetParent(satelliteContainer);
                var lr = go.AddComponent<LineRenderer>();
                lr.material      = orbitLineMaterial != null
                    ? orbitLineMaterial : new Material(Shader.Find("Unlit/Color"));
                lr.startColor    = orbitLineColor;
                lr.endColor      = orbitLineColor;
                lr.startWidth    = 0.008f;
                lr.endWidth      = 0.008f;
                lr.positionCount = seg.Count;
                lr.SetPositions(seg.ToArray());
                lr.useWorldSpace = true;
                _orbitLines.Add(new OrbitEntry { lr = lr, clusterIdx = clusterIdx });
            }
        }
        catch { }
    }

    int GetClusterIdxForTle(Tle tle, System.DateTime now)
    {
        try
        {
            var    sat = new Satellite(tle);
            double mpe = now.Subtract(tle.EpochJulian.ToTime()).TotalMinutes;
            var    eci = sat.PositionEci(mpe);
            double r   = System.Math.Sqrt(
                eci.Position.X * eci.Position.X +
                eci.Position.Y * eci.Position.Y +
                eci.Position.Z * eci.Position.Z);
            float lat = (float)(System.Math.Asin(eci.Position.Z / r) * Mathf.Rad2Deg);
            float lon = (float)(System.Math.Atan2(eci.Position.Y, eci.Position.X) * Mathf.Rad2Deg);
            return GetNearestCluster(lat, lon);
        }
        catch { return 0; }
    }

    List<List<Vector3>> SplitAtWrap(List<Vector3> pts)
    {
        var result = new List<List<Vector3>>();
        var cur    = new List<Vector3>();
        for (int i = 0; i < pts.Count; i++)
        {
            if (i > 0 && Mathf.Abs(pts[i].x - pts[i-1].x) > mapWidth * 0.4f)
            { result.Add(cur); cur = new List<Vector3>(); }
            cur.Add(pts[i]);
        }
        if (cur.Count > 0) result.Add(cur);
        return result;
    }

    // ── Cluster ellipses (grouped) ────────────────────────────────
    IEnumerator WaitAndDrawEllipses()
    {
        yield return new WaitForSeconds(2.5f);
        DrawClusterEllipses();
    }

    void DrawClusterEllipses()
    {
        foreach (var g in _clusterEllipseGroups)
            foreach (var lr in g) if (lr != null) Destroy(lr.gameObject);
        _clusterEllipseGroups.Clear();

        if (GlobeManager.ClusterCenters == null ||
            GlobeManager.ClusterCenters.Count == 0) return;

        for (int ci = 0; ci < GlobeManager.ClusterCenters.Count; ci++)
        {
            var   cen  = GlobeManager.ClusterCenters[ci];
            float lat0 = Mathf.Asin(cen.y) * Mathf.Rad2Deg;
            float lon0 = Mathf.Atan2(cen.z, cen.x) * Mathf.Rad2Deg;
            var   grp  = new List<LineRenderer>();

            foreach (var seg in BuildEllipseSegments(lat0, lon0, clusterAngularRadius))
            {
                if (seg.Count < 2) continue;
                var go = new GameObject($"Ellipse_{ci:D2}");
                go.transform.SetParent(satelliteContainer);
                var lr = go.AddComponent<LineRenderer>();
                lr.material      = clusterEllipseMaterial != null
                    ? clusterEllipseMaterial : new Material(Shader.Find("Unlit/Color"));
                lr.startColor    = clusterEllipseColor;
                lr.endColor      = clusterEllipseColor;
                lr.startWidth    = 0.012f;
                lr.endWidth      = 0.012f;
                lr.positionCount = seg.Count;
                lr.SetPositions(seg.ToArray());
                lr.useWorldSpace = true;
                grp.Add(lr);
            }
            _clusterEllipseGroups.Add(grp);
        }
    }

    List<List<Vector3>> BuildEllipseSegments(float lat0, float lon0, float angDeg)
    {
        float   r  = angDeg * Mathf.Deg2Rad;
        Vector3 c  = new Vector3(
            Mathf.Cos(lat0 * Mathf.Deg2Rad) * Mathf.Cos(lon0 * Mathf.Deg2Rad),
            Mathf.Sin(lat0 * Mathf.Deg2Rad),
            Mathf.Cos(lat0 * Mathf.Deg2Rad) * Mathf.Sin(lon0 * Mathf.Deg2Rad));
        Vector3 b1 = Vector3.Cross(c, Vector3.up).normalized;
        if (b1.magnitude < 0.01f) b1 = Vector3.Cross(c, Vector3.right).normalized;
        Vector3 b2 = Vector3.Cross(c, b1).normalized;

        var   res  = new List<List<Vector3>>();
        var   cur  = new List<Vector3>();
        float pLon = float.NaN;

        for (int i = 0; i <= clusterEllipsePoints; i++)
        {
            float   t  = i / (float)clusterEllipsePoints * Mathf.PI * 2f;
            Vector3 pt = (Mathf.Cos(r) * c
                        + Mathf.Sin(r) * (Mathf.Cos(t) * b1 + Mathf.Sin(t) * b2)).normalized;
            float lat  = Mathf.Asin(pt.y) * Mathf.Rad2Deg;
            float lon  = Mathf.Atan2(pt.z, pt.x) * Mathf.Rad2Deg;
            if (!float.IsNaN(pLon) && Mathf.Abs(lon - pLon) > 180f)
            { res.Add(cur); cur = new List<Vector3>(); }
            pLon = lon;
            cur.Add(LatLonToWorld(lat, lon, orbitZ - 0.01f));
        }
        if (cur.Count > 0) res.Add(cur);
        return res;
    }

    // ── [Phase2] Apply Cluster filter ──────────────────────────
    public void ApplyClusterFilter(int selectedIdx)
    {
        bool all = selectedIdx < 0;

        for (int ci = 0; ci < _clusterEllipseGroups.Count; ci++)
        {
            Color col = (all || ci == selectedIdx) ? _colorSelected : _colorDimmed;
            foreach (var lr in _clusterEllipseGroups[ci])
            { if (lr) { lr.startColor = col; lr.endColor = col; } }
        }

        // ALL mode: display only orbitLinesPerCluster lines per Cluster (hide the rest)
        // FILTER mode: display all lines belonging to the selected Cluster, hide the rest
        var shownCount = new int[12];
        foreach (var e in _orbitLines)
        {
            if (!e.lr) continue;
            if (all)
            {
                int ci = e.clusterIdx;
                bool show = ci >= 0 && ci < 12 && shownCount[ci] < orbitLinesPerCluster;
                e.lr.enabled = show;
                if (show) shownCount[ci]++;
            }
            else
            {
                e.lr.enabled = e.clusterIdx == selectedIdx;
            }
        }

        for (int i = 0; i < _satTransforms.Count; i++)
        {
            if (!_satTransforms[i]) continue;
            bool active = all || (i < _satClusterIdx.Count && _satClusterIdx[i] == selectedIdx);
            _satTransforms[i].localScale = Vector3.one * (active ? satScale : satScale * 0.25f);
        }
    }

    // ── Sun shader ───────────────────────────────────────────
    void UpdateSunShader()
    {
        if (!earthMaterial) return;
        // Use the simulated UTC if it is configured
        var now = (simulatedUtcStart.Length > 0)
            ? _simUtcBase.AddSeconds(Time.realtimeSinceStartup - _simUtcRealBase)
            : System.DateTime.UtcNow;
        double jd  = 367.0 * now.Year
            - System.Math.Floor(7.0 * (now.Year
                + System.Math.Floor((now.Month + 9.0) / 12.0)) / 4.0)
            + System.Math.Floor(275.0 * now.Month / 9.0)
            + now.Day + 1721013.5
            + now.Hour / 24.0 + now.Minute / 1440.0 + now.Second / 86400.0;
        double T        = (jd - 2451545.0) / 36525.0;
        double L0       = 280.4665 + 36000.7698 * T;
        double M        = 357.5291 + 35999.0503 * T;
        double C        = 1.9146 * System.Math.Sin(M * Mathf.Deg2Rad)
                        + 0.0200 * System.Math.Sin(2 * M * Mathf.Deg2Rad);
        double sunEclLon = L0 + C;
        double GMST      = 280.46061837 + 360.98564736629 * (jd - 2451545.0);
        double obliquity = 23.439 - 0.0000004 * T;
        earthMaterial.SetFloat("_SunLon",
            (float)((sunEclLon - GMST) % 360.0));
        earthMaterial.SetFloat("_SunDecl",
            (float)(System.Math.Asin(
                System.Math.Sin(obliquity * Mathf.Deg2Rad) *
                System.Math.Sin(sunEclLon * Mathf.Deg2Rad)) * Mathf.Rad2Deg));
    }

    void CreatePlaceholderSats()
    {
        for (int i = 0; i < 100; i++)
            _latLonList.Add(new Vector2(
                Random.Range(-70f, 70f), Random.Range(-180f, 180f)));
        SpawnSatellites();
    }

    private const int BATCH_SIZE = 200; // Maximum number of satellite position updates per frame

    void Update()
    {
        UpdateSunShader();
        _timer += Time.deltaTime;
        if (_timer < updateInterval) return;
        _timer = 0f;
        UpdateLatLon();
        StartCoroutine(BatchUpdatePositions());
    }

    IEnumerator BatchUpdatePositions()
    {
        int total = Mathf.Min(_satTransforms.Count, _latLonList.Count);
        for (int i = 0; i < total; i += BATCH_SIZE)
        {
            int end = Mathf.Min(i + BATCH_SIZE, total);
            for (int j = i; j < end; j++)
            {
                if (!_satTransforms[j]) continue;
                var p2 = LatLonToWorld(_latLonList[j].x, _latLonList[j].y, satZ);
                if (float.IsNaN(p2.x) || float.IsNaN(p2.y) || p2.x < -9000f) continue;
                _satTransforms[j].position = p2;
            }
            yield return null; // Spread across the next frame
        }
    }

    // ── Return satellite count per Cluster (for MonitorPanel) ─────────────
    // Return the Cluster index of a specific satellite
    public int GetSatClusterIdx(int satIdx)
    {
        if (satIdx < 0 || satIdx >= _satClusterIdx.Count) return -1;
        return _satClusterIdx[satIdx];
    }

    public int GetClusterMemberCount(int clusterIdx)
    {
        int count = 0;
        foreach (var ci in _satClusterIdx)
            if (ci == clusterIdx) count++;
        return count;
    }

    public Vector3 LatLonToWorld(float lat, float lon, float z = -0.1f)
    {
        if (float.IsNaN(lat) || float.IsNaN(lon) ||
            float.IsInfinity(lat) || float.IsInfinity(lon))
            return new Vector3(-9999f, -9999f, z);  // off-screen
        return _LatLonToWorld(lat, lon, z);
    }
    Vector3 _LatLonToWorld(float lat, float lon, float z = -0.1f) =>
        new Vector3(
            (lon / 180f) * (mapWidth  * 0.5f),
            (lat /  90f) * (mapHeight * 0.5f),
            z);
}
