"""Bounded subprocesses: cancellation cannot leave an activating client alive."""
import subprocess
import time
import os


def run_process(command, *, cwd=None, timeout=180, check=None):
    if timeout <= 0:
        raise TimeoutError('No time remains for operation')
    if check:
        check()
    with subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True) as process:
        deadline = time.monotonic() + timeout
        try:
            while True:
                if check:
                    check()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    stdout, stderr = process.communicate(timeout=min(.2, remaining))
                    if check:
                        check()
                    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        raise
        except BaseException:
            if process.poll() is None:
                if os.name == 'nt':
                    # docker.exe launches the Compose plugin. Killing only the
                    # parent leaves the plugin holding stdout and activating
                    # containers after cancellation/cleanup.
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
                if process.poll() is None: process.kill()
            try: process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.stdout.close(); process.stderr.close()
                raise RuntimeError('Subprocess descendants did not stop after cancellation')
            raise
