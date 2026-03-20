"""OPC-UA server for the plx runtime.

Uses the asyncua library to expose PLC variables as OPC-UA nodes.
Gracefully degrades if asyncua is not installed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from plx.model.project import Project
from plx.model.types import PrimitiveTypeRef

from ._engine import RuntimeEngine

logger = logging.getLogger("plx.runtime")

try:
    from asyncua import Server, ua

    _HAS_ASYNCUA = True
except ImportError:
    _HAS_ASYNCUA = False


# Type mapping: IEC 61131-3 primitive → OPC-UA VariantType
_TYPE_MAP: dict[str, Any] = {}
if _HAS_ASYNCUA:
    _TYPE_MAP = {
        "BOOL": ua.VariantType.Boolean,
        "SINT": ua.VariantType.SByte,
        "INT": ua.VariantType.Int16,
        "DINT": ua.VariantType.Int32,
        "LINT": ua.VariantType.Int64,
        "USINT": ua.VariantType.Byte,
        "UINT": ua.VariantType.UInt16,
        "UDINT": ua.VariantType.UInt32,
        "ULINT": ua.VariantType.UInt64,
        "REAL": ua.VariantType.Float,
        "LREAL": ua.VariantType.Double,
        "STRING": ua.VariantType.String,
        "WSTRING": ua.VariantType.String,
        "BYTE": ua.VariantType.Byte,
        "WORD": ua.VariantType.UInt16,
        "DWORD": ua.VariantType.UInt32,
        "LWORD": ua.VariantType.UInt64,
        "TIME": ua.VariantType.String,
        "DATE": ua.VariantType.String,
        "TOD": ua.VariantType.String,
        "DT": ua.VariantType.String,
    }


def _python_value_to_variant_type(value: object) -> Any:
    """Infer OPC-UA variant type from a Python value."""
    if not _HAS_ASYNCUA:
        return None
    if isinstance(value, bool):
        return ua.VariantType.Boolean
    if isinstance(value, int):
        return ua.VariantType.Int32
    if isinstance(value, float):
        return ua.VariantType.Float
    if isinstance(value, str):
        return ua.VariantType.String
    return None


class OPCUAServer:
    """OPC-UA server exposing PLC variables.

    Address space layout:
        Objects/plx/Programs/<ProgramName>/<var>
        Objects/plx/GVLs/<GVLName>/<var>
    """

    def __init__(
        self,
        engine: RuntimeEngine,
        *,
        port: int = 4840,
        endpoint: str | None = None,
    ) -> None:
        if not _HAS_ASYNCUA:
            raise RuntimeError(
                "asyncua is not installed. "
                "Install with: pip install plx-controls[runtime]"
            )

        self._engine = engine
        self._port = port
        self._endpoint = endpoint or f"opc.tcp://0.0.0.0:{port}"
        self._server: Server | None = None
        self._sync_task: asyncio.Task | None = None
        self._write_task: asyncio.Task | None = None
        # Maps "scope.var_name" → OPC-UA node for value sync
        self._nodes: dict[str, Any] = {}

    @property
    def endpoint(self) -> str:
        return self._endpoint

    async def start(self) -> None:
        """Initialize and start the OPC-UA server."""
        server = Server()
        await server.init()
        server.set_endpoint(self._endpoint)
        server.set_server_name(f"plx Runtime - {self._engine.project_name}")

        # Create namespace
        uri = "urn:plx:runtime"
        idx = await server.register_namespace(uri)

        # Create top-level folder
        plx_folder = await server.nodes.objects.add_folder(idx, "plx")

        # Create Programs folder
        programs_folder = await plx_folder.add_folder(idx, "Programs")
        for prog_name, ctx in self._engine._sim._programs.items():
            prog_folder = await programs_folder.add_folder(idx, prog_name)
            await self._add_state_variables(
                idx, prog_folder, ctx._state, ctx._known_vars, f"{prog_name}",
            )

        # Create GVLs folder
        gvls_folder = await plx_folder.add_folder(idx, "GVLs")
        for gvl_name, gvl_state in self._engine._sim._global_state.items():
            gvl_folder = await gvls_folder.add_folder(idx, gvl_name)
            await self._add_state_variables(
                idx, gvl_folder, gvl_state, set(gvl_state.keys()), f"GVLs.{gvl_name}",
            )

        self._server = server
        await server.start()
        logger.info("OPC-UA server started at %s", self._endpoint)

        # Start value sync task
        self._sync_task = asyncio.create_task(self._sync_loop())
        # Start write monitoring task
        self._write_task = asyncio.create_task(self._write_monitor_loop())

    async def stop(self) -> None:
        if self._sync_task is not None:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        if self._write_task is not None:
            self._write_task.cancel()
            try:
                await self._write_task
            except asyncio.CancelledError:
                pass
        if self._server is not None:
            await self._server.stop()
            logger.info("OPC-UA server stopped")

    async def _add_state_variables(
        self,
        idx: int,
        parent_node: Any,
        state: dict[str, object],
        known_vars: set[str],
        path_prefix: str,
    ) -> None:
        """Recursively add state variables as OPC-UA nodes."""
        for var_name in sorted(known_vars):
            if var_name not in state:
                continue

            value = state[var_name]
            full_path = f"{path_prefix}.{var_name}"

            if isinstance(value, dict):
                # FB instance or struct — create a folder
                folder = await parent_node.add_folder(idx, var_name)
                await self._add_state_variables(
                    idx, folder, value, set(value.keys()), full_path,
                )
            else:
                # Scalar — create a variable node
                vtype = _python_value_to_variant_type(value)
                if vtype is not None:
                    node = await parent_node.add_variable(
                        idx, var_name, value, vtype,
                    )
                    await node.set_writable()
                    self._nodes[full_path] = node

    async def _sync_loop(self) -> None:
        """Periodically push state dict values to OPC-UA nodes."""
        try:
            while True:
                await asyncio.sleep(0.05)  # 50ms sync interval
                await self._sync_values()
        except asyncio.CancelledError:
            pass

    async def _sync_values(self) -> None:
        """Push current PLC state to OPC-UA nodes."""
        for path, node in self._nodes.items():
            try:
                value = self._engine.read_variable(path)
                # Convert bool to Python bool for OPC-UA
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    await node.write_value(value)
                else:
                    await node.write_value(value)
            except (KeyError, Exception):
                pass  # Variable may have been removed during reload

    async def _write_monitor_loop(self) -> None:
        """Periodically check for OPC-UA client writes and push to engine."""
        try:
            while True:
                await asyncio.sleep(0.05)  # 50ms check interval
                for path, node in self._nodes.items():
                    try:
                        opcua_value = await node.read_value()
                        engine_value = self._engine.read_variable(path)
                        if opcua_value != engine_value:
                            self._engine.write_variable(path, opcua_value)
                    except (KeyError, Exception):
                        pass
        except asyncio.CancelledError:
            pass

    async def rebuild_address_space(self) -> None:
        """Rebuild the OPC-UA address space after a project reload."""
        if self._server is None:
            return

        # Stop sync tasks
        if self._sync_task is not None:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        if self._write_task is not None:
            self._write_task.cancel()
            try:
                await self._write_task
            except asyncio.CancelledError:
                pass

        # Clear old nodes
        self._nodes.clear()

        # Delete and recreate the plx folder
        server = self._server
        idx = await server.get_namespace_index("urn:plx:runtime")

        # Find and delete old plx folder
        objects = server.nodes.objects
        children = await objects.get_children()
        for child in children:
            name = await child.read_browse_name()
            if name.Name == "plx":
                await server.delete_nodes([child], recursive=True)
                break

        # Recreate
        plx_folder = await objects.add_folder(idx, "plx")

        programs_folder = await plx_folder.add_folder(idx, "Programs")
        for prog_name, ctx in self._engine._sim._programs.items():
            prog_folder = await programs_folder.add_folder(idx, prog_name)
            await self._add_state_variables(
                idx, prog_folder, ctx._state, ctx._known_vars, f"{prog_name}",
            )

        gvls_folder = await plx_folder.add_folder(idx, "GVLs")
        for gvl_name, gvl_state in self._engine._sim._global_state.items():
            gvl_folder = await gvls_folder.add_folder(idx, gvl_name)
            await self._add_state_variables(
                idx, gvl_folder, gvl_state, set(gvl_state.keys()), f"GVLs.{gvl_name}",
            )

        # Restart sync tasks
        self._sync_task = asyncio.create_task(self._sync_loop())
        self._write_task = asyncio.create_task(self._write_monitor_loop())

        logger.info("OPC-UA address space rebuilt")
