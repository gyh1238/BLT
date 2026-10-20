import io
import requests
import configparser
from skyfield.api import EarthSatellite
from skyfield.api import load
import math

EARTH_RADIUS_KM = 6371.0
# Plausible LEO band for the Starlink file; anything outside it is a bad propagation.
MIN_ALTITUDE_KM = 200.0
MAX_ALTITUDE_KM = 2000.0


def get_sat_from_spacetrack(number_of_sat):
    class MyError(Exception):
        def __init___(self, args):
            Exception.__init__(self, "my exception was raised with arguments {0}".format(args))
            self.args = args
    uriBase = "https://www.space-track.org"
    requestLogin = "/ajaxauth/login"
    requestCmdAction = "/basicspacedata/query"
    requestFindStarlinks = (
        "/class/tle_latest/NORAD_CAT_ID/>40000/ORDINAL/1"
        "/OBJECT_NAME/STARLINK~~/DECAYED/0/format/tle"
        "/orderby/NORAD_CAT_ID%20asc"
    )
    _requestOMMStarlink1 = "/class/omm/NORAD_CAT_ID/"  # noqa: F841
    _requestOMMStarlink2 = "/orderby/EPOCH%20asc/format/json"  # noqa: F841
    config = configparser.ConfigParser()
    config.read("./data/SLTrack.ini")
    configUsr = config.get("configuration", "username")
    configPwd = config.get("configuration", "password")
    siteCred = {'identity': configUsr, 'password': configPwd}
    with requests.Session() as session:
        resp = session.post(uriBase + requestLogin, data=siteCred)
        if resp.status_code != 200:
            raise MyError(resp, "POST fail on login")
        resp = session.get(uriBase + requestCmdAction + requestFindStarlinks)
        if resp.status_code != 200:
            print(resp)
            raise MyError(resp, "GET fail on request for Starlink satellites")
        session.close()

    ALL_TLE_DATA = resp.text
    ALL_TLE_DATA = ALL_TLE_DATA.split('\r\n')

    ts = load.timescale()
    earthsat_list = []
    for i in range(int(len(ALL_TLE_DATA) / 2)):
        earthsat_list.append(EarthSatellite(ALL_TLE_DATA[2 * i], ALL_TLE_DATA[2 * i + 1], str(i) + 'th STARLINK', ts))

    t_now = ts.now()
    geo_list = []
    pos_list = []
    vel_list = []
    for i in range(int(len(earthsat_list))):
        geo_list.append(earthsat_list[i].at(t_now))
    for i in range(int(len(earthsat_list))):
        pos_list.append(geo_list[i].position.km)
        vel_list.append(geo_list[i].velocity.km_per_s.tolist())
    name_list = []
    for i in range(int(len(earthsat_list))):
        name_list.append(earthsat_list[i].model.satnum)

    return (earthsat_list[:number_of_sat], t_now,
            name_list[:number_of_sat], pos_list[:number_of_sat],
            vel_list[:number_of_sat])


def read_tle_lines(path):
    """The element lines of a two-line set, whatever the file's line endings.

    Space-Track serves plain `1 ...` / `2 ...` pairs. A file that has been
    through a text editor or a Windows transfer can carry CR, CRLF or the
    CR CR LF an unconverted download leaves, and a name line above each pair
    is also common. Blank lines and name lines are dropped, so the caller
    sees the same pairs either way.
    """
    with io.open(path, 'r', encoding='utf-8', errors='ignore', newline='') as f:
        raw = f.read()
    raw = raw.replace('\r\n', '\n').replace('\r', '\n')
    return [ln.rstrip() for ln in raw.split('\n')
            if ln.strip().startswith(('1 ', '2 '))]


def get_sat_from_text(number_of_sat):
    filePath = './data/STARLINK_TLE.txt'
    lines = read_tle_lines(filePath)

    ts = load.timescale()
    earthsat_list = []
    for i in range(len(lines) // 2):
        l1, l2 = lines[2 * i], lines[2 * i + 1]
        if not (l1.startswith('1 ') and l2.startswith('2 ')):
            continue            # a stray line would otherwise pair the wrong two
        earthsat_list.append(EarthSatellite(l1, l2, str(i) + ' sat', ts))

    if not earthsat_list:
        raise ValueError(
            "no two-line element pairs in " + filePath + ". The file should "
            "hold '1 ...' and '2 ...' lines in pairs; see data/README.md.")


    t_fixed = ts.utc(2022, 9, 2, 6, 0, 0)

    geo_list = []
    pos_list = []
    vel_list = []
    name_list = []
    vel_ang_list = []
    for i in range(int(len(earthsat_list))):
        geo_list.append(earthsat_list[i].at(t_fixed))

    for i in range(int(len(earthsat_list))):
        pos = geo_list[i].position.km.tolist()
        if math.isnan(pos[0]):
            continue
        # Propagating to the fixed epoch is only valid for TLEs that existed
        # then. 202 of the 2,554 entries were issued after 2022-09-02, and SGP4
        # run backwards past their launch returns positions inside the Earth
        # (altitudes down to -5,500 km) rather than NaN. None of them sit in the
        # first 2,000 entries, so N <= 2,000 was never affected; N = 8,192 pads
        # by copying base satellites and inherited them.
        altitude_km = math.sqrt(pos[0] ** 2 + pos[1] ** 2 + pos[2] ** 2) - EARTH_RADIUS_KM
        if not (MIN_ALTITUDE_KM <= altitude_km <= MAX_ALTITUDE_KM):
            continue
        pos_list.append(pos)
        vel_list.append(geo_list[i].velocity.km_per_s.tolist())
        name_list.append(earthsat_list[i].model.satnum)
        vel_ang_list.append(earthsat_list[i].model.no_kozai / 60)

    return name_list[:number_of_sat], pos_list[:number_of_sat], vel_list[:number_of_sat], vel_ang_list[:number_of_sat]

