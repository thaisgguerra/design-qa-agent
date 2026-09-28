"""Ticket creation. Every tracker gets the same ticket body and the side by side evidence image.

Supported: markdown (local files, default), clickup, linear.
Adding Jira / GitHub Issues means writing one more class with a create() method.
"""
from __future__ import annotations

from pathlib import Path

import requests

from . import config
from .analyze import Finding

PRIORITY = {"critical": 1, "major": 2, "minor": 3}  # ClickUp: 1 urgent, 2 high, 3 normal


def ticket_body(f: Finding, screen: str) -> str:
    return (
        f"**Screen:** {screen}\n"
        f"**Element:** {f.element}\n"
        f"**Category:** {f.category}  |  **Severity:** {f.severity}  |  **Agent confidence:** {f.confidence:.0%}\n\n"
        f"| | Value |\n|---|---|\n| Expected (design) | {f.expected} |\n| Actual (implementation) | {f.actual} |\n\n"
        f"**Why:** {f.rationale}\n\n"
        f"**Location:** x={f.bbox[0]}, y={f.bbox[1]}, {f.bbox[2]}x{f.bbox[3]} px (design coordinates)\n"
        f"**Automated checks:** {'; '.join(f.checks) or 'none'}\n\n"
        f"_Opened by the Design QA agent ({f.id}) after human approval. Evidence attached._"
    )


class MarkdownTracker:
    name = "markdown"

    def __init__(self, out_dir: Path):
        self.dir = out_dir / "tickets"
        self.dir.mkdir(parents=True, exist_ok=True)

    def create(self, f: Finding, evidence: Path, screen: str) -> str:
        path = self.dir / f"{f.id}.md"
        rel = Path("..") / evidence.parent.name / evidence.name
        path.write_text(f"# [{f.severity.upper()}] {f.title}\n\n{ticket_body(f, screen)}\n\n![evidence]({rel.as_posix()})\n")
        return str(path)


class ClickUpTracker:
    name = "clickup"
    API = "https://api.clickup.com/api/v2"

    def __init__(self):
        if not (config.CLICKUP_TOKEN and config.CLICKUP_LIST_ID):
            raise RuntimeError("Set CLICKUP_TOKEN and CLICKUP_LIST_ID in .env")
        self.h = {"Authorization": config.CLICKUP_TOKEN}

    def create(self, f: Finding, evidence: Path, screen: str) -> str:
        r = requests.post(f"{self.API}/list/{config.CLICKUP_LIST_ID}/task", headers=self.h, timeout=30, json={
            "name": f"[Design QA] {f.title}",
            "markdown_content": ticket_body(f, screen),
            "priority": PRIORITY.get(f.severity, 3),
            "tags": ["design-qa", f.category],
        })
        r.raise_for_status()
        task = r.json()
        with open(evidence, "rb") as fh:
            requests.post(f"{self.API}/task/{task['id']}/attachment", headers=self.h, timeout=60,
                          files={"attachment": (evidence.name, fh, "image/png")}).raise_for_status()
        return task.get("url", task["id"])


class LinearTracker:
    name = "linear"
    API = "https://api.linear.app/graphql"

    def __init__(self):
        if not (config.LINEAR_API_KEY and config.LINEAR_TEAM_ID):
            raise RuntimeError("Set LINEAR_API_KEY and LINEAR_TEAM_ID in .env")
        self.h = {"Authorization": config.LINEAR_API_KEY, "Content-Type": "application/json"}

    def _gql(self, query: str, variables: dict) -> dict:
        r = requests.post(self.API, headers=self.h, json={"query": query, "variables": variables}, timeout=30)
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            raise RuntimeError(data["errors"])
        return data["data"]

    def _upload(self, path: Path) -> str:
        size = path.stat().st_size
        up = self._gql("""mutation($ct:String!,$fn:String!,$s:Int!){fileUpload(contentType:$ct,filename:$fn,size:$s){
            uploadFile{uploadUrl assetUrl headers{key value}}}}""",
                       {"ct": "image/png", "fn": path.name, "s": size})["fileUpload"]["uploadFile"]
        headers = {h["key"]: h["value"] for h in up["headers"]}
        headers.update({"Content-Type": "image/png", "Cache-Control": "public, max-age=31536000"})
        requests.put(up["uploadUrl"], data=path.read_bytes(), headers=headers, timeout=60).raise_for_status()
        return up["assetUrl"]

    def create(self, f: Finding, evidence: Path, screen: str) -> str:
        asset = self._upload(evidence)
        data = self._gql("""mutation($i:IssueCreateInput!){issueCreate(input:$i){issue{url}}}""", {"i": {
            "teamId": config.LINEAR_TEAM_ID, "title": f"[Design QA] {f.title}",
            "description": ticket_body(f, screen) + f"\n\n![evidence]({asset})",
            "priority": PRIORITY.get(f.severity, 3),
        }})
        return data["issueCreate"]["issue"]["url"]


def get_tracker(name: str, out_dir: Path):
    if name == "clickup":
        return ClickUpTracker()
    if name == "linear":
        return LinearTracker()
    return MarkdownTracker(out_dir)
