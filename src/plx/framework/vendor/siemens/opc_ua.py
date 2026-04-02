"""Siemens OPC UA client function blocks.

TIA Portal OPC UA client instructions for S7-1500.  These FBs allow
the S7-1500 CPU to act as an OPC UA client, connecting to external
OPC UA servers to read, write, and call methods on remote nodes.

Available types:

OPC UA Client:
    OPC_UA_Connect     (Establish OPC UA client connection)
    OPC_UA_Disconnect  (Disconnect from OPC UA server)
    OPC_UA_ReadList    (Read values from OPC UA nodes)
    OPC_UA_WriteList   (Write values to OPC UA nodes)
    OPC_UA_MethodCall  (Call an OPC UA method on a remote server)

Note: do NOT use ``from __future__ import annotations`` in stub files --
annotations must be live objects for interface parsing.
"""

from plx.framework._descriptors import InOut, Input, Output
from plx.framework._library import LibraryFB
from plx.framework._types import BOOL, DINT, DWORD, TIME

# ===================================================================
# OPC UA Client
# ===================================================================


class OPC_UA_Connect(LibraryFB, vendor="siemens", library="siemens_opc_ua"):
    """Establish an OPC UA client connection to a remote server.

    Connects to an OPC UA server at the specified endpoint URL.
    The connection handle (ConnectionHdl) returned on success is used
    by subsequent OPC_UA_ReadList, OPC_UA_WriteList, and
    OPC_UA_MethodCall operations.

    Execute: rising edge initiates the connection attempt.
    ServerEndpointURL: the OPC UA server endpoint (e.g.,
    "opc.tcp://192.168.1.100:4840").

    Security settings (certificate, authentication) are configured
    in the TIA Portal CPU properties, not via FB parameters.

    Typical usage::

        @fb(target=siemens)
        class OpcUaClient:
            connect: OPC_UA_Connect
            connect_req: Input[BOOL]
            connection_handle: Output[UDINT]
            connected: Output[BOOL]

            def logic(self):
                self.connect(Execute=self.connect_req, ServerEndpointURL="opc.tcp://192.168.1.100:4840")
                self.connected = self.connect.Done
                self.connection_handle = self.connect.ConnectionHdl
    """

    # --- Inputs ---
    Execute: Input[BOOL]
    ServerEndpointURL: Input[str]

    # --- Outputs ---
    Done: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[DWORD]
    ConnectionHdl: Output[DWORD]


class OPC_UA_Disconnect(LibraryFB, vendor="siemens", library="siemens_opc_ua"):
    """Disconnect from an OPC UA server.

    Closes a connection previously established by OPC_UA_Connect.

    Execute: rising edge initiates the disconnection.
    ConnectionHdl: handle of the connection to close.

    Typical usage::

        @fb(target=siemens)
        class OpcUaDisconnect:
            disconnect: OPC_UA_Disconnect
            disconnect_req: Input[BOOL]
            connection_handle: Input[UDINT]
            disconnected: Output[BOOL]

            def logic(self):
                self.disconnect(Execute=self.disconnect_req, ConnectionHdl=self.connection_handle)
                self.disconnected = self.disconnect.Done
    """

    # --- Inputs ---
    Execute: Input[BOOL]
    ConnectionHdl: Input[DWORD]

    # --- Outputs ---
    Done: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[DWORD]


class OPC_UA_ReadList(LibraryFB, vendor="siemens", library="siemens_opc_ua"):
    """Read values from one or more OPC UA nodes.

    Reads the current values of OPC UA nodes on the connected server.
    The node identifiers and data mapping are configured in the TIA
    Portal OPC UA client interface.

    Execute: rising edge triggers the read.
    ConnectionHdl: active connection handle from OPC_UA_Connect.
    Timeout: maximum time to wait for the read to complete.
    NodeHdls: array of node handles identifying which nodes to read.
    Variables: destination area where read values are stored.
    NodeErrorIDs: per-node error codes.

    Typical usage::

        @fb(target=siemens)
        class OpcUaReader:
            reader: OPC_UA_ReadList
            connection_handle: Input[DWORD]
            read_trigger: Input[BOOL]
            read_done: Output[BOOL]

            def logic(self):
                self.reader(Execute=self.read_trigger, ConnectionHdl=self.connection_handle)
                self.read_done = self.reader.Done
    """

    # --- Inputs ---
    Execute: Input[BOOL]
    ConnectionHdl: Input[DWORD]
    Timeout: Input[TIME]

    # --- InOut ---
    NodeHdls: InOut[DINT]
    Variables: InOut[DINT]
    NodeErrorIDs: InOut[DWORD]

    # --- Outputs ---
    Done: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[DWORD]


class OPC_UA_WriteList(LibraryFB, vendor="siemens", library="siemens_opc_ua"):
    """Write values to one or more OPC UA nodes.

    Writes values to OPC UA nodes on the connected server.  The node
    identifiers and data mapping are configured in the TIA Portal OPC
    UA client interface.

    Execute: rising edge triggers the write.
    ConnectionHdl: active connection handle from OPC_UA_Connect.
    Timeout: maximum time to wait for the write to complete.
    NodeHdls: array of node handles identifying which nodes to write.
    Variables: source area containing values to write.
    NodeErrorIDs: per-node error codes.

    Typical usage::

        @fb(target=siemens)
        class OpcUaWriter:
            writer: OPC_UA_WriteList
            connection_handle: Input[DWORD]
            write_trigger: Input[BOOL]
            write_done: Output[BOOL]

            def logic(self):
                self.writer(Execute=self.write_trigger, ConnectionHdl=self.connection_handle)
                self.write_done = self.writer.Done
    """

    # --- Inputs ---
    Execute: Input[BOOL]
    ConnectionHdl: Input[DWORD]
    Timeout: Input[TIME]

    # --- InOut ---
    NodeHdls: InOut[DINT]
    Variables: InOut[DINT]
    NodeErrorIDs: InOut[DWORD]

    # --- Outputs ---
    Done: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[DWORD]


class OPC_UA_MethodCall(LibraryFB, vendor="siemens", library="siemens_opc_ua"):
    """Call an OPC UA method on a remote server.

    Invokes a method exposed by an OPC UA server node.  The method
    parameters and return values are configured in the TIA Portal
    OPC UA client interface.

    Execute: rising edge triggers the method call.
    ConnectionHdl: active connection handle from OPC_UA_Connect.
    MethodHdl: handle identifying the method to call.
    Timeout: maximum time to wait for the method to complete.
    InputArguments: InOut reference to the input argument data.
    OutputArguments: InOut reference to the output argument data.
    MethodResult: method-specific result status.

    Typical usage::

        @fb(target=siemens)
        class OpcUaMethodCaller:
            method_call: OPC_UA_MethodCall
            connection_handle: Input[DWORD]
            call_trigger: Input[BOOL]
            call_done: Output[BOOL]

            def logic(self):
                self.method_call(Execute=self.call_trigger, ConnectionHdl=self.connection_handle)
                self.call_done = self.method_call.Done
    """

    # --- Inputs ---
    Execute: Input[BOOL]
    ConnectionHdl: Input[DWORD]
    MethodHdl: Input[DWORD]
    Timeout: Input[TIME]

    # --- InOut ---
    InputArguments: InOut[DINT]
    OutputArguments: InOut[DINT]

    # --- Outputs ---
    Done: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[DWORD]
    MethodResult: Output[DWORD]
