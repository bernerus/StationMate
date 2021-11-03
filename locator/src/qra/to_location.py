import typing as T


def to_location(qra: str) -> T.Tuple[float, float]:
    """
    convert QRA grid to latitude, longitude

    Parameters
    ----------

    qra : str
        QRA locator of length 5

    Returns
    -------

    lat, lon : tuple of float
        Geographic latitude, longitude
    """

    lon_chars = "UVWXYZABCDEFGHIJKLMNOPQRST"
    lat_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    lon_base = -12.0
    lat_base = 40.0

    qra = qra.strip().upper()

    N = len(qra)
    if N != 5:
        raise ValueError("QRA locator requires exactly 5 characters")

    lon = lon_base + 2.0 * lon_chars.index(qra[0])
    lat = lat_base + 1.0 * lat_chars.index(qra[1])

    qra_nr = int(qra[2:4]) -1

    lon += qra_nr % 10 * 12.0/60
    lat += (7 - int(qra_nr / 10)) * 7.5/60

    lon += "HGFAJEBCD".index(qra[4])/3 * 4.0/60 + 2.0/60
    lat += "FEDGJCHAB".index(qra[4])/3 * 2.5/60 + 1.25/60

    return lat, lon
