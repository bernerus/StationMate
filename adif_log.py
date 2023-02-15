import tempfile
import psycopg2
import psycopg2.extras
import adif


class StringWrapper:
    def __init__(self):
        self.string = ""

    def write(self, string):
        self.string += string

def produce_adif_log(band_and_mode, logger):

    band = int(band_and_mode.split('-')[0])

    #db = psycopg2.connect(dbname='ham_station', host="pi3.bernerus.se", user="bernerus", password="1b18sUA1zcl/AE?")
    db = psycopg2.connect(dbname='ham_station')
    cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""SELECT callsign as CALL, date as QSO_DATE, time as TIME_ON, band as FREQ, band as BAND, mode as PROP_MODE,
                        tx as RST_SENT, rx as RST_RCVD,
                        locator as GRIDSQUARE,
                        transmit_mode as MODE
                        FROM nac_log_new WHERE complete=True
                        ORDER BY date,time""")


    rows = cur.fetchall()
    qsos = [{k.upper(): v for k, v in record.items()} for record in rows]

    print("Fetched %d qsos" % len(qsos))

    adif_log = adif.ADIF()

    filename = tempfile.NamedTemporaryFile()

    adif_log.write(qsos, filename.name)

    with open(filename.name,"r") as fd:
        lines = fd.read().splitlines()

    for line in lines:
        print(line)






if __name__ == '__main__':
    import logging
    logger = logging.getLogger(__name__)
    logger.setLevel("DEBUG")
    hdlr = logging.StreamHandler()
    hdlr.setFormatter(logging.Formatter('%(asctime)s %(levelname)8s %(filename)20s:%(lineno)-5s %(message)s'))
    logger.addHandler(hdlr)

    logger.info("Starting adif_log")
    produce_adif_log("144", logger)