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
    # Backing structs
    FBD_ONESHOT,
    FBD_TIMER,
    MESSAGE,
    # Enhanced timers
    TONR,
    TOFR,
    RTOR,
    # One-shots
    OSRI,
    OSFI,
    # Filters
    HPF,
    LPF,
    NTCH,
    DERV,
    INTG,
    # Statistics
    MAVE,
    MSTD,
    MAXC,
    MINC,
    # Drives
    PMUL,
    SCRV,
    PI,
    SOC,
    UPDN,
    CC,
    # I/O
    MSG,
)
from .motion import (
    # Enums
    MC_AB_Direction,
    MC_AB_MoveType,
    MC_AB_StopType,
    # Structs
    AXIS_CIP_DRIVE,
    AXIS_SERVO,
    AXIS_SERVO_DRIVE,
    AXIS_VIRTUAL,
    COORDINATE_SYSTEM,
    MOTION_GROUP,
    MOTION_INSTRUCTION,
    # Motion State
    MAFR,
    MASD,
    MASR,
    MSF,
    MSO,
    # Motion Move
    MAG,
    MAH,
    MAHD,
    MAJ,
    MAM,
    MAS,
    MCD,
    # Cam / Position Cam
    MAPC,
    MATC,
    # Motion Group
    MGS,
    MGSD,
    MGSP,
    MGSR,
    # Motion Events
    MAOC,
    MAR,
    MAW,
    MDOC,
    MDR,
    MDW,
    # Coordinated Motion
    MCCM,
    MCCD,
    MCLM,
    MCS,
    MCT,
)
from .process import (
    # PID
    PIDE,
    # Scaling
    SCL,
    # Alarms
    ALMD,
    ALMA,
    # Profile
    RMPS,
    # Valve / Actuator
    POSP,
    SRTP,
    D2SD,
    D3SD,
    # Dynamic Compensation
    LDLG,
    DEDT,
    # Function Generator
    FGEN,
    # Totalizer
    TOT,
    # Select / Mux
    SEL,
    MUX,
    ESEL,
    # Limit / Clamp
    HLL,
    RLIM,
    # Math
    SNEG,
    SSUM,
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
