"""Read-only live smoke check; prints only statuses and row counts."""

from osguard.tools.extended import (
    inspect_problem_devices, inspect_network_adapters, get_network_configuration,
    inspect_dns_configuration, inspect_failed_updates, inspect_installed_software,
)

for function, key in (
    (inspect_problem_devices, "devices"),
    (inspect_network_adapters, "adapters"),
    (get_network_configuration, "interfaces"),
    (inspect_dns_configuration, "interfaces"),
    (inspect_failed_updates, "updates"),
    (inspect_installed_software, "applications"),
):
    result = function()
    print(f"{result.tool_name}: {result.status}; count={len(result.data.get(key, []))}; error={result.error or 'none'}")
