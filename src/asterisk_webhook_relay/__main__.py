from __future__ import annotations

import logging
import signal
import threading

from .ami import AmiSessionSupervisor
from .config import RelayConfig
from .server import create_http_server


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = RelayConfig.from_env()
    session = AmiSessionSupervisor(config)
    session.start()
    server = create_http_server(config, session)

    def shutdown(*_: object) -> None:
        threading.Thread(target=server.shutdown, name="http-shutdown", daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        session.stop()


if __name__ == "__main__":
    main()
