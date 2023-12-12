from datetime import datetime, timedelta
from typing import Tuple, Union

def str_to_datetime(date_str: str, time_str: str) -> datetime:
    """
     :param date_str: The date string in the format 'YYYY-MM-DD'
     :param time_str: The time string in the format 'HHMM'
     :return: A datetime object representing the combined date and time
     """
    dt_str = date_str + " " + time_str
    try:
        dt_obj = datetime.strptime(dt_str, '%Y-%m-%d %H%M')
    except ValueError:
        raise ValueError("Incorrect date or time format, should be 'YYYY-MM-DD' for date and 'HHMM' for time")
    return dt_obj

def datetime_to_str(dt_obj: datetime) -> Tuple[str, str]:
    """
    :param dt_obj: the datetime object that needs to be converted to a string.
    :return: a tuple containing the date string and the time string in the format (date_str, time_str).
    """
    if not isinstance(dt_obj, datetime):
        raise ValueError("dt_obj must be a datetime object")

    date_str = dt_obj.strftime('%Y-%m-%d')
    time_str = dt_obj.strftime('%H%M')
    return date_str, time_str

def get_timespan(dt_obj: datetime, minutes: int) -> Tuple[datetime, datetime]:
    """
    Get a timespan by subtracting and adding minutes to the given datetime object.

    :param dt_obj: The datetime object to calculate the timespan for.
    :type dt_obj: datetime.datetime
    :param minutes: The number of minutes to subtract and add to the datetime object.
    :type minutes: int
    :return: A tuple containing the earlier datetime object obtained by subtracting minutes and the later datetime object obtained by adding minutes.
    :rtype: tuple
    """

    if not isinstance(dt_obj, datetime):
        raise ValueError("dt_obj must be a datetime object")
    if not isinstance(minutes, int) or minutes < 0:
        raise ValueError("minutes must be a non-negative integer")

    earlier_dt_obj = dt_obj - timedelta(minutes=minutes)
    later_dt_obj = dt_obj + timedelta(minutes=minutes)
    return earlier_dt_obj, later_dt_obj