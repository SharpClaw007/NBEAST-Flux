"""Material library for NBEAST.

Each preset is a small factory returning a fresh ``openmc.Material`` (so callers can
tweak density/temperature without mutating shared state), plus a :class:`MaterialSpec`
record the GUI enumerates to build the searchable material dropdowns. A material can
belong to several roles (water is both a moderator and a coolant).

NBEAST's bundled offline library only carries H/O/U/Zr data, so most catalog entries
need additional cross sections to actually run. :func:`available_names` + the
``MaterialSpec.is_available`` check let the GUI flag which materials are runnable with
the active library and which need a download — without hiding the rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import openmc

# ---------------------------------------------------------------------------
# Factories — each returns a fresh openmc.Material. Enrichment-parametric fuels
# take an ``enrichment`` kwarg; everything else takes no required arguments.
# ---------------------------------------------------------------------------
def uo2(enrichment: float = 3.2, density: float = 10.4) -> openmc.Material:
    """Uranium dioxide fuel at the given U-235 enrichment (wt%)."""
    m = openmc.Material(name=f"UO2 ({enrichment:g}% enr.)")
    m.add_element("U", 1.0, enrichment=enrichment)
    m.add_element("O", 2.0)
    m.set_density("g/cm3", density)
    return m


def u_metal(enrichment: float = 19.75, density: float = 19.0) -> openmc.Material:
    """Uranium metal at the given enrichment (wt%)."""
    m = openmc.Material(name=f"U metal ({enrichment:g}% enr.)")
    m.add_element("U", 1.0, enrichment=enrichment)
    m.set_density("g/cm3", density)
    return m


def heu_metal_godiva() -> openmc.Material:
    """Highly enriched uranium metal — Godiva (ICSBEP HEU-MET-FAST-001).

    Atom densities (atoms/b-cm) from the benchmark specification; the validated
    fast-criticality reference (bare sphere, k_eff ~= 1.0).
    """
    n_u234, n_u235, n_u238 = 4.9184e-4, 4.4994e-2, 2.4984e-3
    m = openmc.Material(name="HEU metal (Godiva)")
    m.add_nuclide("U234", n_u234)
    m.add_nuclide("U235", n_u235)
    m.add_nuclide("U238", n_u238)
    m.set_density("atom/b-cm", n_u234 + n_u235 + n_u238)
    return m


def mox(pu_fraction: float = 0.07, density: float = 10.4) -> openmc.Material:
    """Mixed-oxide (U,Pu)O2 fuel — depleted U + reactor-grade Pu vector."""
    m = openmc.Material(name=f"MOX ({pu_fraction * 100:g}% Pu)")
    m.add_element("U", 1.0 - pu_fraction, enrichment=0.25)
    m.add_nuclide("Pu239", pu_fraction * 0.93)
    m.add_nuclide("Pu240", pu_fraction * 0.06)
    m.add_nuclide("Pu241", pu_fraction * 0.01)
    m.add_element("O", 2.0)
    m.set_density("g/cm3", density)
    return m


def uo2_gd(enrichment: float = 3.2, gd_wt: float = 0.05, density: float = 10.2) -> openmc.Material:
    """UO2 with Gd2O3 burnable poison (Gd weight fraction)."""
    m = openmc.Material(name=f"UO2 + {gd_wt * 100:g}% Gd2O3")
    m.add_element("U", 1.0 - gd_wt, enrichment=enrichment)
    m.add_element("Gd", gd_wt * 0.5)
    m.add_element("O", 2.0)
    m.set_density("g/cm3", density)
    return m


def u3si2(enrichment: float = 19.75, density: float = 11.3) -> openmc.Material:
    """U3Si2 — accident-tolerant / research-reactor fuel."""
    m = openmc.Material(name=f"U3Si2 ({enrichment:g}% enr.)")
    m.add_element("U", 3.0, enrichment=enrichment)
    m.add_element("Si", 2.0)
    m.set_density("g/cm3", density)
    return m


def u_nitride(enrichment: float = 19.75, density: float = 14.3) -> openmc.Material:
    """Uranium nitride (UN) fuel."""
    m = openmc.Material(name=f"UN ({enrichment:g}% enr.)")
    m.add_element("U", 1.0, enrichment=enrichment)
    m.add_element("N", 1.0)
    m.set_density("g/cm3", density)
    return m


def water(density: float = 1.0, with_sab: bool = True) -> openmc.Material:
    """Light-water moderator/coolant with the H-in-H2O thermal-scattering kernel."""
    m = openmc.Material(name="Water")
    m.add_element("H", 2.0)
    m.add_element("O", 1.0)
    m.set_density("g/cm3", density)
    if with_sab:
        m.add_s_alpha_beta("c_H_in_H2O")
    return m


def heavy_water(density: float = 1.106, with_sab: bool = True) -> openmc.Material:
    """Heavy water D2O moderator/coolant."""
    m = openmc.Material(name="Heavy water (D2O)")
    m.add_nuclide("H2", 2.0)
    m.add_element("O", 1.0)
    m.set_density("g/cm3", density)
    if with_sab:
        m.add_s_alpha_beta("c_D_in_D2O")
    return m


def graphite(density: float = 1.7, with_sab: bool = True) -> openmc.Material:
    """Nuclear graphite moderator/reflector."""
    m = openmc.Material(name="Graphite")
    m.add_element("C", 1.0)
    m.set_density("g/cm3", density)
    if with_sab:
        m.add_s_alpha_beta("c_Graphite")
    return m


def beryllium(density: float = 1.85) -> openmc.Material:
    """Beryllium metal moderator/reflector."""
    m = openmc.Material(name="Beryllium")
    m.add_element("Be", 1.0)
    m.set_density("g/cm3", density)
    return m


def zr_hydride(density: float = 5.6) -> openmc.Material:
    """Zirconium hydride (ZrH1.6) — TRIGA-style solid moderator."""
    m = openmc.Material(name="Zirconium hydride (ZrH1.6)")
    m.add_element("Zr", 1.0)
    m.add_element("H", 1.6)
    m.set_density("g/cm3", density)
    return m


def sodium(density: float = 0.927) -> openmc.Material:
    """Liquid sodium coolant (fast reactors)."""
    m = openmc.Material(name="Sodium")
    m.add_element("Na", 1.0)
    m.set_density("g/cm3", density)
    return m


def helium(density: float = 1.785e-4) -> openmc.Material:
    """Helium coolant (gas-cooled reactors)."""
    m = openmc.Material(name="Helium")
    m.add_element("He", 1.0)
    m.set_density("g/cm3", density)
    return m


def carbon_dioxide(density: float = 1.977e-3) -> openmc.Material:
    """CO2 coolant (AGR/Magnox)."""
    m = openmc.Material(name="Carbon dioxide")
    m.add_element("C", 1.0)
    m.add_element("O", 2.0)
    m.set_density("g/cm3", density)
    return m


def lead(density: float = 11.35) -> openmc.Material:
    """Lead coolant/reflector (LFR)."""
    m = openmc.Material(name="Lead")
    m.add_element("Pb", 1.0)
    m.set_density("g/cm3", density)
    return m


def flibe(density: float = 1.94) -> openmc.Material:
    """FLiBe (Li2BeF4) molten salt coolant."""
    m = openmc.Material(name="FLiBe (Li2BeF4)")
    m.add_element("Li", 2.0)
    m.add_element("Be", 1.0)
    m.add_element("F", 4.0)
    m.set_density("g/cm3", density)
    return m


def air(density: float = 1.205e-3) -> openmc.Material:
    """Dry air."""
    m = openmc.Material(name="Air")
    m.add_element("N", 0.784)
    m.add_element("O", 0.211)
    m.add_element("Ar", 0.005)
    m.set_density("g/cm3", density)
    return m


def void(density: float = 1.0e-9) -> openmc.Material:
    """Near-vacuum filler (a trace of H so it is always renderable/runnable)."""
    m = openmc.Material(name="Void")
    m.add_nuclide("H1", 1.0)
    m.set_density("g/cm3", density)
    return m


def zircaloy(density: float = 6.55) -> openmc.Material:
    """Zirconium cladding (approximated as pure Zr)."""
    m = openmc.Material(name="Zircaloy")
    m.add_element("Zr", 1.0)
    m.set_density("g/cm3", density)
    return m


def steel_304(density: float = 8.0) -> openmc.Material:
    """Type 304 stainless steel."""
    m = openmc.Material(name="Stainless steel 304")
    m.add_element("Fe", 0.70)
    m.add_element("Cr", 0.19)
    m.add_element("Ni", 0.095)
    m.add_element("Mn", 0.015)
    m.set_density("g/cm3", density)
    return m


def steel_316(density: float = 8.0) -> openmc.Material:
    """Type 316 stainless steel."""
    m = openmc.Material(name="Stainless steel 316")
    m.add_element("Fe", 0.68)
    m.add_element("Cr", 0.17)
    m.add_element("Ni", 0.12)
    m.add_element("Mo", 0.025)
    m.set_density("g/cm3", density)
    return m


def inconel_718(density: float = 8.19) -> openmc.Material:
    """Inconel 718 nickel superalloy."""
    m = openmc.Material(name="Inconel 718")
    m.add_element("Ni", 0.53)
    m.add_element("Cr", 0.19)
    m.add_element("Fe", 0.18)
    m.add_element("Nb", 0.05)
    m.add_element("Mo", 0.03)
    m.set_density("g/cm3", density)
    return m


def aluminum(density: float = 2.70) -> openmc.Material:
    """Aluminum (research-reactor cladding/structure)."""
    m = openmc.Material(name="Aluminum")
    m.add_element("Al", 1.0)
    m.set_density("g/cm3", density)
    return m


def b4c(density: float = 2.52) -> openmc.Material:
    """Boron carbide B4C control absorber."""
    m = openmc.Material(name="Boron carbide (B4C)")
    m.add_element("B", 4.0)
    m.add_element("C", 1.0)
    m.set_density("g/cm3", density)
    return m


def ag_in_cd(density: float = 10.17) -> openmc.Material:
    """Silver-indium-cadmium (Ag-In-Cd) control absorber."""
    m = openmc.Material(name="Ag-In-Cd")
    m.add_element("Ag", 0.80)
    m.add_element("In", 0.15)
    m.add_element("Cd", 0.05)
    m.set_density("g/cm3", density)
    return m


def hafnium(density: float = 13.31) -> openmc.Material:
    """Hafnium control absorber."""
    m = openmc.Material(name="Hafnium")
    m.add_element("Hf", 1.0)
    m.set_density("g/cm3", density)
    return m


def gd2o3(density: float = 7.41) -> openmc.Material:
    """Gadolinia (Gd2O3) burnable absorber."""
    m = openmc.Material(name="Gadolinia (Gd2O3)")
    m.add_element("Gd", 2.0)
    m.add_element("O", 3.0)
    m.set_density("g/cm3", density)
    return m


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MaterialSpec:
    key: str
    label: str
    categories: tuple[str, ...]      # roles this material can fill
    factory: Callable[..., openmc.Material]
    enrichment: bool = False          # accepts an ``enrichment`` kwarg
    _nuclide_cache: list = field(default_factory=list, repr=False, compare=False)

    def build(self, enrichment: float | None = None) -> openmc.Material:
        if self.enrichment and enrichment is not None:
            return self.factory(enrichment=float(enrichment))
        return self.factory()

    def required_names(self) -> set[str]:
        """Nuclides + thermal-scattering tables this material needs (cached).

        The active cross-section library is temporarily cleared so ``add_element``
        expands to *all* natural isotopes instead of validating against (and failing
        on) elements the library lacks — that failure is exactly what we're detecting.
        The nuclide set is enrichment-independent, so the probe build is also silent.
        """
        if not self._nuclide_cache:
            import warnings

            import openmc

            saved = openmc.config.get("cross_sections")
            try:
                if saved is not None:
                    del openmc.config["cross_sections"]
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    mat = self.build()
                names = set(mat.get_nuclides()) | {s[0] for s in getattr(mat, "_sab", [])}
            except Exception:  # noqa: BLE001 — undeterminable => treat as needs-data
                names = {"__unknown__"}
            finally:
                if saved is not None:
                    openmc.config["cross_sections"] = saved
            self._nuclide_cache.append(names)
        return self._nuclide_cache[0]

    def is_available(self, available: set[str]) -> bool:
        return self.required_names() <= available


_MATERIALS: tuple[MaterialSpec, ...] = (
    # fuels
    MaterialSpec("uo2", "UO₂ fuel", ("fuel",), uo2, enrichment=True),
    MaterialSpec("u_metal", "Uranium metal", ("fuel",), u_metal, enrichment=True),
    MaterialSpec("heu_metal_godiva", "HEU metal (Godiva)", ("fuel",), heu_metal_godiva),
    MaterialSpec("mox", "MOX (U,Pu)O₂", ("fuel",), mox),
    MaterialSpec("uo2_gd", "UO₂ + Gd₂O₃", ("fuel",), uo2_gd, enrichment=True),
    MaterialSpec("u3si2", "U₃Si₂", ("fuel",), u3si2, enrichment=True),
    MaterialSpec("u_nitride", "Uranium nitride (UN)", ("fuel",), u_nitride, enrichment=True),
    # moderators / reflectors
    MaterialSpec("water", "Light water", ("moderator", "coolant"), water),
    MaterialSpec("heavy_water", "Heavy water (D₂O)", ("moderator", "coolant"), heavy_water),
    MaterialSpec("graphite", "Graphite", ("moderator", "reflector"), graphite),
    MaterialSpec("beryllium", "Beryllium", ("moderator", "reflector"), beryllium),
    MaterialSpec("zr_hydride", "Zirconium hydride", ("moderator",), zr_hydride),
    # coolants
    MaterialSpec("sodium", "Sodium", ("coolant",), sodium),
    MaterialSpec("helium", "Helium", ("coolant",), helium),
    MaterialSpec("carbon_dioxide", "Carbon dioxide", ("coolant",), carbon_dioxide),
    MaterialSpec("lead", "Lead", ("coolant", "reflector"), lead),
    MaterialSpec("flibe", "FLiBe salt", ("coolant",), flibe),
    MaterialSpec("air", "Air", ("coolant",), air),
    MaterialSpec("void", "Void / vacuum", ("coolant", "moderator"), void),
    # cladding / structural
    MaterialSpec("zircaloy", "Zircaloy", ("cladding", "structural"), zircaloy),
    MaterialSpec("steel_304", "Stainless steel 304", ("cladding", "structural"), steel_304),
    MaterialSpec("steel_316", "Stainless steel 316", ("cladding", "structural"), steel_316),
    MaterialSpec("inconel_718", "Inconel 718", ("cladding", "structural"), inconel_718),
    MaterialSpec("aluminum", "Aluminum", ("cladding", "structural"), aluminum),
    # absorbers
    MaterialSpec("b4c", "Boron carbide (B₄C)", ("absorber",), b4c),
    MaterialSpec("ag_in_cd", "Ag-In-Cd", ("absorber",), ag_in_cd),
    MaterialSpec("hafnium", "Hafnium", ("absorber",), hafnium),
    MaterialSpec("gd2o3", "Gadolinia (Gd₂O₃)", ("absorber",), gd2o3),
)

LIBRARY: dict[str, MaterialSpec] = {m.key: m for m in _MATERIALS}


def by_category(category: str) -> list[MaterialSpec]:
    """Materials that can fill a given role, available-first then alphabetical-ish
    (catalog order preserved within each group)."""
    return [m for m in _MATERIALS if category in m.categories]


def get(key: str) -> MaterialSpec:
    return LIBRARY[key]


def build(key: str, enrichment: float | None = None) -> openmc.Material:
    """Build a material by catalog key (enrichment applied only where relevant)."""
    return LIBRARY[key].build(enrichment=enrichment)


def available_names(cross_sections: str | None) -> set[str]:
    """Every nuclide + thermal table named in a cross_sections.xml (empty if none)."""
    if not cross_sections or not Path(cross_sections).exists():
        return set()
    try:
        import xml.etree.ElementTree as ET

        root = ET.parse(cross_sections).getroot()
        return {lib.get("materials") for lib in root.findall("library") if lib.get("materials")}
    except Exception:  # noqa: BLE001
        return set()


# Back-compat registry (older callers): key -> (label, factory).
PRESETS = {
    "uo2": ("UO₂ fuel", uo2),
    "water": ("Light water", water),
    "zircaloy": ("Zircaloy cladding", zircaloy),
    "heu_metal_godiva": ("HEU metal (Godiva)", heu_metal_godiva),
}
