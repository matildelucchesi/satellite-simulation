# Copyright 2022-2026 ETSI SDG TeraFlowSDN (TFS) (https://tfs.etsi.org/)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Service handler for P4-based L2 forwarding using the SD-Fabric P4 dataplane
for BMv2 and Intel Tofino switches.
"""

import logging
from typing import Any, List, Dict, Optional, Tuple, Union
from common.method_wrappers.Decorator import MetricsPool, metered_subclass_method
from common.proto.context_pb2 import ConfigActionEnum, DeviceId, Service, Device
from common.tools.object_factory.Device import json_device_id
from common.type_checkers.Checkers import chk_type, chk_address_mac, chk_vlan_id
from service.service.service_handler_api._ServiceHandler import _ServiceHandler
from service.service.service_handler_api.SettingsHandler import SettingsHandler
from service.service.service_handlers.p4_fabric_tna_commons.p4_fabric_tna_commons import *
from service.service.task_scheduler.TaskExecutor import TaskExecutor

LOGGER = logging.getLogger(__name__)

METRICS_POOL = MetricsPool('Service', 'Handler', labels={'handler': 'p4_fabric_tna_l2_simple'})

class P4FabricL2SimpleServiceHandler(_ServiceHandler):
    def __init__(   # pylint: disable=super-init-not-called
        self, service : Service, task_executor : TaskExecutor, **settings # type: ignore
    ) -> None:
        """ Initialize Driver.
            Parameters:
                service
                    The service instance (gRPC message) to be managed.
                task_executor
                    An instance of Task Executor providing access to the
                    service handlers factory, the context and device clients,
                    and an internal cache of already-loaded gRPC entities.
                **settings
                    Extra settings required by the service handler.

        """
        self.__service_label = "P4 L2 simple connectivity service"
        self.__service = service
        self.__task_executor = task_executor
        self.__settings_handler = SettingsHandler(self.__service.service_config, **settings)

        self._init_settings()
        self._parse_settings()
        self._print_settings()

    @metered_subclass_method(METRICS_POOL)
    def SetEndpoint(
        self, endpoints : List[Tuple[str, str, Optional[str]]],
        connection_uuid : Optional[str] = None
    ) -> List[Union[bool, Exception]]:
        """ Create/Update service endpoints from a list.
            Parameters:
                endpoints: List[Tuple[str, str, Optional[str]]]
                    List of tuples, each containing a device_uuid,
                    endpoint_uuid and, optionally, the topology_uuid
                    of the endpoint to be added.
                connection_uuid : Optional[str]
                    If specified, is the UUID of the connection this endpoint is associated to.
            Returns:
                results: List[Union[bool, Exception]]
                    List of results for endpoint changes requested.
                    Return values must be in the same order as the requested
                    endpoints. If an endpoint is properly added, True must be
                    returned; otherwise, the Exception that is raised during
                    the processing must be returned.
        """
        chk_type('endpoints', endpoints, list)
        if len(endpoints) == 0: return []

        LOGGER.info(f"{self.__service_label} - Provision service configuration")

        visited = set()
        results = []
        for endpoint in endpoints:
            device_uuid, endpoint_uuid = endpoint[0:2]
            device = self.__task_executor.get_device(DeviceId(**json_device_id(device_uuid)))
            device_name = device.name

            LOGGER.info(f"Device {device_name}")
            LOGGER.info(f"\t | Service endpoint UUID: {endpoint_uuid}")

            port_id = find_port_id_in_endpoint_list(device.device_endpoints, endpoint_uuid)
            LOGGER.info(f"\t | Service port ID: {port_id}")

            dev_port_key = device_name + "-" + PORT_PREFIX + str(port_id)

            # Skip already visited device ports
            if dev_port_key in visited:
                continue

            rules = []
            actual_rules = -1
            applied_rules, failed_rules = 0, -1

            # Create and apply rules
            try:
                rules = self._create_rules(
                    device_obj=device, port_id=port_id, action=ConfigActionEnum.CONFIGACTION_SET)
                actual_rules = len(rules)
                applied_rules, failed_rules = apply_rules(
                    task_executor=self.__task_executor,
                    device_obj=device,
                    json_config_rules=rules
                )
            except Exception as ex:
                LOGGER.error(f"Failed to insert L2 rules on device {device.name} due to {ex}")
                results.append(ex)
            finally:
                rules.clear()

            # Ensure correct status
            if (failed_rules == 0) and (applied_rules == actual_rules):
                LOGGER.info(f"Installed {applied_rules}/{actual_rules} L2 rules on device {device_name} and port {port_id}")
                results.append(True)

            # You should no longer visit this device port again
            visited.add(dev_port_key)

        return results

    @metered_subclass_method(METRICS_POOL)
    def DeleteEndpoint(
        self, endpoints : List[Tuple[str, str, Optional[str]]],
        connection_uuid : Optional[str] = None
    ) -> List[Union[bool, Exception]]:
        """ Delete service endpoints from a list.
            Parameters:
                endpoints: List[Tuple[str, str, Optional[str]]]
                    List of tuples, each containing a device_uuid,
                    endpoint_uuid, and the topology_uuid of the endpoint
                    to be removed.
                connection_uuid : Optional[str]
                    If specified, is the UUID of the connection this endpoint is associated to.
            Returns:
                results: List[Union[bool, Exception]]
                    List of results for endpoint deletions requested.
                    Return values must be in the same order as the requested
                    endpoints. If an endpoint is properly deleted, True must be
                    returned; otherwise, the Exception that is raised during
                    the processing must be returned.
        """
        chk_type('endpoints', endpoints, list)
        if len(endpoints) == 0: return []

        LOGGER.info(f"{self.__service_label} - Deprovision service configuration")

        visited = set()
        results = []
        for endpoint in endpoints:
            device_uuid, endpoint_uuid = endpoint[0:2]
            device = self.__task_executor.get_device(DeviceId(**json_device_id(device_uuid)))
            device_name = device.name

            LOGGER.info(f"Device {device_name}")
            LOGGER.info(f"\t | Service endpoint UUID: {endpoint_uuid}")

            port_id = find_port_id_in_endpoint_list(device.device_endpoints, endpoint_uuid)
            LOGGER.info(f"\t | Service port ID: {port_id}")

            dev_port_key = device_name + "-" + PORT_PREFIX + str(port_id)

            # Skip already visited device ports
            if dev_port_key in visited:
                continue

            rules = []
            actual_rules = -1
            applied_rules, failed_rules = 0, -1

            # Create and apply rules
            try:
                rules = self._create_rules(
                    device_obj=device, port_id=port_id, action=ConfigActionEnum.CONFIGACTION_DELETE)
                actual_rules = len(rules)
                applied_rules, failed_rules = apply_rules(
                    task_executor=self.__task_executor,
                    device_obj=device,
                    json_config_rules=rules
                )
            except Exception as ex:
                LOGGER.error(f"Failed to delete L2 rules from device {device.name} due to {ex}")
                results.append(ex)
            finally:
                rules.clear()

            # Ensure correct status
            if (failed_rules == 0) and (applied_rules == actual_rules):
                LOGGER.info(f"Deleted {applied_rules}/{actual_rules} L2 rules from device {device_name} and port {port_id}")
                results.append(True)

            # You should no longer visit this device port again
            visited.add(dev_port_key)

        return results

    @metered_subclass_method(METRICS_POOL)
    def SetConstraint(self, constraints: List[Tuple[str, Any]]) \
            -> List[Union[bool, Exception]]:
        """ Create/Update service constraints.
            Parameters:
                constraints: List[Tuple[str, Any]]
                    List of tuples, each containing a constraint_type and the
                    new constraint_value to be set.
            Returns:
                results: List[Union[bool, Exception]]
                    List of results for constraint changes requested.
                    Return values must be in the same order as the requested
                    constraints. If a constraint is properly set, True must be
                    returned; otherwise, the Exception that is raised during
                    the processing must be returned.
        """
        chk_type('constraints', constraints, list)
        if len(constraints) == 0: return []

        msg = '[SetConstraint] Method not implemented. Constraints({:s}) are being ignored.'
        LOGGER.warning(msg.format(str(constraints)))
        return [True for _ in range(len(constraints))]

    @metered_subclass_method(METRICS_POOL)
    def DeleteConstraint(self, constraints: List[Tuple[str, Any]]) \
            -> List[Union[bool, Exception]]:
        """ Delete service constraints.
            Parameters:
                constraints: List[Tuple[str, Any]]
                    List of tuples, each containing a constraint_type pointing
                    to the constraint to be deleted, and a constraint_value
                    containing possible additionally required values to locate
                    the constraint to be removed.
            Returns:
                results: List[Union[bool, Exception]]
                    List of results for constraint deletions requested.
                    Return values must be in the same order as the requested
                    constraints. If a constraint is properly deleted, True must
                    be returned; otherwise, the Exception that is raised during
                    the processing must be returned.
        """
        chk_type('constraints', constraints, list)
        if len(constraints) == 0: return []

        msg = '[DeleteConstraint] Method not implemented. Constraints({:s}) are being ignored.'
        LOGGER.warning(msg.format(str(constraints)))
        return [True for _ in range(len(constraints))]

    @metered_subclass_method(METRICS_POOL)
    def SetConfig(self, resources: List[Tuple[str, Any]]) \
            -> List[Union[bool, Exception]]:
        """ Create/Update configuration for a list of service resources.
            Parameters:
                resources: List[Tuple[str, Any]]
                    List of tuples, each containing a resource_key pointing to
                    the resource to be modified, and a resource_value
                    containing the new value to be set.
            Returns:
                results: List[Union[bool, Exception]]
                    List of results for resource key changes requested.
                    Return values must be in the same order as the requested
                    resource keys. If a resource is properly set, True must be
                    returned; otherwise, the Exception that is raised during
                    the processing must be returned.
        """
        chk_type('resources', resources, list)
        if len(resources) == 0: return []

        msg = '[SetConfig] Method not implemented. Resources({:s}) are being ignored.'
        LOGGER.warning(msg.format(str(resources)))
        return [True for _ in range(len(resources))]

    @metered_subclass_method(METRICS_POOL)
    def DeleteConfig(self, resources: List[Tuple[str, Any]]) \
            -> List[Union[bool, Exception]]:
        """ Delete configuration for a list of service resources.
            Parameters:
                resources: List[Tuple[str, Any]]
                    List of tuples, each containing a resource_key pointing to
                    the resource to be modified, and a resource_value containing
                    possible additionally required values to locate the value
                    to be removed.
            Returns:
                results: List[Union[bool, Exception]]
                    List of results for resource key deletions requested.
                    Return values must be in the same order as the requested
                    resource keys. If a resource is properly deleted, True must
                    be returned; otherwise, the Exception that is raised during
                    the processing must be returned.
        """
        chk_type('resources', resources, list)
        if len(resources) == 0: return []

        msg = '[SetConfig] Method not implemented. Resources({:s}) are being ignored.'
        LOGGER.warning(msg.format(str(resources)))
        return [True for _ in range(len(resources))]

    def _init_settings(self):
        self.__switch_info = {}
        self.__port_map = {}

        try:
            self.__settings = self.__settings_handler.get('/settings')
            LOGGER.info(f"{self.__service_label} with settings: {self.__settings}")
        except Exception as ex:
            LOGGER.error(f"Failed to retrieve service settings: {ex}")
            raise Exception(ex)

    def _parse_settings(self):
        try:
            switch_info = self.__settings.value[SWITCH_INFO]
        except Exception as ex:
            LOGGER.error(f"Failed to parse service settings: {ex}")
            raise Exception(ex)
        assert isinstance(switch_info, list), "Switch info object must be a list"

        for switch in switch_info:
            for switch_name, sw_info in switch.items():
                assert switch_name, "Invalid P4 switch name"
                assert isinstance(sw_info, dict), f"Switch {switch_name} info must be a map with arch, dpid, and fwd_list items)"
                assert sw_info[ARCH] in SUPPORTED_TARGET_ARCH_LIST, \
                    f"Switch {switch_name} - Supported P4 architectures are: {','.join(SUPPORTED_TARGET_ARCH_LIST)}"
                switch_dpid = sw_info[DPID]
                assert switch_dpid > 0, f"Switch {switch_name} - P4 switch dataplane ID {sw_info[DPID]} must be a positive integer"

                # Port list
                port_list = sw_info[PORT_LIST]
                assert isinstance(port_list, list), \
                    f"Switch {switch_name} port list must be a list with port_id, port_type, and vlan_id items"
                for port in port_list:
                    port_id = port[PORT_ID]
                    assert port_id >= 0, f"Switch {switch_name} - Invalid P4 switch port ID"
                    port_type = port[PORT_TYPE]
                    assert port_type in PORT_TYPES_STR_VALID, f"Switch {switch_name} - Valid P4 switch port types are: {','.join(PORT_TYPES_STR_VALID)}"
                    vlan_id = port[VLAN_ID]
                    assert chk_vlan_id(vlan_id), f"Switch {switch_name} - Invalid VLAN ID for port {port_id}"

                    if switch_name not in self.__port_map:
                        self.__port_map[switch_name] = {}
                    port_key = PORT_PREFIX + str(port_id)
                    if port_key not in self.__port_map[switch_name]:
                        self.__port_map[switch_name][port_key] = {}
                    self.__port_map[switch_name][port_key][PORT_ID] = port_id
                    self.__port_map[switch_name][port_key][PORT_TYPE] = port_type
                    self.__port_map[switch_name][port_key][VLAN_ID] = vlan_id
                    self.__port_map[switch_name][port_key][FORWARDING_LIST] = []

                # Forwarding list
                fwd_list = sw_info[FORWARDING_LIST]
                assert isinstance(fwd_list, list), f"Switch {switch_name} forwarding list must be a list"
                for fwd_entry in fwd_list:
                    port_id = fwd_entry[PORT_ID]
                    assert port_id >= 0, f"Invalid port ID: {port_id}"
                    host_mac = fwd_entry[HOST_MAC]
                    assert chk_address_mac(host_mac), f"Invalid host MAC address {host_mac}"

                    # Retrieve entry from the port map
                    switch_port_entry = self._get_switch_port_in_port_map(switch_name, port_id)

                    host_facing_port = self._is_host_facing_port(switch_name, port_id)
                    LOGGER.info(f"Switch {switch_name} - Port {port_id}: Is host facing: {"True" if host_facing_port else "False"}")
                    switch_port_entry[FORWARDING_LIST].append(host_mac)
                self.__switch_info[switch_name] = sw_info

    def _print_settings(self):
        LOGGER.info(f"--------------- {self.__service.name} settings ---------------")
        LOGGER.info("--- Topology info")
        for switch_name, switch_info in self.__switch_info.items():
            LOGGER.info(f"\t Device {switch_name}")
            LOGGER.info(f"\t\t| Target P4 architecture: {switch_info[ARCH]}")
            LOGGER.info(f"\t\t|          Data plane ID: {switch_info[DPID]}")
            LOGGER.info(f"\t\t|               Port map: {self.__port_map[switch_name]}")
        LOGGER.info("-------------------------------------------------------")

    def _get_switch_port_in_port_map(self, switch_name : str, port_id : int) -> Dict:
        assert switch_name, "A valid switch name must be used as a key to the port map"
        assert port_id > 0, "A valid switch port ID must be used as a key to a switch's port map"
        switch_entry = self.__port_map[switch_name]
        assert switch_entry, f"Switch {switch_name} does not exist in the port map"
        port_key = PORT_PREFIX + str(port_id)
        assert switch_entry[port_key], f"Port with ID {port_id} does not exist in the switch map"

        return switch_entry[port_key]

    def _get_port_type_of_switch_port(self, switch_name : str, port_id : int) -> str:
        switch_port_entry = self._get_switch_port_in_port_map(switch_name, port_id)
        return switch_port_entry[PORT_TYPE]

    def _get_vlan_id_of_switch_port(self, switch_name : str, port_id : int) -> int:
        switch_port_entry = self._get_switch_port_in_port_map(switch_name, port_id)
        return switch_port_entry[VLAN_ID]

    def _get_fwd_list_of_switch_port(self, switch_name : str, port_id : int) -> List [Tuple]:
        switch_port_entry = self._get_switch_port_in_port_map(switch_name, port_id)
        return switch_port_entry[FORWARDING_LIST]

    def _is_host_facing_port(self, switch_name : str, port_id : int) -> bool:
        return self._get_port_type_of_switch_port(switch_name, port_id) == PORT_TYPE_HOST

    def _create_rules(self, device_obj, port_id, action):
        # Local migration-lab patch: next IDs are actual egress port IDs.
        # L2 frames retain both host MACs; output_hashed selects a single port.
        import hashlib
        import json
        dev_name = device_obj.name
        make = ConfigActionEnum.CONFIGACTION_SET
        vlan = self._get_vlan_id_of_switch_port(dev_name, port_id)
        setup = rules_set_up_port_host if self._is_host_facing_port(dev_name, port_id) else rules_set_up_port_switch
        rules = setup(port=port_id, vlan_id=vlan, action=make)
        destinations = self._get_fwd_list_of_switch_port(dev_name, port_id)
        for mac in destinations:
            rules += rules_set_up_fwd_bridging(port_id=port_id, vlan_id=vlan,
                                              eth_dst=mac, next_id=port_id, action=make)
        if destinations:
            rules += rules_set_up_next_profile_hashed_output(port_id=port_id, next_id=port_id, action=make)
            rules += rules_set_up_next_hashed(port_id=port_id, next_id=port_id, action=make)
        # Stable device rule keys permit deletion/replay across fresh processes;
        # upstream's process-global sequential cache does not identify a rule.
        for rule in rules:
            custom = rule['custom']
            value = custom['resource_value']
            value = json.loads(value) if isinstance(value, str) else value
            base = custom['resource_key'].rsplit('[', 1)[0]
            identity = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
            index = int.from_bytes(hashlib.sha256(identity).digest()[:4], 'big') or 1
            custom['resource_key'] = base + '[' + str(index) + ']'
            rule['action'] = action
        # Delete table references before their action-profile members.
        return list(reversed(rules)) if action == ConfigActionEnum.CONFIGACTION_DELETE else rules
