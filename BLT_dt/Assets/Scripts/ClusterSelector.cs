using UnityEngine;
using System;

/// <summary>
/// BLT-SAND Cluster selection manager (singleton)
/// - Cycle through clusters 0~11 with the ← → arrow keys
/// - Return to the full view (ALL) with ESC
/// - SelectByLabel(1~12): called from UI buttons
/// - Propagates to MapManager and GlobeManager via the OnClusterChanged event
/// Add this to Manager_Root
/// </summary>
public class ClusterSelector : MonoBehaviour
{
    // ── Singleton ──────────────────────────────────────────────
    public static ClusterSelector Instance { get; private set; }

    // ── State ────────────────────────────────────────────────
    /// <summary>-1 = ALL (full view), 0~11 = selected cluster index</summary>
    public int  SelectedIndex  { get; private set; } = -1;
    public bool IsFilterActive => SelectedIndex >= 0;

    // ── Events ──────────────────────────────────────────────
    /// <summary>Raised when the cluster changes. int = SelectedIndex (-1~11)</summary>
    public static event Action<int> OnClusterChanged;

    // ── Color constants (NASA theme) ────────────────────────────────
    public static readonly Color ColorSelected  = new Color(0.00f, 0.706f, 1.00f, 1.00f); // #00b4ff cyan
    public static readonly Color ColorDimmed    = new Color(1.00f, 0.850f, 0.30f, 0.08f); // yellow, 8% alpha
    public static readonly Color ColorNormal    = new Color(1.00f, 0.850f, 0.30f, 0.60f); // yellow, 60% alpha (ALL state)
    public static readonly Color ColorGlobeSel  = new Color(0.00f, 0.706f, 1.00f, 1.00f); // Globe selected circle
    public static readonly Color ColorGlobeDim  = new Color(1.00f, 0.850f, 0.30f, 0.15f); // Globe unselected circle

    // ── Inspector exposure ───────────────────────────────────────
    [Header("References")]
    public MapManager  mapManager;
    public GlobeManager globeManager;

    // ── Lifecycle ─────────────────────────────────────────
    void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
    }

    void OnEnable()
    {
        // Subscribe to MapManager and GlobeManager events
        OnClusterChanged += NotifyMapManager;
        OnClusterChanged += NotifyGlobeManager;
    }

    void OnDisable()
    {
        OnClusterChanged -= NotifyMapManager;
        OnClusterChanged -= NotifyGlobeManager;
    }

    void Update()
    {
        if (Input.GetKeyDown(KeyCode.RightArrow)) CycleNext();
        if (Input.GetKeyDown(KeyCode.LeftArrow))  CyclePrev();
        if (Input.GetKeyDown(KeyCode.Escape))      SelectAll();
    }

    // ── Public API ───────────────────────────────────────────

    /// <summary>Select directly by index. -1 = ALL</summary>
    public void Select(int index)
    {
        int clamped = Mathf.Clamp(index, -1, 11);
        if (clamped == SelectedIndex) return;   // ignore if unchanged

        SelectedIndex = clamped;
        OnClusterChanged?.Invoke(SelectedIndex);

        Debug.Log($"[ClusterSelector] → {GetDisplayLabel()}");
    }

    /// <summary>Move to the next cluster. From the last one (11) → wraps to ALL (-1)</summary>
    public void CycleNext() => Select(SelectedIndex >= 11 ? -1 : SelectedIndex + 1);

    /// <summary>Move to the previous cluster. From ALL (-1) ← → wraps to the last one (11)</summary>
    public void CyclePrev() => Select(SelectedIndex <= -1 ? 11 : SelectedIndex - 1);

    /// <summary>Return to the full view</summary>
    public void SelectAll()  => Select(-1);

    /// <summary>For calling from UI buttons (1-based label: 1~12)</summary>
    public void SelectByLabel(int label) => Select(label - 1);

    /// <summary>Display string for the current selection state</summary>
    public string GetDisplayLabel() =>
        SelectedIndex < 0 ? "ALL CLUSTERS" : $"C-{SelectedIndex + 1:D2}";

    // ── Event handlers ────────────────────────────────────────

    void NotifyMapManager(int idx)
    {
        if (mapManager != null)
            mapManager.ApplyClusterFilter(idx);
    }

    void NotifyGlobeManager(int idx)
    {
        if (globeManager != null)
            globeManager.ApplyClusterFilter(idx);
    }
}
