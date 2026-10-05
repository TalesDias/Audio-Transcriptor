"""Entry point: start the local server (or reuse a running one) and open the browser."""

import json
import os
import sys
import threading
import time
import urllib.request
import webbrowser

from . import selfinstall, server, transcribe
from .config import APP_NAME, DATA_DIR, IDLE_SHUTDOWN_SECONDS

INSTANCE_FILE = DATA_DIR / "instance.json"


def running_instance_url() -> str | None:
    try:
        port = json.loads(INSTANCE_FILE.read_text())["port"]
        url = f"http://127.0.0.1:{port}/"
        with urllib.request.urlopen(url + "api/ping", timeout=1) as r:
            if json.load(r).get("app") == APP_NAME:
                return url
    except (OSError, ValueError, KeyError):
        pass
    return None


def idle_watchdog(httpd):
    while True:
        time.sleep(10)
        idle = time.monotonic() - server.last_ping
        if idle > IDLE_SHUTDOWN_SECONDS and transcribe.active_count() == 0:
            httpd.shutdown()
            return


def main():
    if "--uninstall" in sys.argv[1:]:
        if selfinstall.remove_installed():
            print(f"{APP_NAME} desinstalado. Suas transcrições continuam em {DATA_DIR} "
                  "(apague a pasta para removê-las).")
        else:
            print(f"{APP_NAME} não está instalado.")
        return

    selfinstall.ensure_installed()

    url = running_instance_url()
    if url:
        webbrowser.open(url)
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    httpd = server.make_server()
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    INSTANCE_FILE.write_text(json.dumps({"port": port, "pid": os.getpid()}))

    transcribe.resume_pending()
    threading.Thread(target=idle_watchdog, args=(httpd,), daemon=True).start()
    threading.Timer(0.3, webbrowser.open, args=(url,)).start()

    print(f"{APP_NAME} rodando em {url} (feche esta janela para encerrar)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        INSTANCE_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
