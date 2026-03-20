"""Siemens communication function blocks.

TIA Portal communication instructions for S7-1200/S7-1500 TCP/IP
networking and S7 inter-CPU data exchange.

Available types:

Compact TCP:
    TSEND_C  (Compact TCP send — connection + send in one FB)
    TRCV_C   (Compact TCP receive — connection + receive in one FB)

TCP Connection Management:
    TCON     (Establish TCP connection)
    TDISCON  (Terminate TCP connection)

TCP Data Transfer:
    TSEND    (Send data over established connection)
    TRCV     (Receive data over established connection)

S7 Communication:
    PUT      (Write data to remote S7 CPU)
    GET      (Read data from remote S7 CPU)

Note: do NOT use ``from __future__ import annotations`` in stub files --
annotations must be live objects for interface parsing.
"""

from plx.framework._descriptors import InOut, Input, Output
from plx.framework._library import LibraryFB
from plx.framework._types import BOOL, DINT, UDINT, WORD


# ===================================================================
# Compact TCP (connection + data transfer in one FB)
# ===================================================================

class TSEND_C(LibraryFB, vendor="siemens", library="siemens_communication"):
    """Compact TCP send — establishes connection and sends data.

    Combines TCON + TSEND into a single function block for simplified
    TCP client communication.  The connection is established automatically
    on the first REQ and maintained while CONT=TRUE.

    REQ: rising edge triggers a send operation.
    CONT: TRUE = maintain connection between sends; FALSE = disconnect
    after each send.
    LEN: number of bytes to send from the DATA area.
    CONNECT: InOut connection description structure for programmed
    connections (TCON_IP_v4 or similar).
    COM_RST: InOut BOOL — rising edge restarts the connection.
    DATA: InOut reference to the send buffer (any data type).

    The connection parameters (IP address, port) are configured via the
    CONNECT parameter for programmed connections or in the TIA Portal
    connection table for configured connections.

    Typical usage::

        @fb(target=siemens)
        class TcpSender:
            sender: TSEND_C
            send_trigger: Input[BOOL]
            send_done: Output[BOOL]

            def logic(self):
                self.sender(REQ=self.send_trigger, CONT=True, LEN=100)
                self.send_done = self.sender.DONE
    """

    # --- Inputs ---
    REQ: Input[BOOL]
    CONT: Input[BOOL]
    LEN: Input[UDINT]

    # --- InOut ---
    CONNECT: InOut[DINT]  # connection description (VARIANT — TCON_IP_v4 etc.)
    COM_RST: InOut[BOOL]  # rising edge restarts connection
    DATA: InOut[DINT]  # send buffer (VARIANT — any data type)

    # --- Outputs ---
    DONE: Output[BOOL]
    BUSY: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]


class TRCV_C(LibraryFB, vendor="siemens", library="siemens_communication"):
    """Compact TCP receive — establishes connection and receives data.

    Combines TCON + TRCV into a single function block for simplified
    TCP server or client receive communication.  The connection is
    maintained while CONT=TRUE.

    EN_R: TRUE = receive is enabled and listening for incoming data.
    CONT: TRUE = maintain connection; FALSE = disconnect after receive.
    LEN: maximum number of bytes to receive.
    CONNECT: InOut connection description structure for programmed
    connections (TCON_IP_v4 or similar).
    COM_RST: InOut BOOL — rising edge restarts the connection.
    DATA: InOut reference to the receive buffer.
    RCVD_LEN: actual number of bytes received in the last transaction.

    Typical usage::

        @fb(target=siemens)
        class TcpReceiver:
            receiver: TRCV_C
            data_ready: Output[BOOL]
            bytes_received: Output[UDINT]

            def logic(self):
                self.receiver(EN_R=True, CONT=True, LEN=256)
                self.data_ready = self.receiver.DONE
                self.bytes_received = self.receiver.RCVD_LEN
    """

    # --- Inputs ---
    EN_R: Input[BOOL]
    CONT: Input[BOOL]
    LEN: Input[UDINT]

    # --- InOut ---
    CONNECT: InOut[DINT]  # connection description (VARIANT — TCON_IP_v4 etc.)
    COM_RST: InOut[BOOL]  # rising edge restarts connection
    DATA: InOut[DINT]  # receive buffer (VARIANT — any data type)

    # --- Outputs ---
    DONE: Output[BOOL]
    BUSY: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]
    RCVD_LEN: Output[UDINT]


