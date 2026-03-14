"""Tc2_System — Core system and runtime services for TwinCAT 3.

Stubs for the most commonly used function blocks from the Tc2_System
library.  Parameters requiring POINTER_TO are omitted (noted in
docstrings) — they cannot be represented via the annotation-based
stub interface.

Available types:

  Data types:
    T_AmsNetId    — AMS Net ID string alias
    ST_AmsAddr    — AMS address structure

  ADS communication:
    ADSREAD       — Read data from an ADS device
    ADSWRITE      — Write data to an ADS device
    ADSRDWRT      — Combined ADS read/write
    ADSRDSTATE    — Read ADS device state

  File I/O:
    FB_FileOpen   — Open or create a file
    FB_FileClose  — Close an open file
    FB_FileRead   — Read binary data from a file
    FB_FileWrite  — Write binary data to a file
    FB_FileDelete — Delete a file
    FB_FileGets   — Read a text line from a file
    FB_FilePuts   — Write a text line to a file

  System:
    FB_IecCriticalSection — Mutual exclusion for critical sections

Note: do NOT use ``from __future__ import annotations`` in stub files —
annotations must be live objects for interface parsing.
"""

from plx.framework._descriptors import Input, Output
from plx.framework._library import LibraryFB, LibraryStruct
from plx.framework._types import BOOL, DWORD, INT, TIME, UDINT, WORD


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class T_AmsNetId(LibraryStruct, vendor="beckhoff", library="Tc2_System"):
    """AMS Net ID string (e.g., '172.16.2.131.1.1').

    Shallow stub — the real type is STRING(23).
    """

    pass  # STRING(23) alias — fields populated on demand


class ST_AmsAddr(LibraryStruct, vendor="beckhoff", library="Tc2_System"):
    """AMS address structure for ADS communication.

    Contains a Net ID and a port number identifying a target
    ADS device.
    """

    port: WORD


# ---------------------------------------------------------------------------
# ADS communication
# ---------------------------------------------------------------------------

class ADSREAD(LibraryFB, vendor="beckhoff", library="Tc2_System"):
    """Read data from an ADS device.

    Omitted params: DESTADDR (POINTER_TO) — the read buffer address
    must be passed via ADR() in user code.
    """

    NETID: Input[str]
    PORT: Input[WORD]
    IDXGRP: Input[UDINT]
    IDXOFFS: Input[UDINT]
    LEN: Input[UDINT]
    READ: Input[BOOL]
    TMOUT: Input[TIME]
    BUSY: Output[BOOL]
    ERR: Output[BOOL]
    ERRID: Output[UDINT]


class ADSWRITE(LibraryFB, vendor="beckhoff", library="Tc2_System"):
    """Write data to an ADS device.

    Omitted params: SRCADDR (POINTER_TO) — the write buffer address
    must be passed via ADR() in user code.
    """

    NETID: Input[str]
    PORT: Input[WORD]
    IDXGRP: Input[UDINT]
    IDXOFFS: Input[UDINT]
    LEN: Input[UDINT]
    WRITE: Input[BOOL]
    TMOUT: Input[TIME]
    BUSY: Output[BOOL]
    ERR: Output[BOOL]
    ERRID: Output[UDINT]


class ADSRDWRT(LibraryFB, vendor="beckhoff", library="Tc2_System"):
    """Combined ADS read/write in a single transaction.

    Omitted params: DESTADDR, SRCADDR (POINTER_TO) — buffer addresses
    must be passed via ADR() in user code.
    """

    NETID: Input[str]
    PORT: Input[WORD]
    IDXGRP: Input[UDINT]
    IDXOFFS: Input[UDINT]
    WRITELEN: Input[UDINT]
    READLEN: Input[UDINT]
    WRTRD: Input[BOOL]
    TMOUT: Input[TIME]
    BUSY: Output[BOOL]
    ERR: Output[BOOL]
    ERRID: Output[UDINT]


class ADSRDSTATE(LibraryFB, vendor="beckhoff", library="Tc2_System"):
    """Read the ADS state and device state of a remote device.

    Omitted params: DESTADDR (POINTER_TO) — the read buffer address
    must be passed via ADR() in user code.
    """

    NETID: Input[str]
    PORT: Input[WORD]
    LEN: Input[UDINT]
    RDSTATE: Input[BOOL]
    TMOUT: Input[TIME]
    BUSY: Output[BOOL]
    ERR: Output[BOOL]
    ERRID: Output[UDINT]
    ADSSTATE: Output[WORD]
    DEVSTATE: Output[WORD]


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

