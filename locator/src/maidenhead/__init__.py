"""
Maidenhead grid conversion <==> latitude, longitude

toMaiden([lat, lon], level) returns a char (len = lvl*2)
toLoc(mloc) takes any string and returns topleft [lat,lon] within mloc

Beyond 8 characters is not defined for Maidenhead.
"""

from .to_location import to_location
from .to_maiden import to_maiden
from .to_rect import to_rect
from geo import sphere


def google_maps(maiden: str) -> str:
    """
    generate Google Maps URL from Maidenhead grid

    Parameters
    ----------

    maiden : str
        Maidenhead grid

    Results
    -------

    url : str
        Google Maps URL
    """

    loc = to_location(maiden)

    url = f"https://www.google.com/maps/@?api=1&map_action=map&center={loc[0]},{loc[1]}"

    return url

def distance_between(this_loc, other_loc):
    mn, ms, mw, me, mlat, mlon = to_rect(this_loc)

    n, s, w, e, lat, lon = to_rect(other_loc)

    bearing = sphere.bearing((mlon, mlat), (lon, lat))
    distance = sphere.distance((mlon, mlat), (lon, lat)) / 1000.0 * 0.9989265959409077

    return bearing, distance