# ===================================================================
# TCP Connection Management
# ===================================================================

class TCON(LibraryFB, vendor="siemens", library="siemens_communication"):
    """Establish a TCP connection.

    Creates a TCP connection to a remote partner using connection
    parameters configured in the TIA Portal connection table.  The
    connection ID links to the hardware configuration entry.

    REQ: rising edge initiates the connection attempt.
    ID: connection identifier from the connection table (WORD).

    Use TCON when you need separate connection management from data
    transfer (paired with TSEND/TRCV).  For simpler cases, use
    TSEND_C/TRCV_C which handle connection automatically.

    Typical usage::

        @fb(target=siemens)
        class ConnectionManager:
            connector: TCON
            connect_req: Input[BOOL]
            connected: Output[BOOL]

            def logic(self):
                self.connector(REQ=self.connect_req, ID=1)
                self.connected = self.connector.DONE
    """

    # --- Inputs ---
    REQ: Input[BOOL]
    ID: Input[WORD]

    # --- InOut ---
    CONNECT: InOut[DINT]  # connection description (VARIANT — TCON_IP_v4 etc.)

    # --- Outputs ---
    DONE: Output[BOOL]
    BUSY: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]


class TDISCON(LibraryFB, vendor="siemens", library="siemens_communication"):
    """Terminate a TCP connection.

    Closes a connection previously established by TCON.  The connection
    ID must match the one used in the corresponding TCON call.

    REQ: rising edge initiates disconnection.
    ID: connection identifier to disconnect.

    Typical usage::

        @fb(target=siemens)
        class ConnectionManager:
            disconnector: TDISCON
            disconnect_req: Input[BOOL]
            disconnected: Output[BOOL]

            def logic(self):
                self.disconnector(REQ=self.disconnect_req, ID=1)
                self.disconnected = self.disconnector.DONE
    """

    # --- Inputs ---
    REQ: Input[BOOL]
    ID: Input[WORD]

    # --- Outputs ---
    DONE: Output[BOOL]
    BUSY: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]


# ===================================================================
# TCP Data Transfer
# ===================================================================

class TSEND(LibraryFB, vendor="siemens", library="siemens_communication"):
    """Send data over an established TCP connection.

    Requires an active connection established by TCON.  Sends LEN bytes
    from the send buffer.

    REQ: rising edge triggers the send.
    ID: connection identifier (must match an active TCON connection).
    LEN: number of bytes to send.

    Typical usage::

        @fb(target=siemens)
        class DataSender:
            sender: TSEND
            send_trigger: Input[BOOL]
            send_done: Output[BOOL]

            def logic(self):
                self.sender(REQ=self.send_trigger, ID=1, LEN=50)
                self.send_done = self.sender.DONE
    """

    # --- Inputs ---
    REQ: Input[BOOL]
    ID: Input[WORD]
    LEN: Input[UDINT]

    # --- InOut ---
    DATA: InOut[DINT]  # send buffer (VARIANT — any data type)

    # --- Outputs ---
    DONE: Output[BOOL]
    BUSY: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]


