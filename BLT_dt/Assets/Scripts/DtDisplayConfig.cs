using UnityEngine;

/// <summary>
/// Global display policy for the digital twin: what to show when a data source
/// (the BLT chain RPC, or the BLT_simul RMSE server/file) is NOT connected.
///
///   showFallbackValues = true  (default)
///       Disconnected panels fall back to synthetic/default values
///       (sine-wave RMSE, simulated block ticker, random proposer, default
///       counts) so the demo keeps moving without any backend running.
///
///   showFallbackValues = false
///       Disconnected panels show a neutral placeholder ("—") instead of any
///       fabricated value, so the UI honestly reflects "no live data".
///
/// Add ONE DtDisplayConfig to the scene (e.g. on Manager_Root) and toggle it in
/// the inspector or at runtime via SetShowFallback(). All panels read the static
/// accessors, so the absence of a config object is safe (defaults to fallback on,
/// preserving the original behaviour).
/// </summary>
public class DtDisplayConfig : MonoBehaviour
{
    public static DtDisplayConfig Instance { get; private set; }

    [Header("Offline display")]
    [Tooltip("ON: show synthetic/default values when a source is disconnected. " +
             "OFF: show the placeholder instead (honest 'no data').")]
    public bool   showFallbackValues = true;

    [Tooltip("Text shown for a value whose source is offline while fallback is OFF.")]
    public string placeholder = "—";

    // Static accessors — safe when no config object exists (fallback stays on).
    public static bool   ShowFallback => Instance == null || Instance.showFallbackValues;
    public static string Placeholder  => Instance != null ? Instance.placeholder : "—";

    void Awake()
    {
        if (Instance != null && Instance != this) { Destroy(this); return; }
        Instance = this;
    }

    /// <summary>Runtime toggle (e.g. wire to a UI button / keypress).</summary>
    public void SetShowFallback(bool on) => showFallbackValues = on;
    public void ToggleShowFallback()      => showFallbackValues = !showFallbackValues;
}
