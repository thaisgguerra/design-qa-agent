"""Offline tests: diff, guardrails and the Claude request/response contract (mocked client)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from designqa.analyze import ClaudeAnalyzer  # noqa: E402
from designqa.diff import compute_diff, load_pair  # noqa: E402
from designqa.pipeline import analyze_screen  # noqa: E402


def make_pair(tmp: Path):
    d = Image.new("RGB", (600, 400), "white")
    ImageDraw.Draw(d).rectangle([50, 300, 250, 350], fill="#2563EB")
    i = d.copy()
    ImageDraw.Draw(i).rectangle([50, 300, 250, 350], fill="#3B82F6")
    d.save(tmp / "d.png")
    i.save(tmp / "i.png")
    return tmp / "d.png", tmp / "i.png"


class FakeClient:
    """Mimics anthropic.Anthropic().messages.create with a forced tool call."""

    def __init__(self, findings):
        self.findings = findings
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        block = SimpleNamespace(type="tool_use", name="report_findings",
                                input={"findings": self.findings, "noise_region_ids": []})
        return SimpleNamespace(content=[block], usage=SimpleNamespace(input_tokens=3000, output_tokens=400))


def test_diff_finds_changed_button(tmp_path):
    dp, ip = make_pair(tmp_path)
    d, i, s = load_pair(dp, ip)
    _, regions = compute_diff(d, i)
    assert s == 1 and len(regions) == 1
    r = regions[0]
    assert 40 <= r.x <= 55 and 290 <= r.y <= 305


def test_identical_images_skip_llm(tmp_path):
    dp, _ = make_pair(tmp_path)
    client = FakeClient([])
    res = analyze_screen(dp, dp, ClaudeAnalyzer(model="claude-sonnet-5-5", client=client), tmp_path / "out")
    assert res["regions"] == [] and client.calls == [] and res["findings"] == []


def test_claude_contract_and_guardrails(tmp_path):
    dp, ip = make_pair(tmp_path)
    client = FakeClient([
        {"title": "Primary CTA uses the wrong blue", "category": "color", "severity": "critical",
         "element": "Pay button", "expected": "#2563EB", "actual": "#3B82F6", "bbox": [50, 300, 200, 50],
         "region_ids": [1], "confidence": 0.95, "rationale": "DOM bg vs Figma fill"},
        {"title": "Duplicate of the same issue", "category": "color", "severity": "major",
         "element": "Pay button", "expected": "#2563EB", "actual": "#3B82F6", "bbox": [52, 302, 196, 46],
         "region_ids": [1], "confidence": 0.7, "rationale": "dup"},
        {"title": "Hallucinated title issue", "category": "typography", "severity": "major",
         "element": "Title", "expected": "28px", "actual": "22px", "bbox": [400, 20, 150, 30],
         "region_ids": [], "confidence": 0.9, "rationale": "no evidence"},
        {"title": "Claims a color change that is not there", "category": "color", "severity": "minor",
         "element": "Background", "expected": "#FFFFFF", "actual": "#FFFFFF", "bbox": [300, 50, 100, 100],
         "region_ids": [], "confidence": 0.8, "rationale": "same value"},
    ])
    an = ClaudeAnalyzer(model="claude-sonnet-5-5", client=client)
    res = analyze_screen(dp, ip, an, tmp_path / "out", screen="Checkout")

    kw = client.calls[0]
    assert kw["tool_choice"] == {"type": "tool", "name": "report_findings"}
    images = [c for c in kw["messages"][0]["content"] if c["type"] == "image"]
    assert len(images) == 3

    by_title = {f["title"]: f for f in res["findings"]}
    assert "Duplicate of the same issue" not in by_title                       # merged
    assert by_title["Primary CTA uses the wrong blue"]["status"] == "proposed"
    assert by_title["Hallucinated title issue"]["status"] == "needs_review"      # no pixel evidence
    assert by_title["Claims a color change that is not there"]["status"] == "rejected"
    assert res["usage"]["cost_usd"] > 0
    assert (tmp_path / "out" / "report.html").exists()
    json.loads((tmp_path / "out" / "findings.json").read_text())


def test_tiling_maps_coordinates_back(tmp_path):
    d = Image.new("RGB", (800, 3000), "white")
    i = d.copy()
    ImageDraw.Draw(i).rectangle([100, 2000, 300, 2050], fill="black")
    d.save(tmp_path / "d.png")
    i.save(tmp_path / "i.png")
    # model answers in the coordinates of the (tile) image it received
    client = FakeClient([{"title": "Extra bar", "category": "extra_element", "severity": "major",
                          "element": "bar", "expected": "nothing", "actual": "black bar",
                          "bbox": [100, 720, 200, 50], "region_ids": [1], "confidence": 0.9,
                          "rationale": "visible"}])
    an = ClaudeAnalyzer(model="claude-sonnet-5-5", client=client, tile_height=1400, overlap=120)
    res = analyze_screen(tmp_path / "d.png", tmp_path / "i.png", an, tmp_path / "out")
    assert len(client.calls) == 1  # only the tile containing the change is sent
    f = res["findings"][0]
    assert abs(f["bbox"][1] - 2000) < 20, f["bbox"]
