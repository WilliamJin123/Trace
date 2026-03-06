"""ConfigIndex: per-key config resolution from DAG ancestry."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tract.storage.repositories import (
        AnnotationRepository,
        BlobRepository,
        CommitParentRepository,
        CommitRepository,
    )


class ConfigIndex:
    """Per-key config resolution from DAG ancestry.

    Walks ancestry, collects content_type="config" commits, resolves
    per-key with DAG precedence (closer to HEAD wins).
    """

    def __init__(self) -> None:
        self._settings: dict[str, tuple[Any, int]] = {}  # key -> (value, dag_distance)
        self._stale: bool = False

    @classmethod
    def build(
        cls,
        commit_repo: CommitRepository,
        blob_repo: BlobRepository,
        head_hash: str,
        *,
        parent_repo: CommitParentRepository | None = None,
        annotation_repo: AnnotationRepository | None = None,
    ) -> ConfigIndex:
        """Build index by walking ancestry and collecting config commits."""
        from tract.operations.ancestry import walk_ancestry

        idx = cls()
        config_commits = walk_ancestry(
            commit_repo, blob_repo, head_hash,
            content_type_filter={"config"},
            parent_repo=parent_repo,
        )
        # config_commits is root-first; distance = len - 1 - i (so HEAD-closest = 0)
        total = len(config_commits)
        for i, commit_row in enumerate(config_commits):
            distance = total - 1 - i
            blob = blob_repo.get(commit_row.content_hash)
            if blob is None:
                continue
            payload = json.loads(blob.payload_json)
            settings = payload.get("settings", {})
            for key, value in settings.items():
                existing = idx._settings.get(key)
                if existing is None or distance < existing[1]:
                    idx._settings[key] = (value, distance)
        return idx

    def get(self, key: str, default: Any = None) -> Any:
        """Resolve a config value. None values are treated as 'not set'."""
        entry = self._settings.get(key)
        if entry is None:
            return default
        value = entry[0]
        if value is None:
            return default
        return value

    def get_all(self) -> dict[str, Any]:
        """Resolve all config key-value pairs (excluding None/unset)."""
        return {
            key: val for key, (val, _dist) in self._settings.items()
            if val is not None
        }

    def invalidate(self) -> None:
        """Mark index as stale (requires rebuild on next access)."""
        self._stale = True

    @property
    def is_stale(self) -> bool:
        return self._stale

    def __len__(self) -> int:
        return len(self._settings)
