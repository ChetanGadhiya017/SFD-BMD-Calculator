"""Shear force & bending moment solver for statically determinate beams."""

from .solver import (
    Beam,
    BeamError,
    MomentLoad,
    PointLoad,
    Result,
    UDL,
    solve,
)

__all__ = ["Beam", "BeamError", "MomentLoad", "PointLoad", "Result", "UDL", "solve"]
__version__ = "2.0.0"
