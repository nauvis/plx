"""Tc2_Utilities — TwinCAT utility library stubs.

Beckhoff's general-purpose utility library covering time/date handling,
string formatting, PID control, ring buffers, system time access,
profiling, and CSV writing.

Available types:

Structs:
    TIMESTRUCT          Time structure (year, month, day, hour, etc.)
    T_Arg               Universal argument for formatted output

Function Blocks:
    FB_FormatString     printf-style string formatting
    FB_BasicPID         Discretized PID controller
    RTC                 Real-time clock
    RTC_EX              Extended real-time clock (higher precision)
    FB_MemRingBuffer    Memory-based FIFO/LIFO ring buffer
    FB_StringRingBuffer String ring buffer
    NT_GetTime          Read Windows system time
    FB_LocalSystemTime  Get local system time as TIMESTRUCT
    Profiler            Execution time measurement
    FB_CSVMemBufferWriter  Write CSV data to memory buffer

Note: do NOT use ``from __future__ import annotations`` in stub files —
annotations must be live objects for interface parsing.
"""

from plx.framework._descriptors import Input, Output
from plx.framework._library import LibraryFB, LibraryStruct
from plx.framework._types import BOOL, INT, REAL, TIME, UDINT, WORD


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class TIMESTRUCT(LibraryStruct, vendor="beckhoff", library="Tc2_Utilities"):
    """Windows SYSTEMTIME structure for date/time representation.

    Used by NT_GetTime, FB_LocalSystemTime, and other time-related FBs
    to pass structured date/time values.
    """

    wYear: WORD
    wMonth: WORD
    wDayOfWeek: WORD
    wDay: WORD
    wHour: WORD
    wMinute: WORD
    wSecond: WORD
    wMilliseconds: WORD


class T_Arg(LibraryStruct, vendor="beckhoff", library="Tc2_Utilities"):
    """Universal argument descriptor for FB_FormatString.

    T_Arg is a union-like structure that carries a typed value reference.
    Do not construct T_Arg directly — use the helper functions:
    F_BOOL(), F_BYTE(), F_WORD(), F_DWORD(), F_INT(), F_DINT(),
    F_REAL(), F_LREAL(), F_STRING(), F_UDINT(), F_ULINT(), etc.

    Each helper returns a T_Arg with the correct type tag and pointer
    to the source variable.
    """


# ---------------------------------------------------------------------------
# Function blocks — String formatting
# ---------------------------------------------------------------------------

class FB_FormatString(LibraryFB, vendor="beckhoff", library="Tc2_Utilities"):
    """printf-style string formatting.

    Formats up to 10 arguments into a string using C-style format
    specifiers (%d, %f, %s, etc.).  Arguments are passed as T_Arg
    values created via F_INT(), F_REAL(), F_STRING(), etc.
    Only arg1 through arg4 are declared here; the real FB has arg1-arg10.
    """

    sFormat: Input[str]
    arg1: Input[T_Arg]
    arg2: Input[T_Arg]
    arg3: Input[T_Arg]
    arg4: Input[T_Arg]

    bError: Output[BOOL]
    nErrId: Output[UDINT]
    sOut: Output[str]


# ---------------------------------------------------------------------------
# Function blocks — PID control
# ---------------------------------------------------------------------------

class FB_BasicPID(LibraryFB, vendor="beckhoff", library="Tc2_Utilities"):
    """Simple discretized PID controller.

    Suitable for basic temperature, pressure, and flow control loops.
    For advanced PID (cascade, ratio, feed-forward), use the
    Tc2_TcpIp or Tc3_Controller libraries instead.
    """

    fSetpointValue: Input[REAL]
    fActualValue: Input[REAL]
    fManSyncValue: Input[REAL]
    bSync: Input[BOOL]

    # Tuning parameters
    fKp: Input[REAL]
    fTn: Input[REAL]
    fTv: Input[REAL]
    fTd: Input[REAL]
    fOutMaxLimit: Input[REAL]
    fOutMinLimit: Input[REAL]

    fOut: Output[REAL]
    bARWactive: Output[BOOL]
    eErrorId: Output[INT]
    bError: Output[BOOL]


# ---------------------------------------------------------------------------
# Function blocks — Real-time clock
# ---------------------------------------------------------------------------

