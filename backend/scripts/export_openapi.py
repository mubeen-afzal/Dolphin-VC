import json
from pathlib import Path

from app.config import Settings
from app.main import create_app


def main() -> None:
    app = create_app(
        Settings(env="test", secret_key="openapi-export-key-that-is-at-least-32-bytes")
    )
    destination = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
    print(destination)


if __name__ == "__main__":
    main()
