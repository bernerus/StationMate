import typing as T

from . import to_location


def to_rect(maiden: str) -> T.Tuple[float, float, float, float, float, float]:
    """
    Convert Maidenhead locator to rectangular coordinates.

    :param maiden: Maidenhead locator.
    :return: Tuple containing north, south, west, east, latitude center, longitude center.
    :raises ValueError: If the length of maiden is not between 2 and 12 (inclusive) or if it does not have an even
        number of characters.
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
