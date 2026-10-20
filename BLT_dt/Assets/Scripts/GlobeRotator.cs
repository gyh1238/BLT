using UnityEngine;
using UnityEngine.EventSystems;

/// <summary>
/// Rotates Globe3D by mouse-dragging over the GlobePanel (RawImage).
/// Attach to the GlobePanel GameObject.
/// Requires the Globe3D Transform to be assigned.
/// </summary>
public class GlobeRotator : MonoBehaviour,
    IPointerDownHandler, IDragHandler, IPointerUpHandler
{
    [Header("References")]
    public Transform globeTransform;   // Globe3D

    [Header("Settings")]
    public float rotateSpeed = 0.3f;   // Drag sensitivity
    public bool  invertX     = false;
    public bool  invertY     = false;

    private bool    _dragging  = false;
    private Vector2 _lastPos;

    public void OnPointerDown(PointerEventData e)
    {
        _dragging = true;
        _lastPos  = e.position;
    }

    public void OnDrag(PointerEventData e)
    {
        if (!_dragging || globeTransform == null) return;

        Vector2 delta = e.position - _lastPos;
        _lastPos = e.position;

        float dx = delta.x * rotateSpeed * (invertX ? 1 : -1);
        float dy = delta.y * rotateSpeed * (invertY ? 1 : -1);

        // Yaw around the world Y axis; pitch around the world right vector
        globeTransform.Rotate(Vector3.up,   dx, Space.World);
        globeTransform.Rotate(Vector3.right, dy, Space.World);
    }

    public void OnPointerUp(PointerEventData e)
    {
        _dragging = false;
    }
}
