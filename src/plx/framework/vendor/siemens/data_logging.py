"""Siemens data logging function blocks.

TIA Portal data logging instructions for S7-1200/S7-1500.  These FBs
manage CSV-format data logs stored on the CPU's memory card, used for
production data recording, trend logging, and batch reporting.

Available types:

Data Logging:
    DataLogCreate  (Create a new data log)
    DataLogOpen    (Open an existing data log)
    DataLogWrite   (Write a record to a data log)
    DataLogClose   (Close a data log)
    DataLogDelete  (Delete a data log)
    DataLogClear   (Clear all records from a data log)

Note: do NOT use ``from __future__ import annotations`` in stub files --
annotations must be live objects for interface parsing.
"""

from plx.framework._descriptors import InOut, Input, Output
from plx.framework._library import LibraryFB
from plx.framework._types import BOOL, DINT, UDINT, WORD

# ===================================================================
# Data Logging
# ===================================================================


class DataLogCreate(LibraryFB, vendor="siemens", library="siemens_data_logging"):
    """Create a new data log on the CPU memory card.

    Creates a CSV-format data log file with a specified maximum number
    of records.  Once the log reaches RECORDS entries, the oldest record
    is overwritten (circular buffer behavior).

    REQ: rising edge triggers log creation.
    RECORDS: maximum number of records (rows) the log can hold.
    NAME: filename for the data log (STRING, e.g., "ProductionLog").
    ID: handle returned on success — used by DataLogWrite/Close/Delete.

    The data log columns are defined by the data type of the record
    buffer passed to DataLogWrite.

    Typical usage::

        @fb(target=siemens)
        class LogSetup:
            create_log: DataLogCreate
            init_req: Input[BOOL]
            log_id: Output[UDINT]
            log_ready: Output[BOOL]

            def logic(self):
                self.create_log(REQ=self.init_req, RECORDS=10000, NAME="ProductionLog")
                self.log_ready = self.create_log.DONE
                self.log_id = self.create_log.ID
    """

    # --- Inputs ---
    REQ: Input[BOOL]
    RECORDS: Input[UDINT]
    NAME: Input[str]

    # --- InOut ---
    DATA: InOut[DINT]
    HEADER: InOut[DINT]

    # --- Outputs ---
    DONE: Output[BOOL]
    BUSY: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]
    ID: Output[UDINT]


class DataLogOpen(LibraryFB, vendor="siemens", library="siemens_data_logging"):
    """Open an existing data log on the CPU memory card.

    Opens a previously created data log by name or ID for writing
    additional records.  Use this after a CPU restart to resume logging
    to an existing file.

    REQ: rising edge triggers the open operation.
    NAME: filename of the data log to open.
    ID: if non-zero, opens by ID instead of by name.

    Typical usage::

        @fb(target=siemens)
        class LogOpen:
            open_log: DataLogOpen
            open_req: Input[BOOL]
            opened: Output[BOOL]

            def logic(self):
                self.open_log(REQ=self.open_req, NAME="ProductionLog", ID=0)
                self.opened = self.open_log.DONE
    """

    # --- Inputs ---
    REQ: Input[BOOL]
    NAME: Input[str]
    ID: Input[UDINT]

    # --- Outputs ---
    DONE: Output[BOOL]
    BUSY: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]


class DataLogWrite(LibraryFB, vendor="siemens", library="siemens_data_logging"):
    """Write a record to an open data log.

    Appends one record (row) to the data log identified by ID.  The
    record data comes from a data block structure that defines the
    columns.

    REQ: rising edge triggers the write.
    ID: data log handle (from DataLogCreate or DataLogOpen).

    Typical usage::

        @fb(target=siemens)
        class LogWriter:
            write_log: DataLogWrite
            log_id: Input[UDINT]
            write_trigger: Input[BOOL]
            write_done: Output[BOOL]

            def logic(self):
                self.write_log(REQ=self.write_trigger, ID=self.log_id)
                self.write_done = self.write_log.DONE
    """

    # --- Inputs ---
    REQ: Input[BOOL]
    ID: Input[UDINT]

    # --- Outputs ---
    DONE: Output[BOOL]
    BUSY: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]


class DataLogClose(LibraryFB, vendor="siemens", library="siemens_data_logging"):
    """Close an open data log.

    Flushes any buffered data and closes the data log file.  The log
    can be reopened later with DataLogOpen.

    REQ: rising edge triggers the close.
    ID: data log handle to close.

    Typical usage::

        @fb(target=siemens)
        class LogClose:
            close_log: DataLogClose
            log_id: Input[UDINT]
            close_req: Input[BOOL]
            closed: Output[BOOL]

            def logic(self):
                self.close_log(REQ=self.close_req, ID=self.log_id)
                self.closed = self.close_log.DONE
    """

    # --- Inputs ---
    REQ: Input[BOOL]
    ID: Input[UDINT]

    # --- Outputs ---
    DONE: Output[BOOL]
    BUSY: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]


class DataLogDelete(LibraryFB, vendor="siemens", library="siemens_data_logging"):
    """Delete a data log from the CPU memory card.

    Permanently removes the data log file.  The log must be closed
    before deletion.

    REQ: rising edge triggers the delete.
    NAME: filename of the data log to delete.

    Typical usage::

        @fb(target=siemens)
        class LogDelete:
            delete_log: DataLogDelete
            delete_req: Input[BOOL]
            deleted: Output[BOOL]

            def logic(self):
                self.delete_log(REQ=self.delete_req, NAME="OldLog")
                self.deleted = self.delete_log.DONE
    """

    # --- Inputs ---
    REQ: Input[BOOL]
    NAME: Input[str]

    # --- Outputs ---
    DONE: Output[BOOL]
    BUSY: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]


class DataLogClear(LibraryFB, vendor="siemens", library="siemens_data_logging"):
    """Clear all records from a data log.

    Removes all recorded data from the log while keeping the log file
    and its configuration intact.  The log must be open.

    REQ: rising edge triggers the clear.
    ID: data log handle to clear.

    Typical usage::

        @fb(target=siemens)
        class LogClear:
            clear_log: DataLogClear
            log_id: Input[UDINT]
            clear_req: Input[BOOL]
            cleared: Output[BOOL]

            def logic(self):
                self.clear_log(REQ=self.clear_req, ID=self.log_id)
                self.cleared = self.clear_log.DONE
    """

    # --- Inputs ---
    REQ: Input[BOOL]
    ID: Input[UDINT]

    # --- Outputs ---
    DONE: Output[BOOL]
    BUSY: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]
