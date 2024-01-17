class Degree(int):
    """
    The Degree class is a subclass of int that represents an angle in degrees. It ensures that the angle value is between 0 and 359.

    Attributes:
        No additional attributes.

    Methods:
        - __new__(cls, value): Returns a new instance of the Degree class with the specified value.
        - __add__(self, other): Overrides the addition operator to perform addition with an integer or another Degree object.
        - __sub__(self, other): Overrides the subtraction operator to perform subtraction with an integer or another Degree object.
        - __mul__(self, other): Overrides the multiplication operator to perform multiplication with an integer or another Degree object.
        - __truediv__(self, other): Overrides the division operator to perform division with an integer or another Degree object.

    Example Usage:

        # create a Degree object with a value of 45
        degree = Degree(45)

        # perform addition with an integer
        result = degree + 10
        print(result)  # Output: 55

        # perform subtraction with another Degree object
        result = degree - Degree(20)
        print(result)  # Output: 25

        # perform multiplication with an integer
        result = degree * 2
        print(result)  # Output: 90

        # perform division with an integer
        result = degree / 3
        print(result)  # Output: 15

        # ensure that the angle value is always between 0 and 359
        result = degree + 400
        print(result)  # Output: 85

        result = degree - 100
        print(result)  # Output: 305
    """
    def __new__(cls, value):
        if value is None:
            return None
        value %= 360
        if not 0 <= value <= 359:
            raise ValueError("Value must be between 0 and 359")
        return int.__new__(cls, value)

    def __add__(self, other):
        if self is None or other is None:
            return None
        elif isinstance(other, int):
            return Degree((int(self) + other) % 360)
        return NotImplemented

    def __sub__(self, other):
        if self is None or other is None:
            return None
        elif isinstance(other, int):
            return Degree((int(self) - other) % 360)
        return NotImplemented

    def __mul__(self, other):
        if self is None or other is None:
            return None
        elif isinstance(other, int):
            return Degree((int(self) * other) % 360)
        return NotImplemented

    def __truediv__(self, other):
        if self is None or other is None:
            return None
        elif isinstance(other, int):
            return Degree((int(self) // other) % 360)
        return NotImplemented