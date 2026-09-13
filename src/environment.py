from pathlib import Path


def get_environment_context() -> str:
    home = Path.home().resolve()
    project = Path.cwd().resolve()

    return (
        "LOCAL ENVIRONMENT:\n"
        f"User home: {home}\n"
        f"Desktop: {home / 'Desktop'}\n"
        f"Documents: {home / 'Documents'}\n"
        f"Downloads: {home / 'Downloads'}\n"
        f"Project directory: {project}"
    )