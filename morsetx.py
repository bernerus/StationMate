import time
import smbus2
import queue
from threading import Lock
from p20_defs import *

imc = {
    'A': '.-',
    'B': '-...',
    'C': '-.-.',
    'D': '-..',
    'E': '.',
    'F': '..-.',
    'G': '--.',
    'H': '....',
    'I': '..',
    'J': '.---',
    'K': '-.-',
    'L': '.-..',
    'M': '--',
    'N': '-.',
    'O': '---',
    'P': '.--.',
    'Q': '--.-',
    'R': '.-.',
    'S': '...',
    'T': '-',
    'U': '..-',
    'V': '...-',
    'W': '.--',
    'X': '-..-',
    'Y': '-.--',
    'Z': '--..',
    'Å': '.--.-',
    'Ä': '.-.-',
    'Ö': '---.',

    '1': '.----',
    '2': '..---',
    '3': '...--',
    '4': '....-',
    '5': '.....',
    '6': '-....',
    '7': '--...',
    '8': '---..',
    '9': '----.',
    '0': '-----',

    '.': '.-.-.-',
    ',': '--..--',
    '?': '..--..',
    '\'': '.----.',
    '!': '-.-.--',
    '/': '-..-.',
    '(': '-.--.',
    ')': '-.--.-',
    '&': '.-...',
    ':': '---...',
    ';': '-.-.-.',
    '=': '-...-',
    '+': '.-.-.',
    '-': '-....-',
    '_': '..--.-',
    '"': '.-..-.',
    '$': '...-..-',
    '@': '.--.-.',
    '§': '_...-.-',
    '#': '...-.-',
}

cw_thread = None
cw_thread_lock = Lock()


class Morser:

    def __init__(self, verbose=True, gpio_bus=1, speed=None, p20=None):
        self.unit_time = None
        self.set_speed(speed)
        self.verbose = verbose
        self.bus = smbus2.SMBus(gpio_bus)
        self.p20 = p20
        self.txq = queue.Queue()

    def set_speed(self, speed):
        if speed is None:
            speed = 100
        self.unit_time = 6 / speed
        print("CW speed set to ", speed)

    def transmit_sentence(self, sentence):
        for (index, word) in enumerate(sentence.split()):
            if index > 0:
                self.wait_between_words()
            self.transmit_word(word)

    def transmit_word(self, word):
        for (index, letter) in enumerate(word):
            if index > 0:
                self.wait_between_letters()
            self.transmit_letter(letter)

    def transmit_letter(self, letter):
        code = imc.get(letter.upper(), '')

        if code != '':

            if self.verbose:
                print('\nProcessing letter "{}" and code "{}"'.format(letter.upper(), code))

            for (index, signal) in enumerate(code):
                if index > 0:
                    self.wait_between_signals()

                if signal == '.':
                    self.transmit_dot()
                else:
                    self.transmit_dash()

        else:
            if self.verbose:
                print('\nInvalid input: {}'.format(letter))

    def transmit_dot(self):
        self.p20.bit_write(P20_CW_KEY, "LOW")
        time.sleep(self.unit_time)

    def transmit_dash(self):
        self.p20.bit_write(P20_CW_KEY, "LOW")
        time.sleep(self.unit_time * 3)

    def wait_between_signals(self):
        self.p20.bit_write(P20_CW_KEY, "HIGH")
        time.sleep(self.unit_time)

    def wait_between_letters(self):
        self.p20.bit_write(P20_CW_KEY, "HIGH")
        time.sleep(self.unit_time * 3)

    def wait_between_words(self):
        self.p20.bit_write(P20_CW_KEY, "HIGH")
        time.sleep(self.unit_time * 7)

    def send_message(self, message, repeat=1):
            count = repeat
            try:
                while count:
                    if message != '':
                        if self.verbose:
                            print('\nBegin Transmission')

                        self.transmit_sentence(message)
                        self.p20.bit_write(P20_CW_KEY, "HIGH")
                    count -= 1
                    if count == 0:
                        break
                    self.wait_between_words()

                if self.verbose:
                    print('\nEnd Transmission')

            finally:
                self.p20.bit_write(P20_CW_KEY, "HIGH")

    def background_thread(self):
        """Example of how to send server generated CW."""
        while True:
            if not self.txq.empty():
                item = self.txq.get_nowait()
                print("Transmitting CW: %s" % item)
                self.send_message(item)
            else:
                time.sleep(self.unit_time)