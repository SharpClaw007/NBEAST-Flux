"""Data-free geometry previews for the parametric templates.

The templates are analytic (nested cylinders, lattices, spheres, slabs), so their
cross-sections can be described exactly as a short list of 2-D shapes — no transport,
no nuclear data, no OpenMC plotting round-trip. The GUI paints these shapes (Qt-free
here: this module only produces primitives), which makes the preview instant and able
to render *needs-data* materials that OpenMC itself couldn't resolve yet.

Every template yields an ``xy`` slice and an ``xz`` slice (the CAE convention), with
honest annotations for infinite/reflective extents.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Shape:
    """One paintable primitive, in cm, centred on (x, y) of its slice plane."""

    kind: str                    # "rect" | "circle"
    x: float
    y: float
    w: float                     # rect width / circle diameter
    h: float                     # rect height / circle diameter
    material: str | None         # material catalog key; None = void/gap
    label: str = ""


@dataclass
class SlicePlot:
    shapes: list[Shape]          # painted in order (background first)
    width: float                 # extent of the slice plane (cm)
    height: float
    axes: tuple[str, str] = ("x", "y")
    note: str = ""               # honesty note ("infinite in z", "reflective", …)


@dataclass
class GeometryPreview:
    xy: SlicePlot
    xz: SlicePlot
    legend: list[tuple[str, str]] = field(default_factory=list)   # (material key, label)
    title: str = ""


def _pin_shapes(cx: float, cy: float, fuel_r, clad_ir, clad_or, fuel_key, clad_key):
    return [
        Shape("circle", cx, cy, 2 * clad_or, 2 * clad_or, clad_key, "clad"),
        Shape("circle", cx, cy, 2 * clad_ir, 2 * clad_ir, None, "gap"),
        Shape("circle", cx, cy, 2 * fuel_r, 2 * fuel_r, fuel_key, "fuel"),
    ]


def preview(template: str, params: dict, mats: dict) -> GeometryPreview | None:
    """The geometry preview for a template, or None when it has no analytic preview
    (the CAD template renders from its tessellated solids instead)."""
    builder = _BUILDERS.get(template)
    return builder(params, mats) if builder else None


def _pin_cell(params: dict, mats: dict) -> GeometryPreview:
    p = float(params.get("pitch", 1.26))
    fr = float(params.get("fuel_radius", 0.39))
    ci = float(params.get("clad_inner_radius", 0.40))
    co = float(params.get("clad_outer_radius", 0.46))
    fuel, clad, mod = mats.get("fuel", "uo2"), mats.get("clad", "zircaloy"), mats.get("moderator", "water")

    xy = SlicePlot(
        shapes=[Shape("rect", 0, 0, p, p, mod, "moderator"),
                *_pin_shapes(0, 0, fr, ci, co, fuel, clad)],
        width=p, height=p, axes=("x", "y"),
        note="reflective boundaries (infinite lattice)",
    )
    h = 2.0 * p
    xz = SlicePlot(
        shapes=[Shape("rect", 0, 0, p, h, mod, "moderator"),
                Shape("rect", 0, 0, 2 * co, h, clad, "clad"),
                Shape("rect", 0, 0, 2 * ci, h, None, "gap"),
                Shape("rect", 0, 0, 2 * fr, h, fuel, "fuel")],
        width=p, height=h, axes=("x", "z"),
        note="infinite in z",
    )
    legend = [(fuel, "fuel"), (clad, "cladding"), (mod, "moderator")]
    return GeometryPreview(xy, xz, legend, "PWR pin cell")


def _assembly(params: dict, mats: dict) -> GeometryPreview:
    n = int(params.get("n_side", 5))
    p = float(params.get("pitch", 1.26))
    fr = float(params.get("fuel_radius", 0.39))
    ci = float(params.get("clad_inner_radius", 0.40))
    co = float(params.get("clad_outer_radius", 0.46))
    fuel, clad, mod = mats.get("fuel", "uo2"), mats.get("clad", "zircaloy"), mats.get("moderator", "water")

    side = n * p
    shapes = [Shape("rect", 0, 0, side, side, mod, "moderator")]
    xz_shapes = [Shape("rect", 0, 0, side, 2 * side / max(n, 2), mod, "moderator")]
    half = (n - 1) / 2.0
    for i in range(n):
        cx = (i - half) * p
        for j in range(n):
            cy = (j - half) * p
            shapes += _pin_shapes(cx, cy, fr, ci, co, fuel, clad)
        xz_shapes += [
            Shape("rect", cx, 0, 2 * co, 2 * side / max(n, 2), clad, "clad"),
            Shape("rect", cx, 0, 2 * fr, 2 * side / max(n, 2), fuel, "fuel"),
        ]
    xy = SlicePlot(shapes, side, side, ("x", "y"), "reflective boundaries")
    xz = SlicePlot(xz_shapes, side, 2 * side / max(n, 2), ("x", "z"), "infinite in z")
    legend = [(fuel, "fuel"), (clad, "cladding"), (mod, "moderator")]
    return GeometryPreview(xy, xz, legend, f"{n}×{n} assembly")


def _godiva(params: dict, mats: dict) -> GeometryPreview:
    r = float(params.get("radius", 8.7407))
    mat = mats.get("material", "heu_metal_godiva")
    box = 2.4 * r

    def plane(axes):
        return SlicePlot(
            shapes=[Shape("rect", 0, 0, box, box, None, "vacuum"),
                    Shape("circle", 0, 0, 2 * r, 2 * r, mat, "core")],
            width=box, height=box, axes=axes, note="bare sphere, vacuum boundary")

    return GeometryPreview(plane(("x", "y")), plane(("x", "z")),
                           [(mat, "core")], "Bare sphere")


def _shield(params: dict, mats: dict) -> GeometryPreview:
    t = float(params.get("thickness", 30.0))
    w = 2.0 * float(params.get("transverse_half", 5.0))
    shield = mats.get("shield", "water")
    xy = SlicePlot(
        shapes=[Shape("rect", 0, 0, t, w, shield, "shield")],
        width=t * 1.15, height=w * 1.3, axes=("x", "y"),
        note="monoenergetic beam → enters the left face; transverse reflective",
    )
    xz = SlicePlot(
        shapes=[Shape("rect", 0, 0, t, w, shield, "shield")],
        width=t * 1.15, height=w * 1.3, axes=("x", "z"),
        note="beam →; reflective in y and z (1-D problem)",
    )
    return GeometryPreview(xy, xz, [(shield, "shield")], "Shield slab")


_BUILDERS = {
    "Pin cell": _pin_cell,
    "Fuel assembly": _assembly,
    "Godiva": _godiva,
    "Shield slab": _shield,
}
