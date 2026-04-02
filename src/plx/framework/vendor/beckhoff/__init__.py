"""Beckhoff TwinCAT library stubs.

Stubs are organized by TwinCAT library name:

- ``mc2``: Tc2_MC2 — PLCopen motion control (MC_Power, MC_MoveAbsolute, ...)
- ``standard``: Tc2_Standard — LTIME timer variants (LTON, LTOF, LTP)
- ``system``: Tc2_System — ADS communication, file I/O, system services
- ``utilities``: Tc2_Utilities — Time, formatting, PID, ring buffers, system access

Note: Tc3_EventLogger FBs (FB_TcMessage, FB_TcAlarm, etc.) are method-based
OOP function blocks that use .Create()/.Send()/.Raise()/.Clear() methods and
properties rather than VAR_INPUT/VAR_OUTPUT parameters. They cannot be
represented as LibraryFB stubs and require method/property support first.
"""

from .mc2 import (
    # Structs
    AXIS_REF,
    # Enums
    E_JogMode,
    # Touch Probe
    MC_AbortTrigger,
    MC_BufferMode,
    MC_Direction,
    # Coupling
    MC_GearIn,
    MC_GearInDyn,
    MC_GearOut,
    # Stop / Halt
    MC_Halt,
    # Homing
    MC_Home,
    MC_HomingMode,
    # Manual
    MC_Jog,
    # Point-to-Point Motion
    MC_MoveAbsolute,
    MC_MoveAdditive,
    MC_MoveContinuousAbsolute,
    MC_MoveContinuousRelative,
    MC_MoveModulo,
    MC_MoveRelative,
    # Advanced
    MC_MoveSuperImposed,
    MC_MoveVelocity,
    # Axis Administration
    MC_Power,
    # Status / Parameter
    MC_ReadActualPosition,
    MC_ReadActualVelocity,
    MC_ReadAxisError,
    # Parameter Read / Write
    MC_ReadBoolParameter,
    MC_ReadParameter,
    MC_ReadParameterSet,
    MC_ReadStatus,
    MC_Reset,
    MC_SetOverride,
    MC_SetPosition,
    MC_Stop,
    MC_TorqueControl,
    MC_TouchProbe,
    MC_WriteBoolParameter,
    MC_WriteBoolParameterPersistent,
    MC_WriteParameter,
    MC_WriteParameterPersistent,
    ST_AxisStatus,
    ST_HomingOptions,
    ST_MoveOptions,
)
from .standard import (
    LTOF,
    LTON,
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
    RTC,
    RTC_EX,
    TIMESTRUCT,
    FB_BasicPID,
    FB_CSVMemBufferWriter,
    FB_FormatString,
    FB_LocalSystemTime,
    FB_MemRingBuffer,
    FB_StringRingBuffer,
    NT_GetTime,
    Profiler,
    T_Arg,
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
    # Parameter Read / Write
    "MC_ReadBoolParameter",
    "MC_ReadParameter",
    "MC_ReadParameterSet",
    "MC_WriteBoolParameter",
    "MC_WriteBoolParameterPersistent",
    "MC_WriteParameter",
    "MC_WriteParameterPersistent",
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
