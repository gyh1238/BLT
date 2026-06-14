using System;
using System.Collections;
using System.Collections.Generic;
using System.Net;
using UnityEngine;
using System.Collections.Specialized;
using Zeptomoby.OrbitTools;

public class maggellan_generator : MonoBehaviour
{
    public GameObject maggellanPrefab;

    //float span = 1.0f;
    //float delta = 0;

    public class SpaceTrack
    {
        public class WebClientEx : WebClient
        {
            private CookieContainer _cookieContainer = new CookieContainer();

            protected override WebRequest GetWebRequest(Uri address)
            {
                WebRequest request = base.GetWebRequest(address);

                if (request is HttpWebRequest)
                    (request as HttpWebRequest).CookieContainer = _cookieContainer;

                return request;
            }
        }   // END WebClient Class

        public static string GetSpaceTrack()
        {
            string uriBase = "https://www.space-track.org";
            string requestController = "/basicspacedata";
            string requestAction = "/query";
            string requestFindStarlinks = "/class/tle_latest/NORAD_CAT_ID/>40000/ORDINAL/1/OBJECT_NAME/STARLINK~~/DECAYED/0/format/tle/orderby/NORAD_CAT_ID%20asc";   // for starlink
            //string requestFindStarlinks = "/class/tle_latest/ORDINAL/1/DECAYED/0/format/tle/orderby/NORAD_CAT_ID%20asc";     // for all
            //string requestFindStarlinks = "/class/tle_latest/ORDINAL/1/DECAYED/0/EPOCH/>now-30/format/tle/orderby/NORAD_CAT_ID%20asc";     // for all
            //string requestFindStarlinks = "/class/tle_latest/ORDINAL/1/DECAYED/0/NORAD_CAT_ID/<>50924/EPOCH/>now-30/format/tle/orderby/NORAD_CAT_ID%20asc";     // for all
            //string requestFindStarlinks = "/class/tle_latest/ORDINAL/1/DECAYED/0/NORAD_CAT_ID/<>50924/EPOCH/>now-30/MEAN_MOTION/>11.25/format/tle/orderby/NORAD_CAT_ID%20asc";     // for all

            string request = uriBase + requestController + requestAction + requestFindStarlinks;

            // Create new WebClient object to communicate with the service
            using (var client = new WebClientEx())
            {
                // Store the user authentication information.
                // Fill in your own Space-Track account (https://www.space-track.org).
                // Left blank intentionally — do NOT commit real credentials.
                var data = new NameValueCollection
                {
                    { "identity", "" },
                    { "password", "" },
                };

                // Generate the URL for the API Query and return the response
                var response2 = client.UploadValues(uriBase + "/ajaxauth/login", data);
                var response4 = client.DownloadData(request);

                return (System.Text.Encoding.Default.GetString(response4));
            }
        }   // END GetSpaceTrack()

        public static Eci PrintPosVel(Tle tle)
        {
            Satellite sat = new Satellite(tle);
            DateTime now_time = DateTime.Now.ToUniversalTime();
            DateTime epoch_time = tle.EpochJulian.ToTime();

            double mpe = now_time.Subtract(epoch_time).TotalMinutes;

            Eci eci = sat.PositionEci(mpe);

            return eci;
        }
    }   // END SpaceTrack Class

    public GameObject[] SatelliteArr;
    public int SatelliteArrSize;

    // Start is called before the first frame update
    void Start()
    {
        string result = SpaceTrack.GetSpaceTrack();
        string[] result_parts = result.Split(new[] { '\n' });
        List<GameObject> SatelliteList = new List<GameObject>();
        List<Eci> EciList = new List<Eci>();
        List<Tle> TleList = new List<Tle>();
        //SatelliteArrSize = result_parts.Length / 2;
        //SatelliteArr = new GameObject[SatelliteArrSize];

        for (int i = 0; i < result_parts.Length - 1; i = i + 2)
        {
            try
            {
                string tle_str1 = (i / 2 + 1).ToString() + "th Starlink";
                string tle_str2 = result_parts[i];
                string tle_str3 = result_parts[i + 1];
                Tle tle = new Tle(tle_str1, tle_str2, tle_str3);
                TleList.Add(tle);

                Eci eci = SpaceTrack.PrintPosVel(tle);
                EciList.Add(eci);
            }
            catch
            {

            }
        }

        for (int j =0; j < EciList.Count; j++)
        {
            try
            {
                double px = EciList[j].Position.X / 10;
                double py = EciList[j].Position.Z / 10;
                double pz = EciList[j].Position.Y / 10;
                double vx = EciList[j].Velocity.X;
                double vy = EciList[j].Velocity.Z;
                double vz = EciList[j].Velocity.Y;
                double orbit_cycle = double.Parse(TleList[j].MeanMotion.Split(' ')[0]);

                GameObject thisObject = Instantiate(maggellanPrefab) as GameObject;
                SatelliteList.Add(thisObject);

                SatelliteList[j].transform.position = new Vector3((float)px, (float)py, (float)pz);
                SatelliteList[j].name = TleList[j].NoradNumber;

                EarthOrbit thisSat = GameObject.Find(TleList[j].NoradNumber).GetComponent<EarthOrbit>();
                thisSat.vx = vx;
                thisSat.vy = vy;
                thisSat.vz = vz;
                thisSat.orbit_cycle = orbit_cycle;
                thisSat.px = px;
                thisSat.py = py;
                thisSat.pz = pz;
            }
            catch
            {

            }
        }
    }

    // Update is called once per frame
    void Update()
    {
        //this.delta += Time.deltaTime;
        //if(this.delta > this.span)
        //{
        //    this.delta = 0;
        //    //GameObject go = Instantiate(maggellanPrefab) as GameObject;
        //    //int px = UnityEngine.Random.Range(-60, 60);
        //    //go.transform.position = new Vector3(px, px, px);
        //}
    }
}