class RTC(LibraryFB, vendor="beckhoff", library="Tc2_Utilities"):
    """Real-time clock (IEC 61131-3 compatible).

    When EN is TRUE, CDT tracks the current date/time starting from
    PDT.  Q indicates the clock is running.
    """

    EN: Input[BOOL]
    PDT: Input[UDINT]

    Q: Output[BOOL]
    CDT: Output[UDINT]


class RTC_EX(LibraryFB, vendor="beckhoff", library="Tc2_Utilities"):
    """Extended real-time clock with millisecond precision.

    Higher-resolution variant of RTC that provides time as a
    TIMESTRUCT output for direct field access.
    """

    EN: Input[BOOL]
    PDT: Input[UDINT]

    Q: Output[BOOL]
    CDT: Output[UDINT]


# ---------------------------------------------------------------------------
# Function blocks — Ring buffers
# ---------------------------------------------------------------------------

class FB_MemRingBuffer(LibraryFB, vendor="beckhoff", library="Tc2_Utilities"):
    """Memory ring buffer for FIFO/LIFO data storage.

    Provides a fixed-size circular buffer that stores arbitrary data
    blocks.  Data is written/read as raw byte sequences with explicit
    size parameters.
    """

    bWrite: Input[BOOL]
    bRead: Input[BOOL]
    cbWriteSize: Input[UDINT]
    cbReadSize: Input[UDINT]
    bReset: Input[BOOL]

    bOk: Output[BOOL]
    nCount: Output[UDINT]
    cbSize: Output[UDINT]
    cbFreeSize: Output[UDINT]
    bError: Output[BOOL]
    nErrId: Output[UDINT]


class FB_StringRingBuffer(LibraryFB, vendor="beckhoff", library="Tc2_Utilities"):
    """String ring buffer for FIFO/LIFO string storage.

    Specialized ring buffer for STRING values.  Write strings with
    bWrite + sWrite, read them back with bRead + sRead.
    """

    bWrite: Input[BOOL]
    bRead: Input[BOOL]
    sWrite: Input[str]
    bReset: Input[BOOL]

    bOk: Output[BOOL]
    sRead: Output[str]
    nCount: Output[UDINT]
    bError: Output[BOOL]
    nErrId: Output[UDINT]


# ---------------------------------------------------------------------------
# Function blocks — System time
# ---------------------------------------------------------------------------

class NT_GetTime(LibraryFB, vendor="beckhoff", library="Tc2_Utilities"):
    """Read the Windows system time from the TwinCAT runtime.

    Performs an ADS request to read the OS clock.  NETID selects the
    target runtime (empty string for local).  Result is returned as
    a TIMESTRUCT.
    """

    NETID: Input[str]
    START: Input[BOOL]
    TMOUT: Input[TIME]

    BUSY: Output[BOOL]
    ERR: Output[BOOL]
    ERRID: Output[UDINT]
    TIMESTR: Output[TIMESTRUCT]


class FB_LocalSystemTime(LibraryFB, vendor="beckhoff", library="Tc2_Utilities"):
    """Get local system time as a TIMESTRUCT.

    Simpler alternative to NT_GetTime — enable with bEnable and read
    the result from systemTime.  No ADS call required.
    """

    bEnable: Input[BOOL]

    bValid: Output[BOOL]
    systemTime: Output[TIMESTRUCT]


# ---------------------------------------------------------------------------
# Function blocks — Profiling
# ---------------------------------------------------------------------------

class Profiler(LibraryFB, vendor="beckhoff", library="Tc2_Utilities"):
    """Execution time measurement for PLC cycle profiling.

    Call START_MEASURE() and STOP_MEASURE() methods around the code
    section to profile.  This stub provides only the FB shell — use
    the method-call interface in actual TwinCAT projects.
    """

    bError: Output[BOOL]


# ---------------------------------------------------------------------------
# Function blocks — CSV
# ---------------------------------------------------------------------------

class FB_CSVMemBufferWriter(LibraryFB, vendor="beckhoff", library="Tc2_Utilities"):
    """Write CSV-formatted data to a memory buffer.

    Build CSV content field-by-field with bWrite + sField, then
    finalize each row with bWriteLine.  The accumulated buffer can
    be written to a file via FB_FileWrite.
    """

    bWrite: Input[BOOL]
    sField: Input[str]
    bWriteLine: Input[BOOL]
    bReset: Input[BOOL]

    bOk: Output[BOOL]
    bError: Output[BOOL]
    nErrId: Output[UDINT]
    cbSize: Output[UDINT]
