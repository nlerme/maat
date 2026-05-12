from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Student:
    group: str
    last_name: str
    first_name: str
    token: str
    animal: str = ""
    animal_entity: str = ""

    @property
    def display_name(self) -> str:
        prefix = f"{self.animal} " if self.animal else ""
        return f"{prefix}{self.first_name} {self.last_name}"