class TRCV(LibraryFB, vendor="siemens", library="siemens_communication"):
    """Receive data over an established TCP connection.

    Requires an active connection established by TCON.  Receives up to
    LEN bytes into the receive buffer.

    EN_R: TRUE = receive is enabled and listening.
    ID: connection identifier (must match an active TCON connection).
    LEN: maximum number of bytes to receive.
    RCVD_LEN: actual number of bytes received.

    Typical usage::

        @fb(target=siemens)
        class DataReceiver:
            receiver: TRCV
            data_ready: Output[BOOL]
            bytes_received: Output[UDINT]

            def logic(self):
                self.receiver(EN_R=True, ID=1, LEN=256)
                self.data_ready = self.receiver.DONE
                self.bytes_received = self.receiver.RCVD_LEN
    """

    # --- Inputs ---
    EN_R: Input[BOOL]
    ID: Input[WORD]
    LEN: Input[UDINT]

    # --- InOut ---
    DATA: InOut[DINT]  # receive buffer (VARIANT — any data type)

    # --- Outputs ---
    DONE: Output[BOOL]
    BUSY: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]
    RCVD_LEN: Output[UDINT]


# ===================================================================
# S7 Communication (PUT/GET)
# ===================================================================

class PUT(LibraryFB, vendor="siemens", library="siemens_communication"):
    """Write data to a remote S7 CPU via S7 communication.

    Sends data from the local CPU to a data block on a remote S7 CPU.
    Uses S7 communication protocol over PROFINET or Industrial Ethernet.
    The remote CPU must have PUT/GET access enabled in its protection
    settings.

    REQ: rising edge triggers the write operation.
    ID: connection identifier configured in hardware configuration.
    ADDR_1: start address in the remote DB (byte offset as DINT).
    SD_1: InOut reference to the local send data.

    Note: PUT/GET is considered less secure than other communication
    methods because it bypasses the remote CPU's program logic.  Use
    TSEND_C/TRCV_C for new projects where possible.

    Typical usage::

        @fb(target=siemens)
        class RemoteWriter:
            writer: PUT
            write_trigger: Input[BOOL]
            write_done: Output[BOOL]

            def logic(self):
                self.writer(REQ=self.write_trigger, ID=1, ADDR_1=0)
                self.write_done = self.writer.DONE
    """

    # --- Inputs ---
    REQ: Input[BOOL]
    ID: Input[WORD]

    # --- InOut ---
    ADDR_1: InOut[DINT]  # remote area pointer (VARIANT — ANY_POINTER)
    SD_1: InOut[DINT]  # send data area 1 (VARIANT — any data type)
    ADDR_2: InOut[DINT]  # remote area pointer 2 (VARIANT — ANY_POINTER)
    SD_2: InOut[DINT]  # send data area 2 (VARIANT — any data type)

    # --- Outputs ---
    DONE: Output[BOOL]
    BUSY: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]


class GET(LibraryFB, vendor="siemens", library="siemens_communication"):
    """Read data from a remote S7 CPU via S7 communication.

    Reads data from a data block on a remote S7 CPU into a local buffer.
    Uses S7 communication protocol over PROFINET or Industrial Ethernet.
    The remote CPU must have PUT/GET access enabled in its protection
    settings.

    REQ: rising edge triggers the read operation.
    ID: connection identifier configured in hardware configuration.
    ADDR_1: start address in the remote DB (byte offset as DINT).
    RD_1: InOut reference to the local receive buffer.
    NDR: new data received — TRUE for one scan when fresh data arrives.

    Typical usage::

        @fb(target=siemens)
        class RemoteReader:
            reader: GET
            read_trigger: Input[BOOL]
            new_data: Output[BOOL]

            def logic(self):
                self.reader(REQ=self.read_trigger, ID=1, ADDR_1=0)
                self.new_data = self.reader.NDR
    """

    # --- Inputs ---
    REQ: Input[BOOL]
    ID: Input[WORD]

    # --- InOut ---
    ADDR_1: InOut[DINT]  # remote area pointer (VARIANT — ANY_POINTER)
    RD_1: InOut[DINT]  # receive data area 1 (VARIANT — any data type)
    ADDR_2: InOut[DINT]  # remote area pointer 2 (VARIANT — ANY_POINTER)
    RD_2: InOut[DINT]  # receive data area 2 (VARIANT — any data type)

    # --- Outputs ---
    DONE: Output[BOOL]
    BUSY: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]
    NDR: Output[BOOL]
