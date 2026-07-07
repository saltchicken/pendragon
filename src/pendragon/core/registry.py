OPERATION_REGISTRY = {}


def register_operation(name, config_class=None):

    def decorator(cls):
        OPERATION_REGISTRY[name] = {"class": cls, "config": config_class}
        return cls

    return decorator

