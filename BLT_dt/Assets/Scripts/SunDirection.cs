using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class SunDirection : MonoBehaviour
{
    DateTime fixed_time;
    double DeclinationAngle;
    Vector3 SunPosVec_part1;
    Vector3 SunPosVec_part2;
    double SunAngle;
    Vector3 SunPosVec;

    // Start is called before the first frame update
    void Start()
    {
        //DateTime now_time = DateTime.Now;
        //Vector3 sun_pos = GetSunDirection(now_time);
        //Debug.Log(now_time);
        //Debug.Log(sun_pos);

        //DateTime fixed_time1 = new DateTime(2022, 09, 01, 21, 0, 0);
        //Vector3 sun_pos1 = GetSunDirection(fixed_time1);
        //Debug.Log(sun_pos1);

        //DateTime fixed_time2 = new DateTime(2022, 09, 02, 21, 0, 0);
        //Vector3 sun_pos2 = GetSunDirection(fixed_time2);
        //Debug.Log(sun_pos2);

        fixed_time = new DateTime(2022, 12, 22, 1, 0, 0);
        DeclinationAngle = CalculateDeclinationAngle(fixed_time);
        SunPosVec_part1 = new Vector3((float)Math.Cos(DeclinationAngle), (float)Math.Sin(DeclinationAngle), 0.0f);
        SunPosVec_part2 = new Vector3(0.0f, 0.0f, -1.0f);
        SunAngle = 0;
        SunPosVec = (float)Math.Cos(SunAngle) * SunPosVec_part1 + (float)Math.Sin(SunAngle) * SunPosVec_part2;

        //    var p_coeff = Mathf.Cos((float)angle);
        //    var v_coeff = Mathf.Sin((float)angle);
    }

    // Update is called once per frame
    void Update()
    {
        SunAngle += 0.01;
        if (SunAngle >= 2 * Math.PI)
        {
            fixed_time = fixed_time.AddDays(30);
            DeclinationAngle = CalculateDeclinationAngle(fixed_time);
            SunPosVec_part1 = new Vector3((float)Math.Cos(DeclinationAngle), (float)Math.Sin(DeclinationAngle), 0.0f);
            SunPosVec_part2 = new Vector3(0.0f, 0.0f, -1.0f);
            SunAngle = 0;
        }
        SunPosVec = (float)Math.Cos(SunAngle) * SunPosVec_part1 + (float)Math.Sin(SunAngle) * SunPosVec_part2;
        transform.rotation = Quaternion.LookRotation(SunPosVec);
    }

    //public static Vector3 GetSunDirection(DateTime time)
    //{
    //    time = time.ToUniversalTime();
    //    double JD = 367 * time.Year - Math.Floor(7.0 * (time.Year + Math.Floor((time.Month + 9.0) / 12.0)) / 4.0) + Math.Floor(275.0 * time.Month / 9.0) + time.Day + 1721013.5 + time.Hour / 24.0 + time.Minute / 1440.0 + time.Second / 86400.0;
    //    double pi = 3.14159265359;
    //    double UT1 = (JD - 2451545) / 36525;
    //    double longMSUN = 280.4606184 + 36000.77005361 * UT1;
    //    double mSUN = 357.5277233 + 35999.05034 * UT1;
    //    double ecliptic = longMSUN + 1.914666471 * Math.Sin(mSUN * pi / 180) + 0.918994643 * Math.Sin(2 * mSUN * pi / 180);
    //    double eccen = 23.439291 - 0.0130042 * UT1;

    //    double x = Math.Cos(ecliptic * pi / 180);
    //    double y = Math.Cos(eccen * pi / 180) * Math.Sin(ecliptic * pi / 180);
    //    double z = Math.Sin(eccen * pi / 180) * Math.Sin(ecliptic * pi / 180);

    //    return new Vector3(Convert.ToSingle(x), Convert.ToSingle(y), Convert.ToSingle(z));
    //}

    public double CalculateDeclinationAngle(DateTime time)
    {
        time = time.ToUniversalTime();
        double DayNumber = time.DayOfYear;
        //Debug.Log(DayNumber);
        var temp = (2 * Math.PI) * ((284 + DayNumber) / 365.25);
        return 23.45 * (Math.PI / 180) * Math.Sin(temp);
    }
}
