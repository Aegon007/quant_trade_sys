import importlib
import sys


def clear_modules(*module_names):
    for module_name in module_names:
        sys.modules.pop(module_name, None)


def reload_module(module_name):
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)
