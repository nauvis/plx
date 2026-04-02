"""Allen Bradley library stubs.

Stubs are organized by Rockwell library/category:

- ``process``: Process control (PIDE, SCL, ALMD, ALMA, RMPS, POSP, etc.)
- ``drives``: Enhanced timers, filters, statistics, drives, MSG
- ``motion``: CIP Motion control (MSO, MSF, MAM, MAJ, MAS, MAH, etc.)

Note: GSV/SSV are stateless instructions (not FBs) called as
``GSV(ClassName, InstanceName, AttributeName, Dest)`` in ST.  They compile
to FunctionCallStatement nodes, not FBInvocation, and cannot be represented
as LibraryFB stubs.  The AB parser/raise pass already handles them correctly.
"""

from .drives import (
    CC,
    DERV,
    # Backing structs
    FBD_ONESHOT,
    FBD_TIMER,
    # Filters
    HPF,
    INTG,
    LPF,
    # Statistics
    MAVE,
    MAXC,
    MESSAGE,
    MINC,
    # I/O
    MSG,
    MSTD,
    NTCH,
    OSFI,
    # One-shots
    OSRI,
    PI,
    # Drives
    PMUL,
    RTOR,
    SCRV,
    SOC,
    TOFR,
    # Enhanced timers
    TONR,
    UPDN,
)
from .motion import (
    # Structs
    AXIS_CIP_DRIVE,
    AXIS_SERVO,
    AXIS_SERVO_DRIVE,
    AXIS_VIRTUAL,
    COORDINATE_SYSTEM,
    # Motion State
    MAFR,
    # Motion Move
    MAG,
    MAH,
    MAHD,
    MAJ,
    MAM,
    # Motion Events
    MAOC,
    # Cam / Position Cam
    MAPC,
    MAR,
    MAS,
    MASD,
    MASR,
    MATC,
    MAW,
    MCCD,
    # Coordinated Motion
    MCCM,
    MCD,
    MCLM,
    MCS,
    MCT,
    MDOC,
    MDR,
    MDW,
    # Motion Group
    MGS,
    MGSD,
    MGSP,
    MGSR,
    MOTION_GROUP,
    MOTION_INSTRUCTION,
    MSF,
    MSO,
    # Enums
    MC_AB_Direction,
    MC_AB_MoveType,
    MC_AB_StopType,
)
from .process import (
    ALMA,
    # Alarms
    ALMD,
    D2SD,
    D3SD,
    DEDT,
    ESEL,
    # Function Generator
    FGEN,
    # Limit / Clamp
    HLL,
    # Dynamic Compensation
    LDLG,
    MUX,
    # PID
    PIDE,
    # Valve / Actuator
    POSP,
    RLIM,
    # Profile
    RMPS,
    # Scaling
    SCL,
    # Select / Mux
    SEL,
    # Math
    SNEG,
    SRTP,
    SSUM,
    # Totalizer
    TOT,
)

__all__ = [
    # Drives — Backing structs
    "FBD_ONESHOT",
    "FBD_TIMER",
    "MESSAGE",
    # Drives — Enhanced timers
    "TONR",
    "TOFR",
    "RTOR",
    # Drives — One-shots
    "OSRI",
    "OSFI",
    # Drives — Filters
    "HPF",
    "LPF",
    "NTCH",
    "DERV",
    "INTG",
    # Drives — Statistics
    "MAVE",
    "MSTD",
    "MAXC",
    "MINC",
    # Drives — Drives
    "PMUL",
    "SCRV",
    "PI",
    "SOC",
    "UPDN",
    "CC",
    # Drives — I/O
    "MSG",
    # Motion — Enums
    "MC_AB_Direction",
    "MC_AB_MoveType",
    "MC_AB_StopType",
    # Motion — Structs
    "AXIS_CIP_DRIVE",
    "AXIS_SERVO",
    "AXIS_SERVO_DRIVE",
    "AXIS_VIRTUAL",
    "COORDINATE_SYSTEM",
    "MOTION_GROUP",
    "MOTION_INSTRUCTION",
    # Motion State
    "MAFR",
    "MASD",
    "MASR",
    "MSF",
    "MSO",
    # Motion Move
    "MAG",
    "MAH",
    "MAHD",
    "MAJ",
    "MAM",
    "MAS",
    "MCD",
    # Cam / Position Cam
    "MAPC",
    "MATC",
    # Motion Group
    "MGS",
    "MGSD",
    "MGSP",
    "MGSR",
    # Motion Events
    "MAOC",
    "MAR",
    "MAW",
    "MDOC",
    "MDR",
    "MDW",
    # Coordinated Motion
    "MCCM",
    "MCCD",
    "MCLM",
    "MCS",
    "MCT",
    # Process — PID
    "PIDE",
    # Process — Scaling
    "SCL",
    # Process — Alarms
    "ALMD",
    "ALMA",
    # Process — Profile
    "RMPS",
    # Process — Valve / Actuator
    "POSP",
    "SRTP",
    "D2SD",
    "D3SD",
    # Process — Dynamic Compensation
    "LDLG",
    "DEDT",
    # Process — Function Generator
    "FGEN",
    # Process — Totalizer
    "TOT",
    # Process — Select / Mux
    "SEL",
    "MUX",
    "ESEL",
    # Process — Limit / Clamp
    "HLL",
    "RLIM",
    # Process — Math
    "SNEG",
    "SSUM",
]
