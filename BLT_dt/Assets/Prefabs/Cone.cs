using UnityEngine;

[RequireComponent(typeof(MeshFilter))]
public class Cone : MonoBehaviour
{
    public float height = 1f;
    public float radius = 0.5f;
    public int segments = 20;

    void Start()
    {
        MeshFilter mf = GetComponent<MeshFilter>();
        mf.mesh = GenerateCone(radius, height, segments);
    }

    Mesh GenerateCone(float radius, float height, int segments)
    {
        Mesh mesh = new Mesh();
        Vector3[] vertices = new Vector3[segments + 2];
        int[] triangles = new int[segments * 3];

        vertices[0] = Vector3.up * height;
        for (int i = 0; i < segments; i++)
        {
            float angle = (float)i / segments * Mathf.PI * 2;
            vertices[i + 1] = new Vector3(Mathf.Cos(angle) * radius, 0, Mathf.Sin(angle) * radius);
        }
        vertices[segments + 1] = Vector3.zero;

        for (int i = 0; i < segments; i++)
        {
            triangles[i * 3] = 0;
            triangles[i * 3 + 1] = i + 1;
            triangles[i * 3 + 2] = (i + 1) % segments + 1;
        }

        mesh.vertices = vertices;
        mesh.triangles = triangles;
        mesh.RecalculateNormals();
        return mesh;
    }
}
