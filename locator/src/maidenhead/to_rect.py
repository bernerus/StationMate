import typing as T

from . import to_location


def to_rect(maiden: str) -> T.Tuple[float, float, float, float, float, float]:
    """
    convert Maidenhead grid to a tuple containing north, south, west, east values of the limits and the location of the center of the given square
    of the given locator.

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
    if not 12 >= N >= 2 and N % 2 == 0:
        raise ValueError("Maidenhead locator requires 2-12 characters, even number of characters")

    south, west = to_location(maiden)

    lonsize = 20
    latsize = 10

    if N == 2:
        east = west + lonsize
        north = south + latsize

        return north, south, west, east, south + latsize/2, west + lonsize/2

    lonsize /= 10
    latsize /= 10

    if N == 4:
        east = west + lonsize
        north = south + latsize

        return north, south, west, east, south + latsize / 2, west + lonsize / 2

    lonsize /= 24
    latsize /= 24

    if N == 6:
        east = west + lonsize
        north = south + latsize

        return north, south, west, east, south + latsize / 2, west + lonsize / 2

    lonsize /= 10
    latsize /= 10

    if N == 8:
        east = west + lonsize
        north = south + latsize

        return north, south, west, east, south + latsize / 2, west + lonsize / 2

    lonsize /= 24
    latsize /= 24

    if N == 10:
        east = west + lonsize
        north = south + latsize

        return north, south, west, east, south + latsize / 2, west + lonsize / 2

    lonsize /= 10
    latsize /= 10

    if N == 12:
        east = west + lonsize
        north = south + latsize

        return north, south, west, east, south + latsize / 2, west + lonsize / 2
