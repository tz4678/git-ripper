import io
import struct
import typing
from dataclasses import dataclass


class Error(Exception):
    message: str = None

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.message
        super().__init__(self.message)

    @classmethod
    def raise_if_not(
        cls, condition: bool, *args: typing.Any, **kwargs: typing.Any
    ) -> None:
        if not condition:
            raise cls(*args, **kwargs)


class InvalidSignature(Error):
    message: str = "Invalid signature"


class InvalidVersion(Error):
    message: str = "Invalid version"


@dataclass
class Header:
    signature: bytes
    version: int
    num_entries: int


@dataclass
class Entry:
    ctime_seconds: int
    ctime_nanoseconds: int
    mtime_seconds: int
    mtime_nanoseconds: int
    dev: int
    ino: int
    mode: int
    uid: int
    gid: int
    file_size: int  # 40 bytes
    sha1: bytes  # +20 bytes
    flags: int  # +2 bytes
    file_path: bytes  # null-terminated


@dataclass
class GitIndex:
    # https://git-scm.com/docs/index-format
    # TODO: add support of extenions
    _fp: typing.BinaryIO

    def parse(self) -> None:
        try:
            self._fp.seek(0)
        except:
            pass
        self.parse_header()
        self.parse_entries()

    __post_init__ = parse

    def parse_header(self) -> None:
        self.header = Header(*self.read_struct('!4s2I'))
        InvalidSignature.raise_if_not(self.header.signature == b'DIRC')
        InvalidVersion.raise_if_not(self.header.version in (2, 3, 4))

    def parse_entries(self) -> None:
        self.entries = []
        for _ in range(self.header.num_entries):
            entrysize = self._fp.tell()
            # В struct нету null-terminated strings
            unpacked = self.read_struct('!10I20sH')
            # путь всегда заканчивается null-byte
            buf = io.BytesIO()
            while (c := self._fp.read(1)) and c != b'\0':
                buf.write(c)
            entry = Entry(*unpacked, buf.getvalue())
            entrysize -= self._fp.tell()
            # размер entry кратен 8: file path добивается null-байтами
            self._fp.seek(entrysize % 8, io.SEEK_CUR)
            # print(entry)
            self.entries.append(entry)

    def __iter__(self) -> typing.Iterator[Entry]:
        return iter(self.entries)

    def read_struct(self, format: str) -> tuple[typing.Any, ...]:
        return struct.unpack(format, self._fp.read(struct.calcsize(format)))
