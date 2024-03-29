from datetime import timedelta, date, datetime
import psycopg2
import psycopg2.extras
import pytz
import locator.src.maidenhead as mh
import math
from geo import sphere

def get_nth_tuesday(n, today=date.today()):

    d = today.replace(day=1)
    offset = 1 - d.weekday()
    if offset < 0:
        offset += 7
    offset += 7 * n

    return d + timedelta(offset)

def get_nth_thursday(n, today=date.today()):

    d = today.replace(day=3)
    offset = 3 - d.weekday()
    if offset < 0:
        offset += 7
    offset += 7 * n

    return d + timedelta(offset)


def is_dst(dt=None, timezone="UTC"):
    if dt is None:
        dt = datetime.utcnow()
    if type(dt) is date:
        dt = datetime(dt.year, dt.month, dt.day, 18, 0, 0)
    timezone = pytz.timezone(timezone)
    timezone_aware_date = timezone.localize(dt, is_dst=None)
    return timezone_aware_date.tzinfo._dst.seconds != 0


def get_test_data(tuesday_number, today, thursday_number = None):

    if thursday_number is not None:
        test_date = get_nth_thursday(thursday_number, today)
    else:
        test_date = get_nth_tuesday(tuesday_number, today)
    dst = is_dst(test_date, timezone="CET")
    utcstart = "18:00:00" if not dst else "17:00:00"
    utcend = "22:00:00" if not dst else "21:00:00"

    t_date_start = test_date.isoformat()[:10] + " " + utcstart
    t_date_stop = test_date.isoformat()[:10] + " " + utcend

    return test_date, t_date_start, t_date_stop

def get_contest_times(band_and_mode, tuesday_number=None, today=datetime.now()):

    t_date_start, t_date_stop, test_date = None, None, None
    if tuesday_number is None:
        try:
            tuesday_number = band_on_tuesday_number[band_and_mode]
            test_date, t_date_start, t_date_stop = get_test_data(tuesday_number, today)
        except KeyError:
            thursday_number = band_on_thursday_number[band_and_mode]
            test_date, t_date_start, t_date_stop = get_test_data(thursday_number, today, thursday_number=thursday_number)

    today_str = today.strftime("%Y-%m-%d %H:%M:%S")
    if t_date_start > today_str:
        first = today.replace(day=1)
        last_month_end = first - timedelta(days=1)
        test_date, t_date_start, t_date_stop = get_test_data(tuesday_number, last_month_end)
    return test_date, t_date_start, t_date_stop

band_on_tuesday_number = {
        "144": 0,
        "144-FT8": 0,
        "144-MSK": 0,
        "432": 1,
        "432-FT8": 1,
        "1296": 2,
        "1296-FT8": 2,
    }

band_on_thursday_number = {
        "50": 1,
        "50-FT8": 1,
        "28": 0,
        "28-FT8": 0
    }



class StringWrapper:
    def __init__(self):
        self.string = ""

    def write(self, string):
        self.string += string

