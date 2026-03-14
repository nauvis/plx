"""Beckhoff TwinCAT library stubs.

Stubs are organized by TwinCAT library name:

- ``mc2``: Tc2_MC2 — PLCopen motion control (MC_Power, MC_MoveAbsolute, ...)
- ``standard``: Tc2_Standard — LTIME timer variants (LTON, LTOF, LTP)
- ``system``: Tc2_System — ADS communication, file I/O, system services
- ``utilities``: Tc2_Utilities — Time, formatting, PID, ring buffers, system access
"""

from .mc2 import (
    # Enums
    E_JogMode,
    MC_BufferMode,
    MC_Direction,
    MC_HomingMode,
    # Structs
    AXIS_REF,
    ST_AxisStatus,
    ST_HomingOptions,
    ST_MoveOptions,
    # Axis Administration
    MC_Power,
    MC_Reset,
    MC_SetPosition,
    # Status / Parameter
    MC_ReadActualPosition,
    MC_ReadActualVelocity,
    MC_ReadAxisError,
    MC_ReadStatus,
    MC_SetOverride,
    # Point-to-Point Motion
    MC_MoveAbsolute,
    MC_MoveAdditive,
    MC_MoveContinuousAbsolute,
    MC_MoveContinuousRelative,
    MC_MoveModulo,
    MC_MoveRelative,
    MC_MoveVelocity,
    # Stop / Halt
    MC_Halt,
    MC_Stop,
    # Homing
    MC_Home,
    # Manual
    MC_Jog,
    # Coupling
    MC_GearIn,
    MC_GearInDyn,
    MC_GearOut,
    # Touch Probe
    MC_AbortTrigger,
    MC_TouchProbe,
    # Advanced
    MC_MoveSuperImposed,
    MC_TorqueControl,
)
from .standard import (
    LTON,
    LTOF,
    LTP,
)
from .system import (
    ADSRDSTATE,
    ADSRDWRT,
    ADSREAD,
    ADSWRITE,
    FB_FileClose,
    FB_FileDelete,
    FB_FileGets,
    FB_FileOpen,
    FB_FilePuts,
    FB_FileRead,
    FB_FileWrite,
    FB_IecCriticalSection,
    ST_AmsAddr,
    T_AmsNetId,
)
from .utilities import (
    FB_BasicPID,
    FB_CSVMemBufferWriter,
    FB_FormatString,
    FB_LocalSystemTime,
    FB_MemRingBuffer,
    FB_StringRingBuffer,
    NT_GetTime,
    Profiler,
    RTC,
    RTC_EX,
    T_Arg,
    TIMESTRUCT,
)

__all__ = [
    # Enums
    "E_JogMode",
    "MC_BufferMode",
    "MC_Direction",
    "MC_HomingMode",
    # Structs
    "AXIS_REF",
    "ST_AxisStatus",
    "ST_HomingOptions",
    "ST_MoveOptions",
    # Axis Administration
    "MC_Power",
    "MC_Reset",
    "MC_SetPosition",
    # Status / Parameter
    "MC_ReadActualPosition",
    "MC_ReadActualVelocity",
    "MC_ReadAxisError",
    "MC_ReadStatus",
    "MC_SetOverride",
    # Point-to-Point Motion
    "MC_MoveAbsolute",
    "MC_MoveAdditive",
    "MC_MoveContinuousAbsolute",
    "MC_MoveContinuousRelative",
    "MC_MoveModulo",
    "MC_MoveRelative",
    "MC_MoveVelocity",
    # Stop / Halt
    "MC_Halt",
    "MC_Stop",
    # Homing
    "MC_Home",
    # Manual
    "MC_Jog",
    # Coupling
    "MC_GearIn",
    "MC_GearInDyn",
    "MC_GearOut",
    # Touch Probe
    "MC_AbortTrigger",
    "MC_TouchProbe",
    # Advanced
    "MC_MoveSuperImposed",
    "MC_TorqueControl",
    # Tc2_Standard
    "LTON",
    "LTOF",
    "LTP",
    # Tc2_System — data types
    "T_AmsNetId",
    "ST_AmsAddr",
    # Tc2_System — ADS
    "ADSREAD",
    "ADSWRITE",
    "ADSRDWRT",
    "ADSRDSTATE",
    # Tc2_System — file I/O
    "FB_FileOpen",
    "FB_FileClose",
    "FB_FileRead",
    "FB_FileWrite",
    "FB_FileDelete",
    "FB_FileGets",
    "FB_FilePuts",
    # Tc2_System — system
    "FB_IecCriticalSection",
    # Tc2_Utilities
    "FB_BasicPID",
    "FB_CSVMemBufferWriter",
    "FB_FormatString",
    "FB_LocalSystemTime",
    "FB_MemRingBuffer",
    "FB_StringRingBuffer",
    "NT_GetTime",
    "Profiler",
    "RTC",
    "RTC_EX",
    "T_Arg",
    "TIMESTRUCT",
]
