from pcf8574 import PCF85
from typing import *
import time
from smbus2 import SMBus

LOW = "LOW"
HIGH = "HIGH"
INPUT = "INPUT"
OUTPUT = "OUTPUT"

default_pin_names = {"p0": 0,
                     "p1": 1,
                     "p2": 2,
                     "p3": 3,
                     "p4": 4,
                     "p5": 5,
                     "p6": 6,
                     "p7": 7,
                     }


class PCF:

    def __init__(self, logger, address, pin_names: Dict[str, Union[int , Tuple[int, str]]] = None):
        """
        Initializes a PCF8574 I2C extension IC.

        :param logger: The logger object for logging.
        :param address: The I2C address of the device.
        :param pin_names: A dictionary containing the pin names.
                          The dictionary should have pin names as keys and corresponding pin modes as values.
                          The pin mode can be an integer or a tuple containing an integer and a string
                          representing the pin mode and its name.
                          If not provided, default_pin_names will be used.
        """
        self.logger = logger
        self.address = address
        self.status = True
        self.pin_mode_flags = 0x00
        self.sm_bus_number = 1
        self.pin_names = pin_names

        if pin_names is None:
            self.pin_names = default_pin_names
        else:
            self.pin_names = {}
            for k, v in pin_names.items():
                if type(v) is tuple:
                    self.pin_names[k] = v[0]
                    if v[1] in [INPUT, OUTPUT]:
                        self.pin_mode(k, v[1])
                else:
                    self.pin_names[k] = v
        self.bus = SMBus(self.sm_bus_number)
        time.sleep(1)
        PCF85.setup(address, self.bus, self.status)

    def pin_mode(self, pin_name, mode):
        self.pin_mode_flags = PCF85.pin_mode(self.logger, self.pin_names[pin_name], mode, self.pin_mode_flags)

    def bit_read(self, pin_name):
        """
        Read the value of a specific bit from a given pin.

        :param pin_name: The name of the pin. (str)
        :return: The value of the bit read from the pin. (int)
        """
        return PCF85.bit_read(self.logger, self.pin_names[pin_name], self.bus, self.address)

    def byte_read(self, pin_mask):
        """
        Reads a byte from the PCF8574 device using the provided pin mask.

        :param pin_mask: The pin mask to use for reading the byte.
        :return: The byte read from the PCF85 device.
        """
        return PCF85.byte_read(self.logger, pin_mask, self.bus, self.address)

    def byte_write(self, pin_mask, value):
        """
        Write a byte to PCF8574 using the specified pin mask, and value.

        :param pin_mask: The pin mask indicating which pins to write to.
        :type pin_mask: int
        :param value: The value to write to the specified pins.
        :return: The result of the byte write operation.
        """
        return PCF85.byte_write(self.logger, pin_mask, self.bus, self.address, value & 0xff)

    def bit_write(self, pin_name, value):
        """
        :param pin_name: The name of the pin to write the value to. (str)
        :param value: The value to be written to the pin. (bool)
        :return: None

        This method writes the specified value to the pin with the given name.
        It internally calls the `bit_write` method of a `PCF85` object with the provided parameters: logger, pin name,
        * value, address, pin mode flags, and bus.
        """
        PCF85.bit_write(self.logger, self.pin_names[pin_name], value, self.address, self.pin_mode_flags, self.bus)