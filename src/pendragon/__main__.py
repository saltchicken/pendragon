from pendragon.plugins import load_plugins
from pendragon import OPERATION_REGISTRY

def main():
    load_plugins()
    print(OPERATION_REGISTRY)

if __name__ == "__main__":
    main()
