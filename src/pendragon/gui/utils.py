from importlib.resources import files


def load_stylesheet(filename: str = "style.qss") -> str:
    resource_path = files("pendragon.resources").joinpath(filename)

    if resource_path.exists():
        return resource_path.read_text()
    return ""
