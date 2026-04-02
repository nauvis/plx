"""Siemens TIA Portal library stubs.

Stubs are organized by TIA Portal library / instruction category:

- ``pid``: Technology Object PID controllers (PID_Compact, PID_3Step, PID_Temp)
- ``communication``: TCP/IP and S7 communication (TSEND_C, TRCV_C, PUT, GET, ...)
- ``modbus``: Modbus TCP and RTU (MB_CLIENT, MB_SERVER, MB_MASTER, MB_SLAVE, ...)
- ``motion``: S7-1500T motion control (MC_Power, MC_MoveAbsolute, MC_GearIn, ...)
- ``alarms``: Program alarms (Program_Alarm)
- ``data_handling``: Scaling and serialization (NORM_X, SCALE_X, Serialize, Deserialize)
- ``data_logging``: Data log management (DataLogCreate, DataLogWrite, ...)
- ``opc_ua``: OPC UA client (OPC_UA_Connect, OPC_UA_ReadList, ...)
- ``timers``: Extended timers (TONR)
"""

from .alarms import (
    Program_Alarm,
)
from .communication import (
    GET,
    # S7 Communication
    PUT,
    # TCP Connection Management
    TCON,
    TDISCON,
    TRCV,
    TRCV_C,
    # TCP Data Transfer
    TSEND,
    # Compact TCP
    TSEND_C,
)
from .data_handling import (
    # Scaling
    NORM_X,
    SCALE_X,
    Deserialize,
    # Serialization
    Serialize,
)
from .data_logging import (
    DataLogClear,
    DataLogClose,
    DataLogCreate,
    DataLogDelete,
    DataLogOpen,
    DataLogWrite,
)
from .modbus import (
    # Modbus TCP
    MB_CLIENT,
    # Modbus RTU
    MB_COMM_LOAD,
    MB_MASTER,
    MB_SERVER,
    MB_SLAVE,
)
from .motion import (
    # Coupling
    MC_GearIn,
    MC_GearOut,
    # Motion Commands
    MC_Halt,
    MC_Home,
    MC_MoveAbsolute,
    MC_MoveJog,
    MC_MoveRelative,
    MC_MoveVelocity,
    # Axis Administration
    MC_Power,
    MC_Reset,
    MC_Stop,
    TO_PositioningAxis,
    # Structs
    TO_SpeedAxis,
)
from .opc_ua import (
    OPC_UA_Connect,
    OPC_UA_Disconnect,
    OPC_UA_MethodCall,
    OPC_UA_ReadList,
    OPC_UA_WriteList,
)
from .pid import (
    PID_3Step,
    PID_Compact,
    PID_Temp,
)
from .timers import (
    TONR,
)

__all__ = [
    # PID
    "PID_Compact",
    "PID_3Step",
    "PID_Temp",
    # Communication — Compact TCP
    "TSEND_C",
    "TRCV_C",
    # Communication — TCP Connection Management
    "TCON",
    "TDISCON",
    # Communication — TCP Data Transfer
    "TSEND",
    "TRCV",
    # Communication — S7
    "PUT",
    "GET",
    # Modbus — TCP
    "MB_CLIENT",
    "MB_SERVER",
    # Modbus — RTU
    "MB_COMM_LOAD",
    "MB_MASTER",
    "MB_SLAVE",
    # Motion — Structs
    "TO_SpeedAxis",
    "TO_PositioningAxis",
    # Motion — Axis Administration
    "MC_Power",
    "MC_Reset",
    "MC_Home",
    # Motion — Commands
    "MC_Halt",
    "MC_MoveAbsolute",
    "MC_MoveRelative",
    "MC_MoveVelocity",
    "MC_MoveJog",
    "MC_Stop",
    # Motion — Coupling
    "MC_GearIn",
    "MC_GearOut",
    # Alarms
    "Program_Alarm",
    # Data Handling — Scaling
    "NORM_X",
    "SCALE_X",
    # Data Handling — Serialization
    "Serialize",
    "Deserialize",
    # Data Logging
    "DataLogCreate",
    "DataLogOpen",
    "DataLogWrite",
    "DataLogClose",
    "DataLogDelete",
    "DataLogClear",
    # OPC UA
    "OPC_UA_Connect",
    "OPC_UA_Disconnect",
    "OPC_UA_ReadList",
    "OPC_UA_WriteList",
    "OPC_UA_MethodCall",
    # Timers
    "TONR",
]
