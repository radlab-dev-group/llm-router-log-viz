import time
from pathlib import Path

from llm_router_log_viz.watcher import LogWatcher


def test_watcher_reads_existing_and_appended_lines(tmp_path: Path):
    log = tmp_path / "router.log"
    log.write_text("line1\nline2\n", encoding="utf-8")

    seen = []

    def on_line(line, line_no):
        seen.append((line_no, line))

    watcher = LogWatcher(str(log), on_line=on_line, poll_interval=0.05, read_from_start=True)
    watcher.start()
    try:
        time.sleep(0.3)
        assert [l for _, l in seen] == ["line1", "line2"]

        with log.open("a", encoding="utf-8") as f:
            f.write("line3\n")
            f.flush()

        time.sleep(0.3)
        assert [l for _, l in seen] == ["line1", "line2", "line3"]
    finally:
        watcher.stop()
