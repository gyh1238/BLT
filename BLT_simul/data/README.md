# `data/`, TLE input

Neither file in this directory is redistributed. Both are created locally.

## `STARLINK_TLE.txt`

The constellation is built from a two-line element set. `model/function_get_tle.py`
reads it with `get_sat_from_text`, which expects the plain Space-Track TLE format:
two lines per satellite, no name line.

```
1 44713U 19074A   26285.51782407  .00002182  00000-0  12345-3 0  9995
2 44713  53.0534 161.4304 0001432  77.0123 283.0987 15.06387300123456
```

A name line above each pair is fine and so is any line ending; `read_tle_lines`
keeps the `1 ...` and `2 ...` lines and drops the rest. Satellites outside a
200-2,000 km altitude band are then rejected as bad propagations
(`MIN_ALTITUDE_KM` / `MAX_ALTITUDE_KM`).

Elements are propagated to a fixed epoch, **2022-09-02 06:00 UTC**
(`function_get_tle.py`), so a newer file changes which satellites are in the
set and where they sit, not the instant they are placed at.

## You have to supply this file

Nothing runs without it. Every driver in `experiments/` builds its constellation through
`get_sat_from_text`, so with no `STARLINK_TLE.txt` present each one stops at a `FileNotFoundError`
before any simulation starts. There is no synthetic constellation to fall back on: the model is
written for real elements, and the padding below completes a short file rather than inventing a
whole one.

## Coverage, and what happens below it

A run at N = 8,192 needs 8,192 satellites, and the file you fetch may cover fewer. The engine pads
the difference rather than refusing to start: `_get_or_synthesize_constellation` picks a satellite
already in the set at random and rotates it about the z-axis. That keeps the altitude and the
inclination, the two properties the clustering and the ISL geometry read, and gives it a new
longitude. Padded satellites are named `SYNTH-k`, and the choice is seeded, so one file always
yields one constellation.

So a result rests on real elements up to the coverage of the file used, and on padded ones beyond
it. Padding reproduces the altitude band and the inclination spread; it does not reproduce where a
satellite sits within its plane, and the link graph is built from exactly that.

The digital twin reads the same file from `BLT_dt/Assets/StreamingAssets/STARLINK_TLE.txt`;
copy it there as well. Without it `MapManager` logs a warning and falls back to a
placeholder constellation.

## `SLTrack.ini`

Space-Track credentials, used only by `get_sat_from_spacetrack`, which fetches a
current Starlink set over the API instead of reading the file above. Create it
yourself after registering at <https://www.space-track.org>:

```ini
[configuration]
username = you@example.com
password = your-password
```

It is in `.gitignore`, together with every other `*.ini`. Do not commit it.

## Space-Track user agreement

Space-Track's terms do not permit redistributing the element sets, which is why
`STARLINK_TLE.txt` is absent here and ignored by git. Fetch your own. The results depend on the
shell the set describes, its altitude, inclination and plane spacing, rather
than on any one satellite, so a different Starlink file gives a different
constellation of the same character.
