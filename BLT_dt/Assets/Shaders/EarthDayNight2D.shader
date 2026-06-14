Shader "Custom/EarthDayNight2D"
{
    Properties
    {
        _DayTex      ("Day Texture",            2D)                 = "white" {}
        _NightTex    ("Night Texture",          2D)                 = "black" {}
        _SunLon      ("Sun Longitude (deg)",    Float)              = 0.0
        _SunDecl     ("Sun Declination (deg)",  Float)              = 11.0
        _BlendWidth  ("Terminator Blend Width", Range(0.005, 0.08)) = 0.02
        _NightDark   ("Night Darkness",         Range(0.0, 1.0))    = 0.3
        _NightTint   ("Night Tint",             Color)              = (0.04, 0.07, 0.14, 1.0)
    }

    SubShader
    {
        Tags { "Queue"="Geometry" "RenderType"="Opaque" }
        Lighting Off
        ZWrite On
        Cull Off

        Pass
        {
            CGPROGRAM
            #pragma vertex   vert
            #pragma fragment frag
            #include "UnityCG.cginc"

            sampler2D _DayTex;
            sampler2D _NightTex;
            float  _SunLon;
            float  _SunDecl;
            float  _BlendWidth;
            float  _NightDark;
            fixed4 _NightTint;

            struct appdata { float4 vertex : POSITION; float2 uv : TEXCOORD0; };
            struct v2f     { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; };

            v2f vert(appdata v)
            {
                v2f o;
                o.pos = UnityObjectToClipPos(v.vertex);
                o.uv  = v.uv;
                return o;
            }

            fixed4 frag(v2f i) : SV_Target
            {
                float lon = (i.uv.x - 0.5) * 2.0 * UNITY_PI;
                float lat = (0.5 - i.uv.y) * UNITY_PI;

                float sunLonRad  = _SunLon  * (UNITY_PI / 180.0);
                float sunDeclRad = _SunDecl * (UNITY_PI / 180.0);

                float elevation =
                    sin(lat) * sin(sunDeclRad) +
                    cos(lat) * cos(sunDeclRad) * cos(lon - sunLonRad);

                float t = smoothstep(-_BlendWidth, _BlendWidth, elevation);

                fixed4 dayColor  = tex2D(_DayTex,   i.uv);
                fixed4 rawNight  = tex2D(_NightTex,  i.uv);
                float  cityLight = max(rawNight.r, max(rawNight.g, rawNight.b));
                fixed4 cityGlow  = fixed4(1.0, 0.95, 0.7, 1.0) * pow(cityLight, 2.0) * 0.5;
                fixed4 nightColor = _NightTint * _NightDark + cityGlow;

                return lerp(nightColor, dayColor, t);
            }
            ENDCG
        }
    }
}
