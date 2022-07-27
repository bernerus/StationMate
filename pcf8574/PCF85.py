INPUT = "INPUT"
OUTPUT = "OUTPUT"
HIGH = "HIGH"
LOW = "LOW"

import time

retry_sleep = 0.2

def setup(PCFAdd, bus, status):
    if status:
            bus.write_byte(PCFAdd, 0xFF)
    elif not status:
            bus.write_byte(PCFAdd, 0x00)


def pin_mode(logger, pin_number: int, mode, flg):
    return set_mode(pin_number, mode, flg)


def set_mode(pin_number: int, mode, flg):
    if INPUT in mode:
        return clear_bit(flg, pin_number)
    elif OUTPUT in mode:
        return set_bit(flg, pin_number)
    else:
        return flg


def bit_read(logger, pin_number, bus, addr):
    errcount = 0
    b = None
    while True:
        try:
            b = bus.read_byte(addr)
            if errcount:
                logger.error("bit_read: retry from %x successful got %s" % (addr, b))
            return test_bit(b, pin_number)
        except OSError as e:
            logger.error("bit_read: OSError from %x pin %d count=%d, retrying, got %x" % (addr, pin_number, errcount, b))
            errcount += 1
            if errcount > 10:
                raise
            time.sleep(retry_sleep)

def byte_read(logger, pin_mask, bus, addr):
    errcount = 0
    b = None
    while True:
        try:
            b = bus.read_byte(addr)
            if errcount:
                logger.error("byte_read: retry from %x successful got %s" % (addr, b))
            return b & pin_mask
        except OSError as e:
            logger.error("byte_read: OSError from %x count=%d, retrying, e=%s, got %s" % (addr, errcount, e, b))
            errcount += 1
            if errcount > 10:
                raise
            time.sleep(retry_sleep)




def byte_write(logger, pin_mask, bus, addr, value):
    errcount = 0
    value_read = None
    while True:
        try:
            value_read = bus.read_byte(addr)
            if errcount:
                logger.error("byte_write: retry read from %x successful got %s" % (addr, value_read))
            break
        except OSError as e:
            logger.error("byte_write: OSError while reading  %x  count=%d, e=%s, got %s, retrying" % (addr, errcount, e, value_read))
            errcount += 1
            if errcount > 10:
                raise
            time.sleep(retry_sleep)
    errcount = 0
    value_write = (value_read & ~pin_mask) | value & pin_mask
    while True:

        try:
            bus.write_byte(addr, value_write)
            check = byte_read(logger, 0xff, bus, addr)
            if check != value_write:
                logger.error("byte_write: reread from %x did not match written value, got %x, expected %x" % (addr, check, value_write))
                raise IOError
            return
        except OSError as e:
            logger.error("byte_write OSError to %x value=%x count=%d, retrying" % (addr, value, errcount))
            errcount += 1
            if errcount > 10:
                raise
            time.sleep(retry_sleep)

def test_bit(n, offset):
    mask = 1 << offset
    return n & mask


def set_bit(n, offset):
    mask = 1 << offset
    return n | mask


def clear_bit(n, offset):
    mask = ~(1 << offset)
    return n & mask


def bit_write(logger, pin_number: int, val, addr, flg, bus):
    if test_bit(flg, pin_number):
        if HIGH in val:
            write_data(logger, pin_number, 1, bus, flg, addr)
        elif LOW in val:
            write_data(logger, pin_number, 0, bus, flg, addr)
    else:
        logger.error("You can not write to an Input Pin")


def write_data(logger, pin_number: int, val, bus, flg, addr):
    if test_bit(flg, pin_number):
        errcount = 0
        value_read = None
        while True:
            try:
                value_read = bus.read_byte(addr)
                if errcount:
                    logger.error("write_data: retry read from %x successful got %s" % (addr, value_read))
                break
            except OSError as e:
                logger.error("write_data: OSError while reading  %x  count=%d, e=%s, got %s, retrying" % (addr, errcount, e, value_read))
                errcount += 1
                if errcount > 10:
                    raise
                time.sleep(retry_sleep)
        errcount = 0
        while True:
            try:
                if val == 0 and test_bit(value_read, pin_number):
                    # logger.debug(f"I2C write_data %x %s"% (addr, format(clear_bit(value_read, pin_number),'b')))
                    bus.write_byte(addr, clear_bit(value_read, pin_number))
                    check = byte_read(logger, 0xff, bus, addr)
                    if check != clear_bit(value_read, pin_number):
                        logger.error("write_data: reread from %x did not match written value, got %s, expected %x" % (addr, check, clear_bit(value_read, pin_number)))
                        raise IOError
                    if errcount:
                        logger.info("write_data succeeded on retry number %d" % errcount)
                    return
                elif val == 1 and not test_bit(value_read, pin_number):
                    # logger.debug("I2C write_data %x %s"% (addr, format(set_bit(value_read, pin_number),'b')))
                    bus.write_byte(addr, set_bit(value_read, pin_number))
                    check = byte_read(logger, 0xff, bus, addr)
                    if check != set_bit(value_read, pin_number):
                        logger.error("byte_write: reread from %x did not match written value, got %s, expected %x" % (addr, check, set_bit(value_read, pin_number)))
                        raise IOError
                    if errcount:
                        logger.info("write_data succeeded on retry number %d" % errcount)
                    return
                else:

                    return

            except OSError as e:
                logger.error("write_data OSError to %x value=%x count=%d, e=%s, retrying" % (addr, val, errcount, e))
                errcount += 1
                if errcount > 10:
                    raise
                time.sleep(retry_sleep)
