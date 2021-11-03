
`maidenhead` provides a simple, yet effective location hashing algorithm.
Maidenhead allows abvitrary precision depending on the length of the locator code.

This code is a fork of the maidenhead package by Michael Hirsch, extended 
for increased precision. This extensions are however not agreed upon in the 
Maidenhead system, therefore I have chosen to not attempt to include
the changes in the published code.

----

This code provides 8 levels of increasing accuracy

  Level |  Precision       | Latitude distance |  Example code
--------|------------------------------------------------------
  1     |  10x20°          | 1113 km           |  IO
  2     |  1x2°            | 111 km            |  IO91
  3     |  2.5 x 5'        | 4.6 km            |  IO91wm
  4     |  15 x 30"        | 463 m             |  IO91wm41
  5*    |  0.625 x 1.25"   | 19.3 m            |  IO91wm41pu
  6*    |  0.0625 x 0.125" | 1.9 m             |  IO91wm41pu67

(IN91wm41pu67 is very near the center of Nelson's column at 
Trafalgar Square, London UK.)

* The levels 5 and 6 are not internationally agreed upon. 
  Here they are a recursive extension of the levels 3 and 4

## Examples

All examples assume first doing

```python
import locator as mh
```

### lat lon to Maidenhead locator

```python
mh.to_maiden(lat, lon, level)
```

returns a char (len = lvl*2)

### Maidenhead locator to lat lon

```python
mh.to_location('AB01cd')
```

takes Maidenhead location string and returns top-left lat, lon of Maidenhead grid square.

## Command Line

The command line interface takes either decimal degrees for "latitude longitude" or the Maidenhead locator string:

```sh
maidenhead 65.0 -148.0
```

> BP65aa

```sh
maidenhead BP65aa12
```

> 65.0083 -147.9917

The "python -m" CLI is also available:

```sh
python -m maidenhead 65.0 -148.0
```


## Alternatives

We also have
[Maidenhead conversion for Julia](https://github.com/space-physics/maidenhead-julia).

Open Location Codes a.k.a Plus Codes are in
[Python code by Google](https://github.com/google/open-location-code/tree/master/python).