def produce_contest_log(band_and_mode, logger, tuesday_number=None, log_remarks=None):

    contest_log = StringWrapper()  # Type: Optional[SupportsWrite[str]]

    logger.info("Producing contest log for band and mode %s, tuesday number=%s, remarks=%s" % (band_and_mode, tuesday_number, log_remarks ))

    test_date, t_date_start, t_date_stop = get_contest_times(band_and_mode, tuesday_number)

    logger.info("Test date = %s, start time %s, end time %s" % (test_date, t_date_start, t_date_stop))

    band = int(band_and_mode.split('-')[0])

    db = psycopg2.connect(dbname='ham_station')
    # TODO: Get this table from internet.
    prefixes = {
        "LA": "NO",
        "LB": "NO",
        "LC": "NO",
        "LD": "NO",
        "LE": "NO",
        "LF": "NO",
        "LG": "NO",
        "LH": "NO",
        "LI": "NO",
        "LJ": "NO",
        "LK": "NO",
        "LL": "NO",
        "LM": "NO",
        "LN": "NO",
        "LY": "LT",
        "3Y": "3Y",
        "JW": "JW",
        "JX": "JX",
        "SA": "SE",
        "SB": "SE",
        "SC": "SE",
        "SD": "SE",
        "SE": "SE",
        "SF": "SE",
        "SG": "SE",
        "SH": "SE",
        "SI": "SE",
        "SJ": "SE",
        "SK": "SE",
        "SL": "SE",
        "SM": "SE",
        "8S": "SE",
        "7S": "SE",
        "OU": "OZ",
        "OW": "OZ",
        "XP": "OZ",
        "OZ": "OZ",
        "OV": "OZ",
        "OY": "OY",
        "OX": "OX",
        "DA": "DE",
        "DB": "DE",
        "DC": "DE",
        "DD": "DE",
        "DE": "DE",
        "DF": "DE",
        "DG": "DE",
        "DH": "DE",
        "DI": "DE",
        "DJ": "DE",
        "DK": "DE",
        "DL": "DE",
        "DM": "DE",
        "DN": "DE",
        "DO": "DE",
        "DP": "DE",
        "DQ": "DE",
        "DR": "DE",
        "OH": "OH",
        "OH0": "OH0",
        "OJ0": "OJ0",
        "YL": "YL",
        "ES": "ES",
        "PA":"PA",
        "PB":"PA",
        "PC":"PA",
        "PD":"PA",
        "PE":"PA",
        "PF":"PA",
        "PG":"PA",
        "PH":"PA",
        "PI":"PA",
        "PJ":"PA",
        "SP":"SP",
        "SO":"SP",
        "SN":"SP",
        "SQ":"SP",
        "SR":"SP",
        "HF":"SP",
        "3Z":"SP",
        "Y2": "DL",
        "Y3": "DL",
        "Y4": "DL",
        "Y5": "DL",
        "Y6": "DL",
        "Y7": "DL",
        "Y8": "DL",
        "Y9": "DL",
        "5P": "DK",
        "5Q": "DK",
    }

    contest_log_header = {
        "TName": "NAC %s" % band,  # Contest name
        "TDate": None,  # Beginning;Ending date of contest
        "PCall": None,  # Beginning;Ending date of contest
        "PWWLo": None,  # WWL used
        "PExch": None,  # Exchanged info used
        "PAdr1": None,  # Address used line 1
        "PAdr2": None,  # Address used line 2
        "PSect": None,  # Contest section/class/category/group
        "PBand": "%d MHz" % band,  # Frequency band
        "PClub": None,  # Associated club call
        "RName": None,  # Name of responsible operator
        "RCall": None,  # Callsign of responsible op
        "RAdr1": None,  # Address of responsible op line 1
        "RAdr2": None,  # Address of responsible op line 2
        "RPoCo": None,  # Postal code of responsible op
        "RCity": None,  # City of responsible op
        "RCoun": None,  # Country of responsible op
        "RPhon": None,  # Phone no of responsible op
        "RHBBS": None,  # BBS or email of responsible op
        "MOpe1": None,  # Operators line 1
        "MOpe2": None,  # Operators line 2
        "STXEq": None,  # Transmitting equipment
        "SPowe": None,  # Transmitting power
        "SRXEq": None,  # Receiving equipment
        "SAnte": None,  # Antenna system description
        "SAntH": None,  # Antenna AGl;ASl
        "CQSOs": None,  # # of valid QSOS;Band mutiplier
        "CWWLs": None,  # Claimed # of WWLs wkd;Bonus per WWL;WWL multiplier
        "CWWLB": None,  # Claimed WWL bonus points
        "CExcs": None,  # Claimed exchanges; Bonus per exchange; Multiplier per exchange
        "CExcB": None,  # Claimed exchange bonus points
        "CDXCs": None,  # Claimed DXCCs; bonus points per DXCC; DCXX multiplier
        "CDXCB": None,  # Claimed DXCC bonus points
        "CToSc": None,  # Claimed total score
        "CODXC": None,  # Claimed ODX call; WWL; distance
    }

    nac_initials = {
        "TName": "NAC %d" % band,
        "PBand": "%d MHz" % band,
        "CWWLs": ";500;1",
        "CExcs": ";0;1",
        "CDXCs": ";0;1",
        "CQSOs": ";1"
    }

    log = contest_log_header.copy()
    for k, v in nac_initials.items():
        log[k] = v

    cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    ts = t_date_start[:10]

    log["TDate"] = t_date_start[:10].replace("-", "")

    cur.execute(
        "SELECT * FROM config_str WHERE (time_start IS NULL OR time_start <= %s ) AND (time_stop IS NULL OR time_stop >= %s) AND (band IS NULL OR band = %s) ORDER BY key",
        (ts, ts, band_and_mode)
    )
    rows = cur.fetchall()

    myloc = None
    for row in rows:
        k = row["key"]
        v = row["value"]
        if k == "my_callsign":
            log["PCall"] = log["RCall"] = v
        elif k == "my_locator":
            log["PWWLo"] = v[:6]
            myloc = v[:6]
        elif k == "my_address":
            log["RAdr1"] = log["PAdr1"] = v
        elif k == "my_club":
            log["PClub"] = v
        elif k == "my_name":
            log["RName"] = v
        elif k == "my_postcode":
            log["RPoCo"] = v
        elif k == "my_city":
            log["RCity"] = v
        elif k == "my_country":
            log["RCoun"] = v
        elif k == "my_phone":
            log["RPhon"] = v
        elif k == "my_email":
            log["RHBBS"] = v
        elif k == "my_tx":
            log["STXEq"] = v
        elif k == "my_pwr":
            log["SPowe"] = v
        elif k == "my_rx":
            log["SRXEq"] = v
        elif k == "my_ant":
            log["SAnte"] = v
        elif k == "my_ant_agl":
            log["SAntH"] = str(v)
        elif k == "my_ant_asl":
            log["SAntH"] += ";" + str(v)
        else:
            pass

    pass

    args = (
        t_date_start[:10], t_date_stop[:10], t_date_start[11:16].replace(":", ""), t_date_stop[11:16].replace(":", ""))
    cur.execute(
        "SELECT DISTINCT(callsign) as dcs FROM nac_log_new WHERE date >= %s and date <= %s and time >= %s and time <= %s",
        args)
    rows = cur.fetchall()
    qso_records = len(rows)
    if qso_records == 0:
        return
    band_multiplier = int(log["CQSOs"].split(";")[1])
    log["CQSOs"] = str(len(rows)) + ";" + str(band_multiplier)

    print("[REG1TEST,1]", file=contest_log)

    wwls, wwl_bonus, wwl_multiplier = log["CWWLs"].split(";")

    cur.execute(
        "SELECT DISTINCT callsign, date, time  FROM nac_log_new WHERE date >= %s and date <= %s and time >= %s and time <= %s and complete ORDER BY date, time",
        args)

    wkd_countries = set()

    for row in cur.fetchall():
        dx_call = row["callsign"].upper()

        for pfx in prefixes:
            if dx_call.startswith(pfx):
                country = prefixes[pfx]
                if country not in wkd_countries:
                    wkd_countries.add(country)
                break
        else:
            raise LookupError("Unknown prefix for callsign %s" % dx_call)

    dxccs, dxcc_bonus, dxcc_multiplier = log["CDXCs"].split(";")

    log["CDXCs"] = "%s;%s;%s" % (len(wkd_countries), dxcc_bonus, dxcc_multiplier)

    cur.execute(
        """ SELECT callsign, locator, distance FROM nac_log_new WHERE date >= %s and date <= %s and time >= %s and time <= %s and complete ORDER BY distance DESC""",
        args)
    odxrow = cur.fetchall()[0]

    mn, ms, mw, me, mlat, mlon = mh.to_rect(myloc[:6])
    n, s, w, e, lat, lon = mh.to_rect(odxrow["locator"][:6])

    distance = sphere.distance((mlon, mlat), (
        lon, lat)) / 1000.0 * 1  # 0.9989265959409077  # Macic  constant compensates for the IARU geoid.

    log["CODXC"] = "%s;%s;%s" % (
        odxrow["callsign"].upper(), odxrow["locator"][:6].upper(), str(int(distance * 100) / 100.0))

    qsorecs = []

    wkd_countries = set()
    wkd_calls = set()
    wkd_wwls = set()

    cur.execute(
        "SELECT * FROM nac_log_new WHERE date >= %s and date <= %s and time >= %s and time <= %s ORDER BY date, time",
        args)
    rows = cur.fetchall()
    total_qso_points = 0

    for row in rows:
        qso_date = row["date"][2:].replace("-", "")
        qso_time = row["time"]
        dx_call = row["callsign"].upper()

        mode_codes = {

            ("CW", 3): 2,  # Two way CW
            ("CW", 2): 4,  # Tx cw, rx SSB
            ("SSB", 2): 1,  # Two way SSB
            ("FT8", 2): 7,  # MGM
            ("MS144", 2): 7,  # MGM
        }

        mode_code = "0"  # Don't know
        if (row["txmode"], len(row["rx"])) in mode_codes:
            mode_code = mode_codes[(row["txmode"], len(row["rx"]))]

        tx = row["tx"].upper()
        tx_qson = ""
        rx = row["rx"].upper()
        rx_qson = ""
        rx_exch = ""
        rx_wwl = row["locator"][:6].upper()
        new_dxcc = ""
        new_exchange = ""

        mn, ms, mw, me, mlat, mlon = mh.to_rect(myloc[:6])
        n, s, w, e, lat, lon = mh.to_rect(rx_wwl[:6])

        distance = sphere.distance((mlon, mlat), (
            lon, lat)) / 1000.0 * 1  # 0.9989265959409077  # Magic  constant compensates for the IARU geoid.
        # print(rx_wwl, distance, file=contest_log)
        points = math.floor(distance) + 1

        dup_qso = ""
        new_wwl = ""
        qso_points = 0

        if row["complete"]:
            if dx_call in wkd_calls:
                dup_qso = "D"
                qso_points = 0
            else:
                if rx_wwl[:4] not in wkd_wwls:
                    new_wwl = "N"
                qso_points = points * band_multiplier
                total_qso_points += qso_points
                wkd_wwls.add(rx_wwl[:4])

                for pfx in prefixes:
                    if dx_call.startswith(pfx):
                        country = prefixes[pfx]
                        if country not in wkd_countries:
                            new_dxcc = "N"
                            wkd_countries.add(country)
                        break
                else:
                    raise LookupError("Unknown prefix for callsign %s" % dx_call)
        else:
            dx_call = "ERROR " + dx_call

        wkd_calls.add(dx_call)

        qsorecs.append("%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%d;%s;%s;%s;%s" %
                       (qso_date, qso_time, dx_call, mode_code,
                        tx, tx_qson, rx, rx_qson, rx_exch, rx_wwl,
                        qso_points, new_exchange, new_wwl, new_dxcc, dup_qso))

    log["CQSOP"] = total_qso_points + len(wkd_countries) * int(dxcc_bonus) * int(dxcc_multiplier)
    log["CToSc"] = total_qso_points + len(wkd_countries) * int(dxcc_bonus) * int(dxcc_multiplier) + int(
        wwl_bonus) * len(wkd_wwls)
    log["CWWLs"] = "%d;%s;%s" % (len(wkd_wwls), wwl_bonus, wwl_multiplier)
    log["CWWLB"] = len(wkd_wwls) * int(wwl_bonus) * int(wwl_multiplier)

    for key, value in log.items():
        print("%s=%s" % (key, value), file=contest_log)

    if log_remarks:
        print("[REMARKS]", file=contest_log)
        print(log_remarks, file=contest_log)
    print("[QSORecords;%d]" % len(qsorecs), file=contest_log)
    for qsorec in qsorecs:
        print(qsorec, file=contest_log)

    print("Contest log.")
    print(contest_log.string)
    return contest_log.string

if __name__ == '__main__':
    dates = ["2022-01-01 20:00",
             "2022-01-04 17:59",
             "2022-01-04 18:00"]

    for d in dates:
        pd = datetime.strptime(d, "%Y-%m-%d %H:%M")
        test_date, t_date_start, t_date_stop = get_contest_times("144-FT8", None, pd)
        print(test_date, t_date_start, t_date_stop)