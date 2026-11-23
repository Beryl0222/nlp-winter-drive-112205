"""台账数据模型：载入 records.json 并联接线索。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Car:
    id: str
    series: str
    build: str  # 新版 / 旧版


@dataclass(frozen=True)
class Run:
    id: str
    car: str
    road: str
    phase: str  # warmup / afterheat
    mode: str   # auto / manual
    temp: int
    speed: tuple
    duration: int
    started: str


@dataclass(frozen=True)
class Note:
    id: str
    observer: str
    run_hint: tuple
    text: str


@dataclass(frozen=True)
class Claim:
    id: str
    scope: str
    type: str
    required: int
    evidence: str


@dataclass(frozen=True)
class Signoff:
    id: str
    claim: str
    author: str
    text: str


@dataclass(frozen=True)
class Copy:
    id: str
    state: str
    refs: tuple
    text: str


@dataclass
class Ledger:
    cars: dict
    runs: dict
    notes: dict
    claims: dict
    signoffs: dict
    copy: dict

    @classmethod
    def load(cls, path) -> "Ledger":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            cars={c["id"]: Car(c["id"], c["series"], c["build"]) for c in raw["cars"]},
            runs={r["id"]: Run(r["id"], r["car"], r["road"], r["phase"], r["mode"],
                               r["temp"], tuple(r["speed"]), r["duration"], r["started"])
                  for r in raw["runs"]},
            notes={n["id"]: Note(n["id"], n["observer"], tuple(n["run_hint"]), n["text"])
                   for n in raw["notes"]},
            claims={c["id"]: Claim(c["id"], c["scope"], c["type"], c["required"], c["evidence"])
                    for c in raw["claims"]},
            signoffs={s["id"]: Signoff(s["id"], s["claim"], s["author"], s["text"])
                      for s in raw["signoffs"]},
            copy={k["id"]: Copy(k["id"], k["state"], tuple(k["refs"]), k["text"])
                  for k in raw["copy"]},
        )

    def series(self) -> set:
        return {c.series for c in self.cars.values()}

    def roads(self) -> set:
        return {r.road for r in self.runs.values()}
