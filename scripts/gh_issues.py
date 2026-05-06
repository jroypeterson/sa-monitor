"""GitHub Issues helper for sa-monitor and sibling projects.

Reads a fine-grained PAT from `Claude Folder/.secrets/gh_pat_claude_issues.txt`
(or from the GH_PAT_CLAUDE_ISSUES env var) and exposes a tiny client around
the issues-only subset of the GitHub REST API. Designed for Cowork-driven
operations across all jroypeterson/* repos.

Required token scopes (fine-grained PAT):
- Resource owner: jroypeterson
- Repository access: All repositories (or selected list including target repos)
- Repository permissions: Issues = Read and write (everything else: No access)
- Account permissions: none

Usage (from another script or REPL):

    from gh_issues import (
        verify_token,
        create_issue,
        list_issues,
        get_issue,
        comment_on_issue,
        close_issue,
    )

    verify_token()                                          # raises on failure
    issue = create_issue(
        repo="jroypeterson/coverage-manager",
        title="...",
        body=open("cm-issue-draft.md").read(),
        labels=["data-quality"],
    )
    print(issue["html_url"])
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---- Paths ----------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_FOLDER = REPO_ROOT.parent
TOKEN_FILE = CLAUDE_FOLDER / ".secrets" / "gh_pat_claude_issues.txt"

# ---- Token loading --------------------------------------------------------


def _load_token() -> str:
    env = os.environ.get("GH_PAT_CLAUDE_ISSUES")
    if env:
        return env.strip()
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    raise SystemExit(
        f"No GH PAT found. Set GH_PAT_CLAUDE_ISSUES env var or create "
        f"{TOKEN_FILE} (one line, token only)."
    )


# ---- Output redaction (defense-in-depth) ----------------------------------

_PAT_RE = re.compile(r"github_pat_[A-Za-z0-9_]+|ghp_[A-Za-z0-9]{20,}|ghs_[A-Za-z0-9]+")


def _redact(text: str) -> str:
    """Strip any literal token from output before printing or writing."""
    return _PAT_RE.sub("<REDACTED_GH_TOKEN>", text)


# ---- HTTP helpers ---------------------------------------------------------

API = "https://api.github.com"


def _request(method: str, path: str, *, body: dict | None = None) -> dict:
    url = path if path.startswith("http") else f"{API}{path}"
    token = _load_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "sa-monitor-gh-issues/1.0 (+jroypeterson)",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None
    if data:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(
            f"GitHub API {method} {path} failed: HTTP {e.code} {e.reason}. "
            f"Body: {_redact(body_text)[:1000]}"
        ) from None


# ---- Public API -----------------------------------------------------------


def verify_token() -> dict:
    """GET /user — confirms token is valid + returns the authenticated user.

    Raises if the token is invalid, expired, or has insufficient scope to
    read the user record. Does NOT print the token under any condition.
    """
    user = _request("GET", "/user")
    return {
        "login": user.get("login"),
        "id": user.get("id"),
        "name": user.get("name"),
        "type": user.get("type"),
    }


def create_issue(
    repo: str,
    title: str,
    body: str,
    *,
    labels: list[str] | None = None,
    assignees: list[str] | None = None,
) -> dict:
    """Create an issue in `owner/repo`."""
    payload: dict = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    if assignees:
        payload["assignees"] = assignees
    return _request("POST", f"/repos/{repo}/issues", body=payload)


def list_issues(repo: str, state: str = "open", per_page: int = 30) -> list[dict]:
    """List issues in `owner/repo`. state in {"open","closed","all"}."""
    qs = urllib.parse.urlencode({"state": state, "per_page": per_page})
    return _request("GET", f"/repos/{repo}/issues?{qs}")  # type: ignore[return-value]


def get_issue(repo: str, number: int) -> dict:
    return _request("GET", f"/repos/{repo}/issues/{number}")


def comment_on_issue(repo: str, number: int, body: str) -> dict:
    return _request(
        "POST", f"/repos/{repo}/issues/{number}/comments", body={"body": body}
    )


def close_issue(repo: str, number: int) -> dict:
    return _request("PATCH", f"/repos/{repo}/issues/{number}", body={"state": "closed"})


# ---- CLI for sanity checks -----------------------------------------------

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="GH issues helper")
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("verify", help="GET /user — verify token works")
    li = sp.add_parser("list", help="List issues")
    li.add_argument("repo")
    li.add_argument("--state", default="open")

    args = p.parse_args()
    if args.cmd == "verify":
        u = verify_token()
        print(json.dumps(u, indent=2))
    elif args.cmd == "list":
        issues = list_issues(args.repo, state=args.state)
        for i in issues:
            print(f"#{i['number']:<5} [{i['state']:>6}] {i['title']}")
