"""Minimal `java.time` facade used by newer exteraGram plugins.

The classes wrap `datetime`/`time` and keep Java's method names.  Only the
value types plugins commonly touch are provided; formatting accepts the same
`yyyy-MM-dd HH:mm:ss` tokens as `SimpleDateFormat`.
"""

import datetime
import time


class Instant:
    def __init__(self, millis=0):
        self._millis = int(millis or 0)

    @classmethod
    def now(cls):
        return cls(int(time.time() * 1000))

    @classmethod
    def ofEpochMilli(cls, value):
        return cls(int(value or 0))

    @classmethod
    def ofEpochSecond(cls, value):
        return cls(int(value or 0) * 1000)

    def toEpochMilli(self):
        return self._millis

    def getEpochSecond(self):
        return self._millis // 1000

    def plusMillis(self, value):
        return Instant(self._millis + int(value or 0))

    def minusMillis(self, value):
        return Instant(self._millis - int(value or 0))

    def plusSeconds(self, value):
        return Instant(self._millis + int(value or 0) * 1000)

    def toPyDateTime(self):
        return datetime.datetime.fromtimestamp(self._millis / 1000.0)

    def toString(self):
        moment = datetime.datetime.utcfromtimestamp(self._millis / 1000.0)
        return moment.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (self._millis % 1000)) + "Z"

    def __str__(self):
        return self.toString()


class Duration:
    def __init__(self, seconds=0, nanos=0):
        self._seconds = int(seconds or 0)
        self._nanos = int(nanos or 0)

    @classmethod
    def ofSeconds(cls, seconds, nano=0):
        return cls(seconds, nano)

    @classmethod
    def ofMillis(cls, millis):
        value = int(millis or 0)
        return cls(value // 1000, (value % 1000) * 1000000)

    def getSeconds(self):
        return self._seconds

    def getNano(self):
        return self._nanos

    def toMillis(self):
        return self._seconds * 1000 + self._nanos // 1000000

    def plusSeconds(self, value):
        return Duration(self._seconds + int(value or 0), self._nanos)

    def plusMillis(self, value):
        return Duration.ofMillis(self.toMillis() + int(value or 0))

    def minusSeconds(self, value):
        return Duration(self._seconds - int(value or 0), self._nanos)

    def toString(self):
        return "PT%SS" % self._seconds


class LocalDate:
    def __init__(self, value=None):
        self._date = value or datetime.date.today()

    @classmethod
    def now(cls):
        return cls(datetime.date.today())

    @classmethod
    def of(cls, year, month, day):
        return cls(datetime.date(int(year), int(month), int(day)))

    @classmethod
    def parse(cls, text):
        return cls(datetime.date.fromisoformat(str(text)))

    def getYear(self):
        return self._date.year

    def getMonthValue(self):
        return self._date.month

    def getDayOfMonth(self):
        return self._date.day

    def plusDays(self, value):
        return LocalDate(self._date + datetime.timedelta(days=int(value or 0)))

    def minusDays(self, value):
        return LocalDate(self._date - datetime.timedelta(days=int(value or 0)))

    def toEpochDay(self):
        return (self._date - datetime.date(1970, 1, 1)).days

    def atStartOfDay(self):
        return LocalDateTime(datetime.datetime.combine(self._date, datetime.time()))

    def toString(self):
        return self._date.isoformat()

    def __str__(self):
        return self.toString()


class LocalTime:
    def __init__(self, value=None):
        self._time = value or datetime.datetime.now().time()

    @classmethod
    def now(cls):
        return cls(datetime.datetime.now().time())

    @classmethod
    def of(cls, hour, minute, second=0):
        return cls(datetime.time(int(hour), int(minute), int(second)))

    def getHour(self):
        return self._time.hour

    def getMinute(self):
        return self._time.minute

    def getSecond(self):
        return self._time.second

    def toString(self):
        return self._time.strftime("%H:%M:%S")

    def __str__(self):
        return self.toString()


class LocalDateTime:
    def __init__(self, value=None):
        self._moment = value or datetime.datetime.now()

    @classmethod
    def now(cls):
        return cls(datetime.datetime.now())

    @classmethod
    def of(cls, year, month, day, hour=0, minute=0, second=0):
        return cls(datetime.datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second)
        ))

    def toLocalDate(self):
        return LocalDate(self._moment.date())

    def toLocalTime(self):
        return LocalTime(self._moment.time())

    def getYear(self):
        return self._moment.year

    def getMonthValue(self):
        return self._moment.month

    def getDayOfMonth(self):
        return self._moment.day

    def getHour(self):
        return self._moment.hour

    def getMinute(self):
        return self._moment.minute

    def getSecond(self):
        return self._moment.second

    def plusDays(self, value):
        return LocalDateTime(self._moment + datetime.timedelta(days=int(value or 0)))

    def toString(self):
        return self._moment.strftime("%Y-%m-%dT%H:%M:%S")

    def __str__(self):
        return self.toString()


class ZoneId:
    def __init__(self, identifier="UTC"):
        self._id = str(identifier or "UTC")

    @classmethod
    def systemDefault(cls):
        return cls(time.tzname[0] if time.tzname else "UTC")

    @classmethod
    def of(cls, identifier):
        return cls(identifier)

    def getId(self):
        return self._id

    def toString(self):
        return self._id


class ZoneOffset(ZoneId):
    UTC = None


ZoneOffset.UTC = ZoneOffset("Z")


class DateTimeFormatter:
    def __init__(self, pattern="yyyy-MM-dd"):
        self._pattern = str(pattern or "yyyy-MM-dd")
        self._python = self._convert(self._pattern)

    @staticmethod
    def _convert(pattern):
        tokens = [
            ("yyyy", "%Y"), ("yy", "%y"),
            ("MMMM", "%B"), ("MMM", "%b"), ("MM", "%m"),
            ("dd", "%d"), ("HH", "%H"), ("hh", "%I"),
            ("mm", "%M"), ("ss", "%S"), ("SSS", "%f"),
            ("EEEE", "%A"), ("EEE", "%a"),
        ]
        result = pattern
        for java, python in sorted(tokens, key=lambda item: -len(item[0])):
            result = result.replace(java, python)
        return result

    @classmethod
    def ofPattern(cls, pattern, locale=None):
        return cls(pattern)

    def format(self, value):
        if isinstance(value, LocalDateTime):
            moment = value._moment
        elif isinstance(value, LocalDate):
            moment = datetime.datetime.combine(value._date, datetime.time())
        elif isinstance(value, LocalTime):
            moment = datetime.datetime.combine(datetime.date.today(), value._time)
        elif isinstance(value, Instant):
            moment = value.toPyDateTime()
        elif isinstance(value, (datetime.date, datetime.datetime)):
            moment = value
        else:
            moment = datetime.datetime.now()
        return moment.strftime(self._python)

    def parse(self, text):
        moment = datetime.datetime.strptime(str(text), self._python)
        return LocalDateTime(moment)


DateTimeFormatter.ISO_LOCAL_DATE = DateTimeFormatter("yyyy-MM-dd")
DateTimeFormatter.ISO_LOCAL_DATE_TIME = DateTimeFormatter("yyyy-MM-dd'T'HH:mm:ss")
