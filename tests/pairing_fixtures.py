"""Shared synthetic entity and DBC fixtures for pairing regressions."""

from pathlib import Path
from dbc_compare_tool.core.models import DbcDatabase, Message, Signal


def signal(name="Speed", start=0, **kwargs):
    values = dict(
        name=name,
        start_bit=start,
        length=8,
        byte_order=1,
        value_type="unsigned",
        is_signed=False,
        factor=1.0,
        offset=0.0,
        minimum=0.0,
        maximum=255.0,
        unit="km/h",
        receivers=("ECU",),
    )
    values.update(kwargs)
    return Signal(**values)


def message(name="Status", frame=100, signals=None, **kwargs):
    return Message(
        name, frame, 8, "ECU", signals={s.name: s for s in (signals or [])}, **kwargs
    )


def database(path, messages):
    return DbcDatabase(Path(path), {m.name: m for m in messages})


def write_dbc(path, *, name="Status", frame=100, sig="Speed", start=0, length=8):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'VERSION ""\nBU_: ECU\nBO_ {frame} {name}: 8 ECU\n'
        f' SG_ {sig} : {start}|{length}@1+ (1,0) [0|255] "km/h" ECU\n',
        encoding="utf-8",
    )
    return path
