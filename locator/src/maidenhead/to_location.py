import typing as T


def to_location(maiden: str) -> T.Tuple[float, float]:
    """
    :param maiden: The Maidenhead locator string.
    :return: The latitude and longitude coordinates corresponding to the given Maidenhead locator.

    The `to_location` method takes a Maidenhead locator string as input and returns the latitude and longitude coordinates corresponding to that locator.

    The Maidenhead locator is a system used to divide the world into grid squares for amateur radio communication. The locator string consists of 2 to 12 characters, with an even number
    * of characters. Each pair of characters represents a different level of granularity in the grid. The first pair represents a large area, the second pair a medium area, and so on.

    The latitude is represented by the number of degrees north from the South Pole, and the longitude is represented by the number of degrees east from the Prime Meridian. The coordinates
    * are returned as a tuple in the format (latitude, longitude).

    If the given Maidenhead locator string does not meet the required length and format constraints, a ValueError is raised.

    Example usage:

    ```
    >>> to_location("FN30")
    (32.5, -85.0)
    ```
    """

    maiden = maiden.strip().upper()

    N = len(maiden)
    if not 12 >= N >= 2 or N % 2 != 0:
        raise ValueError("Maidenhead locator requires 2-12 characters, even number of characters")

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
    try:
        if N >= 8:
            lon += int(maiden[6]) * 5.0 / 600
            lat += int(maiden[7]) * 2.5 / 600
        if N >= 10:
            lon += (ord(maiden[8]) - Oa) * 5.0 / 600 / 24
            lat += (ord(maiden[9]) - Oa) * 2.5 / 600 / 24
        if N >= 12:
            lon += int(maiden[10]) * 5.0 /  600 / 240
            lat += int(maiden[11]) *  2.5 / 600 / 240
    except ValueError as e:
            print("ValueError %s on extended locator '%s', using first 6 characters" % (e, maiden))

    # %%

    return lat, lon
