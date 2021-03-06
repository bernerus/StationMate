import typing as T


def to_location(maiden: str) -> T.Tuple[float, float]:
    """
    convert Maidenhead grid to latitude, longitude

    Parameters
    ----------

    maiden : str
        Maidenhead grid locator of length 2 to 8

    Returns
    -------

    latLon : tuple of float
        Geographic latitude, longitude
    """

    maiden = maiden.strip().upper()

    N = len(maiden)
    if not 12 >= N >= 2 or N % 2 != 0:
        raise ValueError("Maidenhead locator requires 2-10characters, even number of characters")

    Oa = ord("A")
    lon = -180.0
    lat = -90.0
    # %% first pair
    lon += (ord(maiden[0]) - Oa) * 20
    lat += (ord(maiden[1]) - Oa) * 10
    # %% second pair
    if N >= 4:
        lon += int(maiden[2]) * 2
        lat += int(maiden[3]) * 1
    # %%
    if N >= 6:
        lon += (ord(maiden[4]) - Oa) * 5.0 / 60
        lat += (ord(maiden[5]) - Oa) * 2.5 / 60
    # %%
    if N >= 8:
        lon += int(maiden[6]) * 5.0 / 600
        lat += int(maiden[7]) * 2.5 / 600
    if N >= 10:
        lon += (ord(maiden[8]) - Oa) * 5.0 / 600 / 24
        lat += (ord(maiden[9]) - Oa) * 2.5 / 600 / 24
    if N >= 12:
        lon += int(maiden[10]) * 5.0 /  600 / 240
        lat += int(maiden[11]) *  2.5 / 600 / 240

    # %%

    return lat, lon
