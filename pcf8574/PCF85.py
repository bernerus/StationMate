INPUT = "INPUT"
OUTPUT = "OUTPUT"
HIGH = "HIGH"
LOW = "LOW"

import time


def setup(PCFAdd, bus, status):
    if status:
            bus.write_byte(PCFAdd, 0xFF)
    elif not status:
            bus.write_byte(PCFAdd, 0x00)


def pin_mode(pin_number: int, mode, flg):
    return set_mode(pin_number, mode, flg)


def set_mode(pin_number: int, mode, flg):
    if INPUT in mode:
        return clear_bit(flg, pin_number)
    elif OUTPUT in mode:
        return set_bit(flg, pin_number)
    else:
        return flg


def bit_read(pin_number, bus, addr):
    errcount = 0
    while True:
        try:
            b = bus.read_byte(addr)
            return test_bit(b, pin_number)
        except OSError:
            # print("bit_read OSError from %x pin %d count=%d, retrying" % (addr, pin_number, errcount))
            errcount += 1
            if errcount > 10:
                raise
            time.sleep(0.1)

def byte_read(pin_mask, bus, addr):
    errcount = 0
    while True:
        try:
            b = bus.read_byte(addr)
            return b & pin_mask
        except OSError:
            # print("byte_read OSError from %x count=%d, retrying" % (addr,errcount))
            errcount += 1
            if errcount > 10:
                raise
            time.sleep(0.1)




def byte_write(pin_mask, bus, addr, value):
    errcount = 0
    while True:
        try:
            bus.write_byte(addr, value & pin_mask)
            return
        except OSError:
            # print("byte_write OSError to %x value=%x count=%d, retrying" % (addr, value, errcount))
            errcount += 1
            if errcount > 10:
                raise
            time.sleep(0.1)

def test_bit(n, offset):
    mask = 1 << offset
    return n & mask


def set_bit(n, offset):
    mask = 1 << offset
    return n | mask


def clear_bit(n, offset):
    mask = ~(1 << offset)
    return n & mask


def bit_write(pin_number: int, val, addr, flg, bus):
    if test_bit(flg, pin_number):
        if HIGH in val:
            write_data(pin_number, 1, bus, flg, addr)
        elif LOW in val:
            write_data(pin_number, 0, bus, flg, addr)
    else:
        print("You can not write to an Input Pin")


def write_data(pin_number: int, val, bus, flg, addr):
    if test_bit(flg, pin_number):
        errcount = 0
        while True:
            try:
                value_read = bus.read_byte(addr)
                break
            except OSError:
                print("write_data OSError while reading  %x  count=%d, retrying" % (addr, errcount))
                errcount += 1
                if errcount > 10:
                    raise
                time.sleep(0.1)
        errcount = 0
        while True:
            try:
                if val == 0 and test_bit(value_read, pin_number):
                    # print(f"I2C write_data %x %s"% (addr, format(clear_bit(value_read, pin_number),'b')))
                    bus.write_byte(addr, clear_bit(value_read, pin_number))
                    return
                elif val == 1 and not test_bit(value_read, pin_number):
                    # print("I2C write_data %x %s"% (addr, format(set_bit(value_read, pin_number),'b')))
                    bus.write_byte(addr, set_bit(value_read, pin_number))
                    return
                else:
                    return
            except OSError:
                print("write_data OSError to %x value=%x count=%d, retrying" % (addr, val, errcount))
                errcount += 1
                if errcount > 10:
                    raise
                time.sleep(0.1)
