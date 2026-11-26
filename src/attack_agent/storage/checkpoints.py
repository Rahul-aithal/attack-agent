"""Session checkpoints: the full AgentState as JSON in ``<output_dir>/checkpoints/<id>.json``.

Written after every turn and phase change, so a session survives a server restart and a
participant can rejoin with their code and continue where they left off. Plain files keep this
independent of the SQLite store (which only receives a session once it ends).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from attack_agent.state import AgentState


def checkpoint_dir(output_dir: Path | str) -> Path:
    return Path(output_dir) / "checkpoints"


def save_checkpoint(state: AgentState, output_dir: Path | str) -> Path:
    folder = checkpoint_dir(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{state.session_id}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(), encoding="utf-8")
    os.replace(tmp, path)  # atomic: a crash mid-write never leaves a broken checkpoint
    return path


def load_checkpoint(session_id: str, output_dir: Path | str) -> AgentState | None:
    if not session_id or "/" in session_id or "\\" in session_id or ".." in session_id:
        return None
    path = checkpoint_dir(output_dir) / f"{session_id}.json"
    if not path.exists():
        return None
    try:
        return AgentState.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def delete_checkpoint(session_id: str, output_dir: Path | str) -> bool:
    if not session_id or "/" in session_id or "\\" in session_id or ".." in session_id:
        return False
    path = checkpoint_dir(output_dir) / f"{session_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def list_checkpoints(output_dir: Path | str) -> list[dict]:
    """Light summaries of every saved session (newest first)."""
    rows = []
    for path in checkpoint_dir(output_dir).glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append(data)
    rows.sort(key=lambda d: d.get("started_at") or "", reverse=True)
    return rows


def find_by_join_code(code: str, output_dir: Path | str) -> str | None:
    for data in list_checkpoints(output_dir):
        if data.get("join_code") == code:
            return data.get("session_id")
    return None
