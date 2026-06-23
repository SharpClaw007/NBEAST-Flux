"""NBEAST — neutron-flux Monte Carlo simulation, made approachable.

The `nbeast.core` subpackage is the Qt-free engine layer: domain presets,
geometry templates, the run driver, results reading, and OpenMC-deck export.
The GUI (added later) is a thin layer over `nbeast.core`.
"""

# Single source of truth for the version — pyproject (wheel), the installer
# pipeline, and the app all derive from this one line.
__version__ = "0.0.1"
