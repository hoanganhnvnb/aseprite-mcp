"""Stand-in for the aseprite binary, driven by params["fake"]."""

import json
import subprocess
import sys
import time
from pathlib import Path


def _params_path(argv: list[str]) -> Path:
    for i, arg in enumerate(argv):
        if arg == "--script-param" and argv[i + 1].startswith("params="):
            return Path(argv[i + 1].removeprefix("params="))
    raise SystemExit("no params= given")


def _log(params: dict, event: str) -> None:
    if params.get("log"):
        with open(params["log"], "a", encoding="utf-8") as fh:
            fh.write(f"{event} {time.time()}\n")


def main() -> int:
    params = json.loads(_params_path(sys.argv).read_text(encoding="utf-8"))
    mode = params.get("fake", "ok")
    result_path = Path(params["result_path"])

    if mode == "sleep":
        if params.get("save_tmp"):
            Path(params["save_tmp"]).write_text("partial")
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        Path(params["pid_file"]).write_text(str(child.pid))
        time.sleep(30)
        return 0
    if mode == "crash":
        print("boom: something went wrong", file=sys.stderr)
        return 3
    if mode == "noresult":
        return 0
    if mode == "fail":
        result_path.write_text(json.dumps({"ok": False, "error": "no such layer"}))
        return 0
    if mode == "numbered":
        tmp = Path(params["save_tmp"])
        for n in (1, 2):
            tmp.with_name(f"{tmp.stem}{n}{tmp.suffix}").write_text("frame")
        result_path.write_text(json.dumps({"ok": True, "results": [], "saved": True}))
        return 0
    if mode == "unicode":
        sys.stdout.buffer.write("pixel éè ☃ ".encode() + b"\xff\n")
        result_path.write_text(json.dumps({"ok": True, "results": [], "saved": False}))
        return 0

    _log(params, "start")
    time.sleep(params.get("delay", 0))
    saved = False
    if params.get("save_tmp") and params.get("write_save"):
        Path(params["save_tmp"]).write_text(params["write_save"])
        saved = True
    for name in params.get("write_files", []):
        Path(name).write_text(params.get("file_text", "new"))
    result_path.write_text(json.dumps({"ok": True, "results": [], "saved": saved}))
    _log(params, "end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
