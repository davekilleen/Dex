"""Harness capability descriptors and portable skill contracts.

The exports are lazy so ``python -m core.harnesses.registry`` emits only the
requested JSON, without a ``runpy`` duplicate-import warning.
"""


def __getattr__(name: str):
    if name in {
        "CapabilityProfile",
        "CapabilityRow",
        "REGISTRY_PATH",
        "detect_harnesses",
        "get_profile",
        "list_profiles",
    }:
        from . import registry

        return getattr(registry, name)
    raise AttributeError(name)

__all__ = [
    "CapabilityProfile",
    "CapabilityRow",
    "REGISTRY_PATH",
    "detect_harnesses",
    "get_profile",
    "list_profiles",
]
