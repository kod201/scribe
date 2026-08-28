"""Download the pinned extraction model. Run once; everything after is offline.

Revision is pinned so `docs/bench.md` numbers are reproducible (PRD M0).
"""

import sys

from huggingface_hub import snapshot_download

REPO = "mlx-community/Qwen3-VL-30B-A3B-Instruct-8bit"
REVISION = "8794b4f0bce099a0ca7c40980ba7081527321e59"

def _write_main_ref(snapshot_path: str) -> None:
    """Point refs/main at the pinned sha.

    A sha-pinned snapshot_download writes no ref, and `scribe serve` runs the
    server under HF_HUB_OFFLINE=1, where resolving the repo id fails without
    one. The only snapshot on disk is the pinned one, so the ref cannot drift.
    """
    from pathlib import Path

    refs = Path(snapshot_path).parent.parent / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "main").write_text(REVISION)


if __name__ == "__main__":
    path = snapshot_download(
        repo_id=REPO,
        revision=REVISION,
        max_workers=8,
    )
    _write_main_ref(path)
    print(f"\nOK {REPO}@{REVISION[:7]}\n{path}", file=sys.stderr)
