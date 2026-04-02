"""Siemens Modbus communication function blocks.

TIA Portal Modbus TCP and Modbus RTU instructions for S7-1200/S7-1500
fieldbus communication with third-party devices (VFDs, power meters,
remote I/O, sensors).

Available types:

Modbus TCP:
    MB_CLIENT     (Modbus TCP client — master)
    MB_SERVER     (Modbus TCP server — slave)

Modbus RTU (serial):
    MB_COMM_LOAD  (Configure Modbus RTU serial port)
    MB_MASTER     (Modbus RTU master)
    MB_SLAVE      (Modbus RTU slave)

Note: do NOT use ``from __future__ import annotations`` in stub files --
annotations must be live objects for interface parsing.
"""

from plx.framework._descriptors import InOut, Input, Output
from plx.framework._library import LibraryFB
from plx.framework._types import BOOL, DINT, INT, UDINT, UINT, WORD

# ===================================================================
# Modbus TCP
# ===================================================================


class MB_CLIENT(LibraryFB, vendor="siemens", library="siemens_modbus"):
    """Modbus TCP client (master).

    Communicates with a Modbus TCP server device over Ethernet.  Supports
    all standard Modbus function codes for reading/writing coils, discrete
    inputs, holding registers, and input registers.

    MB_MODE selects the Modbus function code:
    - 0: Read — reads MB_DATA_LEN items starting at MB_DATA_ADDR.
    - 1: Write — writes MB_DATA_LEN items starting at MB_DATA_ADDR.
    - 2: Read/Write — simultaneous read and write (FC 23).

    MB_DATA_ADDR: Modbus start address (0-based UDINT).
    MB_DATA_LEN: number of registers or coils to read/write (UINT).
    MB_DATA_PTR: InOut reference to the local data buffer.

    DISCONNECT: TRUE terminates the TCP connection after the transaction.

    The connection parameters (IP address, port 502) are configured in
    the hardware configuration's connection table.

    Typical usage::

        @fb(target=siemens)
        class VFDCommunication:
            modbus: MB_CLIENT
            read_trigger: Input[BOOL]
            comm_done: Output[BOOL]
            comm_error: Output[BOOL]

            def logic(self):
                self.modbus(REQ=self.read_trigger, DISCONNECT=False, MB_MODE=0, MB_DATA_ADDR=40001, MB_DATA_LEN=10)
                self.comm_done = self.modbus.DONE
                self.comm_error = self.modbus.ERROR
    """

    # --- Inputs ---
    REQ: Input[BOOL]
    DISCONNECT: Input[BOOL]
    MB_MODE: Input[INT]
    MB_DATA_ADDR: Input[UDINT]
    MB_DATA_LEN: Input[UINT]

    # --- InOut ---
    CONNECT: InOut[DINT]  # connection description (VARIANT — TCON_IP_v4 etc.)
    MB_DATA_PTR: InOut[DINT]  # data buffer (VARIANT — any data type)

    # --- Outputs ---
    DONE: Output[BOOL]
    BUSY: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]


class MB_SERVER(LibraryFB, vendor="siemens", library="siemens_modbus"):
    """Modbus TCP server (slave).

    Exposes a block of holding registers to remote Modbus TCP clients.
    The S7 CPU acts as a Modbus slave, responding to read/write requests
    from external masters (SCADA, HMI, other PLCs).

    MB_HOLD_REG: InOut reference to the holding register data area.
    The entire data area is accessible to remote Modbus clients.

    DISCONNECT: TRUE closes all active client connections.
    NDR: new data received — TRUE for one scan when a client writes data.
    DR: data read — TRUE for one scan when a client reads data.

    Typical usage::

        @fb(target=siemens)
        class ModbusSlaveHandler:
            server: MB_SERVER
            new_write: Output[BOOL]

            def logic(self):
                self.server(DISCONNECT=False)
                self.new_write = self.server.NDR
    """

    # --- Inputs ---
    DISCONNECT: Input[BOOL]

    # --- InOut ---
    CONNECT: InOut[DINT]  # connection description (VARIANT — TCON_IP_v4 etc.)
    MB_HOLD_REG: InOut[DINT]  # holding register area (VARIANT — any data type)

    # --- Outputs ---
    NDR: Output[BOOL]
    BUSY: Output[BOOL]
    DR: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]


