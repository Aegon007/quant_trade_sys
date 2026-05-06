import importlib


def import_from_path(dotted_path):
    module_name, _, attr_name = dotted_path.rpartition(".")
    if not module_name or not attr_name:
        raise ValueError(f"Invalid import path: {dotted_path}")
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)

