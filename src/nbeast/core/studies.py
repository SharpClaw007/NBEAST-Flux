"""Persistent studies — configured, re-runnable analyses saved in the project.

A **Study** is the durable replacement for the one-shot analysis dialogs: it captures
*what* to run (kind + parameters + run quality) as serializable data, so it survives
closing a window and reopening a project, and can be re-run or duplicated. This module
is the Qt-free model + registry; the GUI builds config forms from the registry, runs
studies on a shared queue, and stores their results back here.

Study kinds (v1): ``keff`` (a single eigenvalue/fixed-source run — the default study
every project gets), ``sweep`` and ``search`` (parameter sweep / criticality search),
``moderation``, ``poisoning``, ``mgxs``, ``depletion``. Each kind advertises the
parameter fields the form should show via :data:`STUDY_KINDS`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StudyField:
    """One configurable parameter of a study kind (drives the generic config form)."""

    key: str
    label: str
    kind: str            # "float" | "int" | "choice" | "param" (a template parameter)
    default: object = None
    minimum: float = 0.0
    maximum: float = 1.0e12
    choices: tuple = ()
    help: str = ""


@dataclass(frozen=True)
class StudyKind:
    key: str
    label: str
    summary: str
    fields: tuple[StudyField, ...] = ()
    eigenvalue_only: bool = True
    needs_moderator: bool = False


# The registry the GUI enumerates. Quality (batches/particles/seed) is common to every
# study and handled separately, so it is not repeated in each kind's fields.
STUDY_KINDS: dict[str, StudyKind] = {
    "keff": StudyKind(
        "keff", "k-effective run",
        "A single transport run — k-eff (eigenvalue) or flux/dose (fixed source).",
        eigenvalue_only=False,
    ),
    "sweep": StudyKind(
        "sweep", "Parameter sweep",
        "Vary one model parameter over a range and watch k respond.",
        fields=(
            StudyField("parameter", "Parameter", "param", help="Which model parameter to vary."),
            StudyField("lo", "From", "float", help="Range start (parameter units)."),
            StudyField("hi", "To", "float", help="Range end."),
            StudyField("points", "Points", "int", default=7, minimum=2, maximum=50),
        ),
    ),
    "search": StudyKind(
        "search", "Criticality search",
        "Find the parameter value that drives k to a target (reported x ± σₓ).",
        fields=(
            StudyField("parameter", "Parameter", "param"),
            StudyField("target", "Target k", "float", default=1.0, minimum=0.1, maximum=5.0),
            StudyField("lo", "Bracket from", "float"),
            StudyField("hi", "Bracket to", "float"),
            StudyField("max_evals", "Max evaluations", "int", default=12, minimum=3, maximum=30),
        ),
    ),
    "moderation": StudyKind(
        "moderation", "Moderation / reactivity curve",
        "k, reactivity, and source multiplication vs moderator density.",
        needs_moderator=True,
    ),
    "poisoning": StudyKind(
        "poisoning", "Reactor poisoning (Xe-135 / Sm-149)",
        "Equilibrium fission-product worths, spectrum-consistent.",
        needs_moderator=True,
        fields=(
            StudyField("level", "Xe-135 level", "choice", default="saturation",
                       choices=("saturation", "1e13", "1e14"),
                       help="Saturated operating equilibrium (default) or a sub-saturation flux."),
        ),
    ),
    "mgxs": StudyKind(
        "mgxs", "Multigroup constants",
        "Collapse the run into a complete few-group diffusion set.",
        fields=(
            StudyField("structure", "Group structure", "choice", default="CASMO-2",
                       choices=("CASMO-2", "CASMO-4", "CASMO-8", "CASMO-16")),
        ),
    ),
    "depletion": StudyKind(
        "depletion", "Depletion / burnup",
        "k vs burnup as the fuel depletes (needs a chain download).",
        fields=(
            StudyField("steps", "Burnup steps", "int", default=5, minimum=1, maximum=200),
            StudyField("step_days", "Days per step", "float", default=30.0,
                       minimum=0.1, maximum=3650.0),
        ),
    ),
}


@dataclass
class StudyConfig:
    """A study's serializable definition: kind + name + parameters + run quality."""

    kind: str
    name: str
    params: dict = field(default_factory=dict)
    quality: dict = field(default_factory=dict)     # batches / particles / seed
    study_id: str = ""

    def to_dict(self) -> dict:
        return {"kind": self.kind, "name": self.name, "params": dict(self.params),
                "quality": dict(self.quality), "study_id": self.study_id}

    @classmethod
    def from_dict(cls, data: dict) -> "StudyConfig":
        return cls(kind=data.get("kind", "keff"), name=data.get("name", ""),
                   params=dict(data.get("params", {})), quality=dict(data.get("quality", {})),
                   study_id=data.get("study_id", ""))

    @property
    def spec(self) -> StudyKind | None:
        return STUDY_KINDS.get(self.kind)


@dataclass
class StudyResult:
    """The outcome of running a study — scalar results + artifact references, saved
    in the project so plots reload without a re-run."""

    ok: bool = False
    summary: str = ""
    scalars: dict = field(default_factory=dict)     # e.g. {"keff": 1.413, "keff_std": 8.6e-4}
    points: list = field(default_factory=list)      # sweep/curve points
    artifacts: dict = field(default_factory=dict)   # name -> path relative to project
    created_utc: str = ""
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "summary": self.summary, "scalars": dict(self.scalars),
                "points": list(self.points), "artifacts": dict(self.artifacts),
                "created_utc": self.created_utc, "warnings": list(self.warnings)}

    @classmethod
    def from_dict(cls, data: dict) -> "StudyResult":
        return cls(ok=data.get("ok", False), summary=data.get("summary", ""),
                   scalars=dict(data.get("scalars", {})), points=list(data.get("points", [])),
                   artifacts=dict(data.get("artifacts", {})),
                   created_utc=data.get("created_utc", ""), warnings=list(data.get("warnings", [])))


def default_name(kind: str, existing: list[str]) -> str:
    """A unique default study name ('Parameter sweep', 'Parameter sweep 2', …)."""
    base = STUDY_KINDS[kind].label if kind in STUDY_KINDS else kind
    if base not in existing:
        return base
    n = 2
    while f"{base} {n}" in existing:
        n += 1
    return f"{base} {n}"


def available_kinds(*, eigenvalue: bool, moderated: bool) -> list[str]:
    """Study kinds applicable to the current template."""
    out = []
    for key, spec in STUDY_KINDS.items():
        if spec.eigenvalue_only and not eigenvalue:
            continue
        if spec.needs_moderator and not moderated:
            continue
        out.append(key)
    return out
