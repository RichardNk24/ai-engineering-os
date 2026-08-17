from pathlib import Path

AEO_DIRNAME = ".aeo"
PROJECT_CONFIG_FILENAME = "project.json"
DATABASE_FILENAME = "aeo.db"


def aeo_dir(root: Path) -> Path:
    return root / AEO_DIRNAME


def project_config_path(root: Path) -> Path:
    return aeo_dir(root) / PROJECT_CONFIG_FILENAME


def database_path(root: Path) -> Path:
    return aeo_dir(root) / DATABASE_FILENAME
