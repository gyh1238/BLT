using UnityEngine;
using UnityEngine.UI;
using TMPro;

/// <summary>
/// Applies the NASA mission control color theme to the entire UI at runtime
/// Add to Manager_Root, Apply On Start = true
/// </summary>
public class NasaThemeApplier : MonoBehaviour
{
    [Header("Targets")]
    public Canvas             targetCanvas;
    public TMP_FontAsset      fontAsset;      // Link the JetBrains Mono asset

    [Header("Options")]
    public bool applyOnStart  = true;
    public bool addBorders    = true;
    public float borderWidth  = 1.5f;

    // ── NASA color palette ─────────────────────────────────────
    public static class C
    {
        public static readonly Color BG        = Hex("020810"); // background
        public static readonly Color PANEL     = Hex("030c18"); // panel
        public static readonly Color BORDER    = Hex("0a3a6e"); // border
        public static readonly Color ACCENT    = Hex("00b4ff"); // cyan accent
        public static readonly Color TEXT      = Hex("7ec8e3"); // default text
        public static readonly Color TEXT_DIM  = Hex("3a6a8a"); // dimmed text
        public static readonly Color OK        = Hex("00c87a"); // normal
        public static readonly Color WARN      = Hex("ff9f1c"); // warning
        public static readonly Color CELL_BG   = Hex("040f1e"); // cell background

        static Color Hex(string h)
        {
            ColorUtility.TryParseHtmlString("#" + h, out Color c);
            return c;
        }
    }

    void Start()
    {
        if (applyOnStart) Apply();
    }

    [ContextMenu("Apply NASA Theme")]
    public void Apply()
    {
        if (targetCanvas == null)
            targetCanvas = FindObjectOfType<Canvas>();
        if (targetCanvas == null) return;

        ApplyToAll(targetCanvas.transform);
        Debug.Log("[NasaTheme] applied");
    }

    void ApplyToAll(Transform root)
    {
        foreach (Transform t in root)
        {
            string name = t.name.ToLower();

            // ── Image background color ──────────────────────────────────
            var img = t.GetComponent<Image>();
            if (img != null && img.sprite == null)
            {
                if (IsBottomCell(name))
                    img.color = C.CELL_BG;
                else if (IsPanel(name))
                    img.color = C.PANEL;
                else if (IsStatusBar(name))
                    img.color = new Color(C.BG.r, C.BG.g, C.BG.b, 0.95f);
                else if (IsBackground(name))
                    img.color = C.PANEL;
            }

            // ── TextMeshPro color ──────────────────────────────
            var tmp = t.GetComponent<TextMeshProUGUI>();
            if (tmp != null)
            {
                // Apply the font
                if (fontAsset != null)
                    tmp.font = fontAsset;

                // Leave value texts whose color is already set (RMSE value, OK, etc.) untouched
                // Apply the theme color only to Label and Title texts
                if (IsTitle(name))
                {
                    tmp.color    = C.ACCENT;
                    tmp.fontSize = Mathf.Max(tmp.fontSize, 13f);
                    tmp.fontStyle = FontStyles.Bold;
                }
                else if (IsLabel(name))
                    tmp.color = C.TEXT;
                else if (IsValueText(name))
                {
                    // Keep the current color for value texts (green/orange, etc., set by scripts)
                    if (tmp.color == Color.white)
                        tmp.color = C.TEXT;
                }
            }

            // ── Add border ───────────────────────────────────
            if (addBorders && IsBottomCell(name) && img != null)
                AddBorder(t, C.BORDER);

            ApplyToAll(t);
        }
    }

    // ── Object name classification ────────────────────────────────────
    bool IsBottomCell(string n)  => n.StartsWith("cell_");
    bool IsPanel(string n)       => n.Contains("panel") || n.Contains("background");
    bool IsStatusBar(string n)   => n.Contains("statusbar") || n.Contains("line1bg") || n.Contains("line2bg");
    bool IsBackground(string n)  => n == "background";
    bool IsTitle(string n)       => n.Contains("title") || n.Contains("titletext");
    bool IsLabel(string n)       => n == "label";
    bool IsValueText(string n)   => n == "value";

    // ── Add 4 border lines ───────────────────────────────────────
    void AddBorder(Transform parent, Color col)
    {
        // Skip if it already exists
        if (parent.Find("__border__") != null) return;

        var container = new GameObject("__border__");
        container.transform.SetParent(parent, false);
        var crt = container.AddComponent<RectTransform>();
        crt.anchorMin = Vector2.zero;
        crt.anchorMax = Vector2.one;
        crt.offsetMin = Vector2.zero;
        crt.offsetMax = Vector2.zero;

        string[] sides = { "Top", "Bottom", "Left", "Right" };
        foreach (var side in sides)
            MakeLine(container.transform, side, col);
    }

    void MakeLine(Transform parent, string side, Color col)
    {
        var go = new GameObject(side);
        go.transform.SetParent(parent, false);
        var img = go.AddComponent<Image>();
        img.color = col;
        img.raycastTarget = false;

        var rt = go.GetComponent<RectTransform>();
        switch (side)
        {
            case "Top":
                rt.anchorMin = new Vector2(0, 1);
                rt.anchorMax = new Vector2(1, 1);
                rt.offsetMin = new Vector2(0, -borderWidth);
                rt.offsetMax = Vector2.zero;
                break;
            case "Bottom":
                rt.anchorMin = Vector2.zero;
                rt.anchorMax = new Vector2(1, 0);
                rt.offsetMin = Vector2.zero;
                rt.offsetMax = new Vector2(0, borderWidth);
                break;
            case "Left":
                rt.anchorMin = Vector2.zero;
                rt.anchorMax = new Vector2(0, 1);
                rt.offsetMin = Vector2.zero;
                rt.offsetMax = new Vector2(borderWidth, 0);
                break;
            case "Right":
                rt.anchorMin = new Vector2(1, 0);
                rt.anchorMax = Vector2.one;
                rt.offsetMin = new Vector2(-borderWidth, 0);
                rt.offsetMax = Vector2.zero;
                break;
        }
    }
}