class FB_FileOpen(LibraryFB, vendor="beckhoff", library="Tc2_System"):
    """Open or create a file on the TwinCAT target.

    nMode flags: FOPEN_MODEREAD (1), FOPEN_MODEWRITE (2),
    FOPEN_MODEAPPEND (4), FOPEN_MODEPLUS (8), FOPEN_MODETEXT (16),
    FOPEN_MODEBINARY (32).
    """

    sNetId: Input[str]
    sPathName: Input[str]
    nMode: Input[DWORD]
    ePath: Input[INT]
    bExecute: Input[BOOL]
    tTimeout: Input[TIME]
    bBusy: Output[BOOL]
    bError: Output[BOOL]
    nErrId: Output[UDINT]
    hFile: Output[UDINT]


class FB_FileClose(LibraryFB, vendor="beckhoff", library="Tc2_System"):
    """Close a previously opened file handle."""

    sNetId: Input[str]
    hFile: Input[UDINT]
    bExecute: Input[BOOL]
    tTimeout: Input[TIME]
    bBusy: Output[BOOL]
    bError: Output[BOOL]
    nErrId: Output[UDINT]


class FB_FileRead(LibraryFB, vendor="beckhoff", library="Tc2_System"):
    """Read binary data from an open file.

    Omitted params: pReadBuff (POINTER_TO) — the read buffer address
    must be passed via ADR() in user code.
    """

    sNetId: Input[str]
    hFile: Input[UDINT]
    cbReadLen: Input[UDINT]
    bExecute: Input[BOOL]
    tTimeout: Input[TIME]
    bBusy: Output[BOOL]
    bError: Output[BOOL]
    nErrId: Output[UDINT]
    cbRead: Output[UDINT]


class FB_FileWrite(LibraryFB, vendor="beckhoff", library="Tc2_System"):
    """Write binary data to an open file.

    Omitted params: pWriteBuff (POINTER_TO) — the write buffer address
    must be passed via ADR() in user code.
    """

    sNetId: Input[str]
    hFile: Input[UDINT]
    cbWriteLen: Input[UDINT]
    bExecute: Input[BOOL]
    tTimeout: Input[TIME]
    bBusy: Output[BOOL]
    bError: Output[BOOL]
    nErrId: Output[UDINT]
    cbWrite: Output[UDINT]


class FB_FileDelete(LibraryFB, vendor="beckhoff", library="Tc2_System"):
    """Delete a file on the TwinCAT target."""

    sNetId: Input[str]
    sPathName: Input[str]
    ePath: Input[INT]
    bExecute: Input[BOOL]
    tTimeout: Input[TIME]
    bBusy: Output[BOOL]
    bError: Output[BOOL]
    nErrId: Output[UDINT]


class FB_FileGets(LibraryFB, vendor="beckhoff", library="Tc2_System"):
    """Read a single text line from an open file.

    Omitted params: pReadBuff (POINTER_TO) — the read buffer address
    must be passed via ADR() in user code.
    """

    sNetId: Input[str]
    hFile: Input[UDINT]
    cbReadLen: Input[UDINT]
    bExecute: Input[BOOL]
    tTimeout: Input[TIME]
    bBusy: Output[BOOL]
    bError: Output[BOOL]
    nErrId: Output[UDINT]
    cbRead: Output[UDINT]
    bEOF: Output[BOOL]


class FB_FilePuts(LibraryFB, vendor="beckhoff", library="Tc2_System"):
    """Write a single text line to an open file.

    Omitted params: pWriteBuff (POINTER_TO) — the write buffer address
    must be passed via ADR() in user code.
    """

    sNetId: Input[str]
    hFile: Input[UDINT]
    cbWriteLen: Input[UDINT]
    bExecute: Input[BOOL]
    tTimeout: Input[TIME]
    bBusy: Output[BOOL]
    bError: Output[BOOL]
    nErrId: Output[UDINT]
    cbWrite: Output[UDINT]


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

class FB_IecCriticalSection(LibraryFB, vendor="beckhoff", library="Tc2_System"):
    """Mutual exclusion for critical sections.

    In user code, call the Enter() and Leave() methods to protect
    shared data. This stub has no I/O parameters.
    """

    pass
