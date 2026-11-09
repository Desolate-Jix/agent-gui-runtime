"""Check measured history preservation and non-destructive chart refreshes."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import update_download_stats as downloads


def release(tag, day, assets):
    return {"draft": False, "tag_name": tag, "published_at": day + "T00:00:00Z",
            "assets": [{"name": name, "download_count": count} for name, count in assets]}


def release_data():
    return [
        release("instant-v0.1.11", "2026-10-28", [
            ("AgentGUIRuntimeExecution-Setup.exe", 43),
            ("AgentGUIRuntimeExecution-update.zip", 5),
            ("example.mp4", 1000),
            ("AgentGUIRuntimeExecutionPreview-Setup.exe", 1000),
        ]),
        release("amadeus-extension-v0.0.9", "2026-11-06", [
            ("amadeus_agent_gui_runtime-0.0.9-py3-none-any.whl", 56),
        ]),
    ]


def stats():
    return downloads.summarize(release_data())[0]


ROW = {"date": "2026-11-08", "installer": 43, "update": 5, "extension": 56}


class DownloadHistoryTests(unittest.TestCase):
    def test_asset_scope(self):
        self.assertEqual([item["downloads"] for item in stats().values()], [43, 5, 56])

    def test_same_day_replaces_only_latest_snapshot(self):
        history = [dict(ROW, date="2026-11-07"), ROW.copy()]
        original = deepcopy(history)
        counts = stats()
        counts["installer"]["downloads"] = 44
        result = downloads.record_snapshot(history, counts, "2026-11-08")
        self.assertEqual(history, original)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], original[0])
        self.assertEqual(result[1]["installer"], 44)

    def test_gap_and_decline_are_preserved_without_filling(self):
        counts = stats()
        counts["installer"]["downloads"] = 40
        result = downloads.record_snapshot([ROW.copy()], counts, "2026-11-12")
        self.assertEqual([r["date"] for r in result], ["2026-11-08", "2026-11-12"])
        self.assertEqual(result[-1]["installer"], 40)

    def test_invalid_history_and_backdated_capture_fail(self):
        cases = [
            {}, [ROW.copy(), ROW.copy()],
            [dict(ROW, date="2026-11-10"), ROW.copy()],
            [dict(ROW, installer=-1)], [dict(ROW, installer=True)],
            [dict(ROW, date="2026-13-01")], [dict(ROW, date="20261108")],
        ]
        for history in cases:
            with self.subTest(history=history), self.assertRaises(ValueError):
                downloads.record_snapshot(history, stats(), "2026-11-09")
        with self.assertRaises(ValueError):
            downloads.record_snapshot([ROW.copy()], stats(), "2026-11-07")

    def setup_root(self, root):
        (root / "docs/data").mkdir(parents=True)
        (root / "docs/data/download-history.json").write_text(json.dumps([ROW]), encoding="utf-8")
        original = b"before\r\n" + downloads.START + b"\r\nold\r\n" + downloads.END + b"\r\nafter\r\n"
        for name in ("README.md", "README.zh-CN.md"):
            (root / name).write_bytes(original)
        return original

    def test_update_is_idempotent_and_preserves_unrelated_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.setup_root(root)
            downloads.update_outputs(root, release_data(), "2026-11-09")
            first = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            downloads.update_outputs(root, release_data(), "2026-11-09")
            second = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(first, second)
            for name in ("README.md", "README.zh-CN.md"):
                content = (root / name).read_bytes()
                self.assertTrue(content.startswith(b"before\r\n" + downloads.START))
                self.assertTrue(content.endswith(downloads.END + b"\r\nafter\r\n"))
            for lang in ("en", "zh-CN"):
                svg = root / f"docs/assets/downloads/download-trend.{lang}.svg"
                self.assertEqual(ET.fromstring(svg.read_bytes()).tag, "{http://www.w3.org/2000/svg}svg")

    def test_bad_second_readme_cannot_change_history_or_first_readme(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = self.setup_root(root)
            history_path = root / "docs/data/download-history.json"
            history_before = history_path.read_bytes()
            (root / "README.zh-CN.md").write_bytes(b"missing markers")
            with self.assertRaises(ValueError):
                downloads.update_outputs(root, release_data(), "2026-11-09")
            self.assertEqual((root / "README.md").read_bytes(), original)
            self.assertEqual(history_path.read_bytes(), history_before)
            self.assertFalse((root / "docs/assets/downloads").exists())

    def test_release_counts_refresh_without_rewriting_daily_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.setup_root(root)
            releases = release_data()
            releases[0]["assets"][0]["download_count"] = 45
            downloads.update_outputs(root, releases[::-1], "2026-11-10")
            history = json.loads((root / "docs/data/download-history.json").read_text())
            self.assertEqual(history, [ROW, dict(ROW, date="2026-11-10", installer=45)])
            snapshot = json.loads((root / "docs/data/downloads-by-release.json").read_text())
            self.assertEqual(snapshot["counts_as_of"], "2026-11-10")
            self.assertEqual([r["downloads"] for r in snapshot["releases"]], [50, 56])
            self.assertEqual([r["published_at"][:10] for r in snapshot["releases"]], ["2026-10-28", "2026-11-06"])
            for lang, month in (("en", "Oct 2026"), ("zh-CN", "2026年10月")):
                svg = ET.fromstring((root / f"docs/assets/downloads/download-trend.{lang}.svg").read_bytes())
                paths = svg.findall(".//{http://www.w3.org/2000/svg}polyline")
                self.assertEqual(len(paths), 1)
                self.assertNotIn("stroke-dasharray", paths[0].attrib)
                self.assertEqual(len(paths[0].get("points").split()), 3)
                self.assertIn(month, " ".join(svg.itertext()))

    def test_same_utc_release_day_is_combined_before_accumulating(self):
        releases = release_data()
        releases.append(release("second-same-day", "2026-10-28", [("AgentGUIRuntimeExecution-Setup.exe", 2)]))
        # A draft must not add to the totals or chart.
        releases.append(dict(release("draft", "2026-11-07", [("AgentGUIRuntimeExecution-Setup.exe", 500)]), draft=True))
        counts, rows = downloads.summarize(releases[::-1])
        self.assertEqual(sum(r["downloads"] for r in rows), 106)
        self.assertEqual(counts["installer"]["downloads"], 45)
        svg = ET.fromstring(downloads.render_chart({"counts_as_of": "2026-11-09", "releases": rows}))
        path = svg.find(".//{http://www.w3.org/2000/svg}polyline")
        points = [tuple(map(float, point.split(","))) for point in path.get("points").split()]
        self.assertEqual(len(points), 3)  # Baseline + two distinct release dates.
        self.assertLess(points[0][0], points[1][0])
        self.assertLess(points[1][0], points[2][0])
        self.assertAlmostEqual((points[0][1] - points[1][1]) / (points[0][1] - points[2][1]), 50 / 106, places=3)


if __name__ == "__main__":
    unittest.main()
