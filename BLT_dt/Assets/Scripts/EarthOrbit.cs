using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class EarthOrbit : MonoBehaviour
{
    //private float angle = 0f;
    //private float selfRotateAngle = 0f;

    //[SerializeField] private float orbitSpeed = 1f;
    //[SerializeField] private float orbitRadius = 1.5f;
    //[SerializeField] private float selfRotateSpeed = 0.15f;

    public double px = 0;
    public double py = 0;
    public double pz = 0;
    public double vx = 0;
    public double vy = 0;
    public double vz = 0;
    public double orbit_cycle = 0;

    [SerializeField] private double radius = 0;
    [SerializeField] private double px_normal = 0;
    [SerializeField] private double py_normal = 0;
    [SerializeField] private double pz_normal = 0;
    [SerializeField] private double vx_normal = 0;
    [SerializeField] private double vy_normal = 0;
    [SerializeField] private double vz_normal = 0;
    [SerializeField] private double angle = 0;
    [SerializeField] private double angle_speed = 0;


    void Start()
    {
        radius = Math.Sqrt(px*px + py*py + pz*pz);
        px_normal = px / radius;
        py_normal = py / radius;
        pz_normal = pz / radius;
        double temp = Math.Sqrt(vx * vx + vy * vy + vz * vz);
        vx_normal = vx / temp;
        vy_normal = vy / temp;
        vz_normal = vz / temp;
    }

    // Update is called once per frame
    void FixedUpdate()
    {
        if (angle >= 2 * Mathf.PI)
        {
            angle = 0;
        }

        var p_coeff = Mathf.Cos((float)angle);
        var v_coeff = Mathf.Sin((float)angle);

        var xPos = radius * (p_coeff * px_normal + v_coeff * vx_normal);
        var yPos = radius * (p_coeff * py_normal + v_coeff * vy_normal);
        var zPos = radius * (p_coeff * pz_normal + v_coeff * vz_normal);

        transform.localPosition = new Vector3((float)xPos, (float)yPos, (float)zPos);

        transform.LookAt(new Vector3(1f, 1f, 1f));
        //transform.rotation = Quaternion.Euler(0, 0, 0);

        angle_speed = (orbit_cycle / 24 / 60 / 60) * 2 * Mathf.PI / 50;

        angle = angle + angle_speed; // fixedupdate 0.02s

        //transform.Rotate(selfRotateAngle, selfRotateAngle, 0f);
        //selfRotateAngle += selfRotateSpeed * Time.deltaTime;
    }
}