# ===================================================================
# Modbus RTU (serial)
# ===================================================================


class MB_COMM_LOAD(LibraryFB, vendor="siemens", library="siemens_modbus"):
    """Configure Modbus RTU serial port parameters.

    Initializes a CM/CB serial communication module for Modbus RTU
    operation.  Must be called once at startup (or on configuration
    change) before using MB_MASTER or MB_SLAVE on that port.

    REQ: rising edge triggers the configuration.
    PORT: hardware identifier of the serial port (from HW config).
    BAUD: baud rate (e.g., 9600, 19200, 38400, 115200).
    PARITY: 0=none, 1=odd, 2=even.
    RESP_TO: response timeout in milliseconds.

    Typical usage::

        @fb(target=siemens)
        class SerialConfig:
            comm_load: MB_COMM_LOAD
            init_req: Input[BOOL]
            init_done: Output[BOOL]

            def logic(self):
                self.comm_load(REQ=self.init_req, PORT=1, BAUD=9600, PARITY=2, RESP_TO=1000)
                self.init_done = self.comm_load.DONE
    """

    # --- Inputs ---
    REQ: Input[BOOL]
    PORT: Input[UINT]
    BAUD: Input[UDINT]
    PARITY: Input[UINT]
    RESP_TO: Input[UINT]
    FLOW_CTRL: Input[UINT]
    RTS_ON_DLY: Input[UINT]
    RTS_OFF_DLY: Input[UINT]

    # --- Outputs ---
    DONE: Output[BOOL]
    BUSY: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]


class MB_MASTER(LibraryFB, vendor="siemens", library="siemens_modbus"):
    """Modbus RTU master.

    Communicates with Modbus RTU slave devices over a serial port
    configured by MB_COMM_LOAD.  Supports standard Modbus function
    codes for reading/writing coils and registers.

    REQ: rising edge triggers the Modbus transaction.
    MB_ADDR: Modbus slave address (1-247).
    MODE: 0=read, 1=write, 2=read/write.
    DATA_ADDR: Modbus start address (UDINT).
    DATA_LEN: number of registers or coils (UINT).
    DATA_PTR: InOut reference to the local data buffer.

    Typical usage::

        @fb(target=siemens)
        class SerialModbus:
            master: MB_MASTER
            poll_trigger: Input[BOOL]
            poll_done: Output[BOOL]

            def logic(self):
                self.master(REQ=self.poll_trigger, MB_ADDR=1, MODE=0, DATA_ADDR=40001, DATA_LEN=10)
                self.poll_done = self.master.DONE
    """

    # --- Inputs ---
    REQ: Input[BOOL]
    MB_ADDR: Input[UINT]
    MODE: Input[INT]
    DATA_ADDR: Input[UDINT]
    DATA_LEN: Input[UINT]

    # --- InOut ---
    DATA_PTR: InOut[DINT]

    # --- Outputs ---
    DONE: Output[BOOL]
    BUSY: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]


class MB_SLAVE(LibraryFB, vendor="siemens", library="siemens_modbus"):
    """Modbus RTU slave.

    Exposes a block of holding registers to a remote Modbus RTU master
    over a serial port configured by MB_COMM_LOAD.  The S7 CPU acts
    as a Modbus slave, responding to read/write requests.

    MB_HOLD_REG: InOut reference to the holding register data area.
    NDR: new data received — TRUE for one scan when the master writes.
    DR: data read — TRUE for one scan when the master reads.

    Typical usage::

        @fb(target=siemens)
        class SerialSlave:
            slave: MB_SLAVE
            new_data: Output[BOOL]

            def logic(self):
                self.slave()
                self.new_data = self.slave.NDR
    """

    # --- Inputs ---
    MB_ADDR: Input[UINT]  # Modbus slave station address (1-247)

    # --- InOut ---
    MB_HOLD_REG: InOut[DINT]  # holding register area (VARIANT — any data type)

    # --- Outputs ---
    NDR: Output[BOOL]
    BUSY: Output[BOOL]
    DR: Output[BOOL]
    ERROR: Output[BOOL]
    STATUS: Output[WORD]
