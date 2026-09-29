import os

import uvicorn


def main() -> None:
    port = int(os.environ.get("PORT") or "8766")
    uvicorn.run("sprint_radar.app:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
