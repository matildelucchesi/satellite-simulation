"""Start, stop or inspect the TeraFlow laboratory and its local console with one command.

start   checks Docker, starts the Compose group (unless a job holds the lab lock),
        then serves the console on http://127.0.0.1:18092/ and opens the browser.
stop    stops the Compose group; the console stops with Ctrl+C in its window.
status  reports Docker, lab lock, Compose containers and console availability.
"""
import argparse
import subprocess
import sys
import webbrowser
from pathlib import Path
from urllib.request import urlopen
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.deployment import compose_command
from tools.stack import UP_ARGUMENTS, create_volumes

PORT = 18092
URL = f'http://127.0.0.1:{PORT}/'
LOCK = Path('results/jobs/lab.lock')


def docker_ready():
    try:
        result = subprocess.run(['docker', 'version', '--format', '{{.Server.Version}}'],
                                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def console_running():
    try:
        with urlopen(URL, timeout=1) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def open_browser(enabled):
    if enabled:
        webbrowser.open(URL)


def start_stack(root):
    if not docker_ready():
        print('Docker non raggiungibile: avviare Docker Desktop con engine Linux e riprovare.', flush=True)
        return 1
    if (root / LOCK).exists():
        print('Un job o un recupero detiene il lock del laboratorio: stack Docker lasciato invariato.', flush=True)
        return 0
    print('Avvio del gruppo Compose teraflow (attesa dei servizi pronti)...', flush=True)
    create_volumes(subprocess.run)
    return subprocess.call(compose_command(*UP_ARGUMENTS), cwd=root)


def serve_console(root, browser):
    if console_running():
        print('Console già attiva: ' + URL, flush=True)
        open_browser(browser)
        return 0
    from src.web import make_server
    try:
        server = make_server(root, PORT)
    except OSError as exc:
        print(f'Porta {PORT} non disponibile: {exc}', flush=True)
        return 1
    print('Console TeraFlow: ' + URL + '  (Ctrl+C per chiuderla; i job proseguono)', flush=True)
    open_browser(browser)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def start(root, stack=True, browser=True):
    if stack:
        code = start_stack(root)
        if code:
            return code
    return serve_console(root, browser)


def stop(root):
    if (root / LOCK).exists():
        print('Un job o un recupero detiene il lock del laboratorio: completare prima il recupero.', flush=True)
        return 1
    return subprocess.call(compose_command('stop'), cwd=root)


def status(root):
    docker = docker_ready()
    print('Docker: ' + ('raggiungibile' if docker else 'non raggiungibile'), flush=True)
    print('Lock del laboratorio: ' + ('presente' if (root / LOCK).exists() else 'assente'), flush=True)
    print('Console: ' + (URL if console_running() else 'non attiva'), flush=True)
    return subprocess.call(compose_command('ps', '-a'), cwd=root) if docker else 1


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='operation', required=True)
    launch = commands.add_parser('start', help='Avvia stack Docker e console')
    launch.add_argument('--no-stack', action='store_true', help='Avvia solo la console')
    launch.add_argument('--no-browser', action='store_true', help='Non aprire il browser')
    commands.add_parser('stop', help='Arresta lo stack Docker')
    commands.add_parser('status', help='Mostra lo stato di Docker, lock, stack e console')
    arguments = parser.parse_args(argv)
    if arguments.operation == 'start':
        return start(root, stack=not arguments.no_stack, browser=not arguments.no_browser)
    return {'stop': stop, 'status': status}[arguments.operation](root)


if __name__ == '__main__':
    raise SystemExit(main())
