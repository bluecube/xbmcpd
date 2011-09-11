from __future__ import unicode_literals
from __future__ import division

class JsonException(Exception):
    pass

class UnexpectedChar(JsonException):
    def __init__(self, char, tokenizer):
        self._char = char
        self._line = tokenizer._line
        self._col = tokenizer._col

    def __str__(self):
        return "Unexpected character {} on line {}, column {}.".format(
            repr(self._char), self._line, self._col)

class UnexpectedEof(JsonException):
    pass
    
class Eof:
    pass

eof = Eof()

def exception_factory(char, tokenizer):
    if char == eof:
        return UnexpectedEof()
    else:
        return UnexpectedChar(char, tokenizer)

class JsonParser(object):
    def __init__(self, iterable):
        self._stack = []

        self._iterator = iter(iterable)
        self._next_char = None

        self._line = 1
        self._col = 0

        self._char_handlers = {
            '[': (self._parse_array),
            '{': (self._parse_object), 
            '"': (self._parse_string),
            't': (self._parse_true),
            'f': (self._parse_false),
            'n': (self._parse_null),
            '-': (self._parse_number),
            '0': (self._parse_number),
            '1': (self._parse_number),
            '2': (self._parse_number),
            '3': (self._parse_number),
            '4': (self._parse_number),
            '5': (self._parse_number),
            '6': (self._parse_number),
            '7': (self._parse_number),
            '8': (self._parse_number),
            '9': (self._parse_number),
        }

        self._escape = {
            '"': '"',
            '\\': '\\',
            '/': '/',
            'b': '\b',
            'f': '\f',
            'n': '\n',
            'r': '\r',
            't': '\t',
        }

    def __iter__(self):
        return self

    def next(self):
        self._eat_whitespace()

        c = self._peek()

        if c == eof:
            if not len(self._stack):
                raise StopIteration()
            else:
                raise UnexpectedEof()

        if c not in self._char_handlers:
            raise exception_factory(c, self)

        return self._char_handlers[c]()

    def _parse_array(self):
        self._check_char('[')

        self._eat_whitespace()
        c = self._peek()
        if c == ']':
            self._getc()
            return []

        ret = []
        
        while True:
            self._eat_whitespace()
            ret.append(self.next())

            self._eat_whitespace()
            c = self._peek()
            if c != ',':
                break
            self._check_char(',')

        self._check_char(']')
        return ret

    def _parse_object(self):
        self._check_char('{')

        self._eat_whitespace()
        c = self._peek()
        if c == '}':
            self._getc()
            return {}
            
        ret = {}

        while True:
            self._eat_whitespace()
            key = self._parse_string()

            self._eat_whitespace()
            self._check_char(':')

            self._eat_whitespace()
            ret[key] = self.next()

            self._eat_whitespace()
            c = self._peek()
            if c != ',':
                break
            self._check_char(',')
        
        self._check_char('}')
        return ret
        
    def _parse_true(self):
        self._check_string('true')
        return True

    def _parse_false(self):
        self._check_string('false')
        return False

    def _parse_null(self):
        self._check_string('null')
        return None

    def _parse_string(self):
        chars = []

        self._check_char('"')

        while True:
            c = self._parse_char()
            if c is None:
                break
            chars.append(c)
        
        return ''.join(chars)

    def _parse_char(self):
        c = self._getc()

        if c == '"':
            return None
        # TODO: Disallow unicode control chars
        elif c == '\\':
            c = self._getc()
            if c in self._escape:
                c = self._escape[c]
            elif c == 'u':
                number = 0
                try:
                    for i in range(4):
                        c = self._getc()
                        number *= 16
                        number += int(c, 16)
                except ValueError:
                    raise UnexpectedChar(c, self)
                c = unichr(number)
            else:
                raise UnexpectedChar(c, self)
        elif c == eof:
            raise UnexpectedEof()
        
        return c

    def _parse_number(self):
        number = 0

        negative = (self._peek() == '-')

        if negative:
            self._getc()
        
        c = self._peek()

        if not self._isdigit(c):
            raise exception_factory(c, self)

        if c == '0':
            self._getc()
            number = 0
        else:
            number = self._parse_int()

        if self._peek() == '.':
            self._getc()
            number += self._parse_fractional()

        if negative:
            number = -number
            
        if self._peek() == 'e' or self._peek() == 'E':
            self._getc()

            c = self._peek()

            negative = False
            if c == '+':
                self._getc()
            elif c == '-':
                self._getc()
                negative = True

            c = self._peek()
            if not self._isdigit(c):
                raise exception_factory(c, self)
            
            exponent = self._parse_int()
            if negative:
                exponent = -exponent

            number *= 10 ** exponent

        return number

    def _parse_int(self):
        number = 0

        while True:
            c = self._peek()
            if not self._isdigit(c):
                break;
            
            number *= 10
            number += self._parse_digit()
        
        return number

    def _parse_fractional(self):
        number = 0
        multiplier = 1
        
        c = self._peek()
        if not self._isdigit(c):
            raise exception_factory(c, self)

        while True:
            c = self._peek()

            if not self._isdigit(c):
                break;

            multiplier /= 10
            number += self._parse_digit() * multiplier

        return number

    def _parse_digit(self):
        c = self._getc()
        try:
            return int(c)
        except ValueError:
            raise UnexpectedChar(c, self)

    def _peek(self):
        if self._next_char is None:
            try:
                c = next(self._iterator)
            except StopIteration:
                c = eof
            self._next_char = c

        return self._next_char

    def _getc(self):
        if self._next_char is None:
            try:
                c = next(self._iterator)
            except StopIteration:
                c = eof
        else:
            c = self._next_char
            self._next_char = None

        if c == '\n':
            self._line += 1
            self._col = 0
        else:
            self._col += 1

        #print("{}:{}: {}".format(self._line, self._col, repr(c)))
        return c

    def _check_string(self, expected):
        for c in expected:
            self._check_char(c)

    def _check_char(self, expected):
        c = self._getc()
        if c != expected:
            raise UnexpectedChar(c, self)
            
    def _eat_whitespace(self):
        while self._isspace(self._peek()):
            self._getc()

    def _isdigit(self, c):
        return c != eof and c.isdigit()

    def _isspace(self, c):
        return c != eof and c.isspace()
        
__ALL__ = ['JsonException', 'UnexpectedChar', 'UnexpectedEof', 'JsonParser']
