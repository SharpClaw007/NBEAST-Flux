"""Template specifications — editable parameters + display metadata.

This is what makes the GUI a real model editor without the GUI knowing any
physics: each template declares its editable parameters (key, label, range,
group), and a ``build`` callable that accepts those parameter keys (plus the
eigenvalue run settings) as keyword arguments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import openmc

from . import benchmarks, templates


@dataclass(frozen=True)
class Parameter:
    key: str          # keyword passed to the build callable
    label: str        # human label shown in the UI
    default: float
    minimum: float
    maximum: float
    step: float = 0.1
    decimals: int = 3
    unit: str = ""
    group: str = "Geometry"  # tree group it belongs under: "Materials" | "Geometry"
    kind: str = "float"      # "float" | "int" — picks the editor widget


@dataclass(frozen=True)
class TemplateSpec:
    key: str
    label: str
    build: Callable[..., openmc.model.Model]
    parameters: tuple[Parameter, ...]
    materials: tuple[str, ...]   # display labels for the Materials node
    geometry: str                # display label for the Geometry node
    run_mode: str = "eigenvalue"  # "eigenvalue" (k-eff) | "fixed source" (shielding)

    def defaults(self) -> dict[str, float]:
        return {p.key: p.default for p in self.parameters}

    def params_in(self, group: str) -> list[Parameter]:
        return [p for p in self.parameters if p.group == group]


# Shared across templates: a global temperature (K) for Doppler-feedback studies.
# Cross sections snap to the nearest bundled data temperature (250/294/600/900/1200 K);
# sweeping it traces the temperature reactivity coefficient. Capped at 1200 K so the
# request stays within tolerance of the single-temperature (294 K) water kernel.
TEMPERATURE = Parameter("temperature", "Temperature", 294.0, 250.0, 1200.0,
                        step=50.0, decimals=0, unit="K", group="Materials")


PIN_CELL = TemplateSpec(
    key="pin_cell",
    label="Pin cell",
    build=templates.pin_cell,
    parameters=(
        Parameter("enrichment", "U-235 enrichment", 3.2, 0.1, 100.0,
                  step=0.1, decimals=2, unit="wt%", group="Materials"),
        Parameter("pitch", "Lattice pitch", 1.26, 0.40, 5.0,
                  step=0.01, decimals=3, unit="cm", group="Geometry"),
        Parameter("fuel_radius", "Fuel radius", 0.39, 0.05, 2.0,
                  step=0.01, decimals=3, unit="cm", group="Geometry"),
        Parameter("clad_inner_radius", "Clad inner radius", 0.40, 0.05, 2.0,
                  step=0.01, decimals=3, unit="cm", group="Geometry"),
        Parameter("clad_outer_radius", "Clad outer radius", 0.46, 0.05, 2.0,
                  step=0.01, decimals=3, unit="cm", group="Geometry"),
        TEMPERATURE,
    ),
    materials=("UO₂ fuel", "Zircaloy", "Water"),
    geometry="PWR pin cell (reflective BCs)",
)

GODIVA = TemplateSpec(
    key="godiva",
    label="Godiva",
    build=benchmarks.godiva,
    parameters=(
        Parameter("radius", "Sphere radius", benchmarks.GODIVA_RADIUS, 1.0, 30.0,
                  step=0.1, decimals=4, unit="cm", group="Geometry"),
        TEMPERATURE,
    ),
    materials=("HEU metal (Godiva) — fixed composition",),
    geometry="Bare HEU sphere (vacuum BC)",
)

ASSEMBLY = TemplateSpec(
    key="assembly",
    label="Fuel assembly",
    build=templates.assembly,
    parameters=(
        Parameter("n_side", "Pins per side", 5, 2, 17,
                  step=1, kind="int", group="Geometry"),
        Parameter("enrichment", "U-235 enrichment", 3.2, 0.1, 100.0,
                  step=0.1, decimals=2, unit="wt%", group="Materials"),
        Parameter("pitch", "Pin pitch", 1.26, 0.40, 5.0,
                  step=0.01, decimals=3, unit="cm", group="Geometry"),
        Parameter("fuel_radius", "Fuel radius", 0.39, 0.05, 2.0,
                  step=0.01, decimals=3, unit="cm", group="Geometry"),
        Parameter("clad_inner_radius", "Clad inner radius", 0.40, 0.05, 2.0,
                  step=0.01, decimals=3, unit="cm", group="Geometry"),
        Parameter("clad_outer_radius", "Clad outer radius", 0.46, 0.05, 2.0,
                  step=0.01, decimals=3, unit="cm", group="Geometry"),
        TEMPERATURE,
    ),
    materials=("UO₂ fuel", "Zircaloy", "Water"),
    geometry="N×N PWR fuel assembly (reflective BCs)",
)

SHIELD = TemplateSpec(
    key="shield_slab",
    label="Shield slab",
    build=templates.shield_slab,
    parameters=(
        Parameter("thickness", "Slab thickness", 30.0, 1.0, 200.0,
                  step=1.0, decimals=1, unit="cm", group="Geometry"),
        Parameter("source_energy", "Source energy", 2.0, 0.01, 20.0,
                  step=0.5, decimals=2, unit="MeV", group="Geometry"),
        TEMPERATURE,
    ),
    materials=("Light water shield",),
    geometry="Water slab — neutron beam (reflective sides, vacuum ends)",
    run_mode="fixed source",
)

SPECS: dict[str, TemplateSpec] = {s.label: s for s in (PIN_CELL, GODIVA, ASSEMBLY, SHIELD)}
