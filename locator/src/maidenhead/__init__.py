

from .to_location import to_location
from .to_maiden import to_maiden
from .to_rect import to_rect
from geo import sphere
"""
    The Maidenhead locator is a system used to divide the world into grid squares for amateur radio communication. The locator string consists of 2 to 12 characters, with an even number
    * of characters. Each pair of characters represents a different level of granularity in the grid. The first pair represents a large area, the second pair a medium area, and so on.

    The latitude is represented by the number of degrees north from the South Pole, and the longitude is represented by the number of degrees east from the Prime Meridian. The coordinates
    * are returned as a tuple in the format (latitude, longitude).
"""

def google_maps(locator: str) -> str:
    """

    :param locator: A string representing the location or address for which the Google Maps URL needs to be generated.
    :return: A formatted URL string for Google Maps with the specified location or address.

    """
    loc = to_location(locator)

    url = f"https://www.google.com/maps/@?api=1&map_action=map&center={loc[0]},{loc[1]}"

    return url

def distance_between(this_loc, other_loc):
    """
    Calculate the bearing and distance between two locations.

    :param this_loc: A tuple or list containing the latitude and longitude of the current location.
    :param other_loc: A tuple or list containing the latitude and longitude of the other location.
    :return: A tuple containing the bearing and distance between the two locations.

    """
    mn, ms, mw, me, mlat, mlon = to_rect(this_loc)

    n, s, w, e, lat, lon = to_rect(other_loc)

    bearing = sphere.bearing((mlon, mlat), (lon, lat))
    distance = sphere.distance((mlon, mlat), (lon, lat)) / 1000.0 * 0.9989265959409077

    return bearing, distance