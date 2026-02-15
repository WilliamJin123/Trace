"""Rebase and cherry-pick operations for Trace.

Implements commit replay with new parentage, EDIT target remapping detection,
and semantic safety checks for reordering.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tract.exceptions import CherryPickError, RebaseError, SemanticSafetyError
from tract.models.commit import CommitInfo, CommitOperation
from tract.models.merge import (
    CherryPickIssue,
    CherryPickResult,
    RebaseResult,
    RebaseWarning,
)
from tract.operations.dag import find_merge_base, get_all_ancestors, get_branch_commits

if TYPE_CHECKING:
    from tract.engine.commit import CommitEngine
    from tract.llm.protocols import ResolverCallable
    from tract.storage.repositories import (
        AnnotationRepository,
        BlobRepository,
        CommitParentRepository,
        CommitRepository,
        RefRepository,
    )
    from tract.storage.schema import CommitRow


def _row_to_info(row: CommitRow) -> CommitInfo:
    """Convert a CommitRow to CommitInfo."""
    return CommitInfo(
        commit_hash=row.commit_hash,
        tract_id=row.tract_id,
        parent_hash=row.parent_hash,
        content_hash=row.content_hash,
        content_type=row.content_type,
        operation=row.operation,
        response_to=row.response_to,
        message=row.message,
        token_count=row.token_count,
        metadata=row.metadata_json,
        generation_config=row.generation_config_json,
        created_at=row.created_at,
    )


def _load_content_model(blob_repo: BlobRepository, content_hash: str) -> object | None:
    """Load content from a blob and return a validated Pydantic model.

    Returns None if the blob cannot be found or parsed.
    """
    from tract.models.content import validate_content

    blob = blob_repo.get(content_hash)
    if blob is None:
        return None
    try:
        data = json.loads(blob.payload_json)
        return validate_content(data)
    except (json.JSONDecodeError, TypeError, Exception):
        return None


def replay_commit(
    original_row: CommitRow,
    new_parent_hash: str | None,
    commit_engine: CommitEngine,
    blob_repo: BlobRepository,
    *,
    response_to_remap: str | None = None,
) -> CommitInfo:
    """Replay a single commit with a new parent, creating a new commit.

    The caller must ensure HEAD is positioned at new_parent_hash before calling.
    The commit engine reads HEAD internally to set the parent.

    Args:
        original_row: The original CommitRow to replay.
        new_parent_hash: The new parent hash (for documentation; HEAD must be here).
        commit_engine: Commit engine for creating the new commit.
        blob_repo: Blob repository for loading original content.
        response_to_remap: If provided, override the response_to field.

    Returns:
        CommitInfo for the newly created replayed commit.

    Raises:
        RebaseError: If the original content cannot be loaded.
    """
    # Load original content model from blob
    content = _load_content_model(blob_repo, original_row.content_hash)
    if content is None:
        raise RebaseError(
            f"Cannot replay commit {original_row.commit_hash}: "
            f"blob {original_row.content_hash} not found or invalid"
        )

    # Determine response_to
    response_to = response_to_remap
    if response_to is None and original_row.response_to is not None:
        response_to = original_row.response_to

    # Create the new commit via the engine (engine reads HEAD for parent)
    return commit_engine.create_commit(
        content=content,  # type: ignore[arg-type]
        operation=original_row.operation,
        message=original_row.message,
        response_to=response_to if original_row.operation == CommitOperation.EDIT else None,
        metadata=dict(original_row.metadata_json) if original_row.metadata_json else None,
        generation_config=(
            dict(original_row.generation_config_json)
            if original_row.generation_config_json
            else None
        ),
    )


def cherry_pick(
    commit_hash: str,
    tract_id: str,
    commit_repo: CommitRepository,
    ref_repo: RefRepository,
    blob_repo: BlobRepository,
    commit_engine: CommitEngine,
    parent_repo: CommitParentRepository | None = None,
    *,
    resolver: ResolverCallable | None = None,
) -> CherryPickResult:
    """Cherry-pick a commit onto the current branch.

    Creates a new commit with the same content but new parentage (current HEAD).

    Args:
        commit_hash: Hash of the commit to cherry-pick.
        tract_id: The tract identifier.
        commit_repo: Commit repository.
        ref_repo: Ref repository.
        blob_repo: Blob repository.
        commit_engine: Commit engine for creating the new commit.
        parent_repo: Optional parent repository for multi-parent traversal.
        resolver: Optional resolver for handling issues.

    Returns:
        CherryPickResult describing the outcome.

    Raises:
        CherryPickError: If issues detected and no resolver, or resolver aborts.
    """
    # Get the commit to cherry-pick
    original_row = commit_repo.get(commit_hash)
    if original_row is None:
        raise CherryPickError(f"Commit not found: {commit_hash}")

    original_info = _row_to_info(original_row)

    # Get current HEAD
    current_head = ref_repo.get_head(tract_id)

    # Build target branch head info for issue context
    target_head_info = None
    if current_head is not None:
        target_row = commit_repo.get(current_head)
        if target_row is not None:
            target_head_info = _row_to_info(target_row)

    # Check for issues
    issues: list[CherryPickIssue] = []

    if original_row.operation == CommitOperation.EDIT and original_row.response_to is not None:
        # Check if the response_to target exists in current branch's history
        if current_head is not None:
            ancestors = get_all_ancestors(current_head, commit_repo, parent_repo)
            if original_row.response_to not in ancestors:
                issues.append(
                    CherryPickIssue(
                        issue_type="edit_target_missing",
                        commit=original_info,
                        target_branch_head=target_head_info,
                        missing_target=original_row.response_to,
                        description=(
                            f"EDIT commit targets {original_row.response_to[:12]}... "
                            f"which does not exist on the current branch"
                        ),
                    )
                )
        else:
            # No commits on current branch, EDIT target definitely missing
            issues.append(
                CherryPickIssue(
                    issue_type="edit_target_missing",
                    commit=original_info,
                    target_branch_head=None,
                    missing_target=original_row.response_to,
                    description=(
                        f"EDIT commit targets {original_row.response_to[:12]}... "
                        f"but current branch has no commits"
                    ),
                )
            )

    # Handle issues
    resolved_content = None
    if issues:
        if resolver is None:
            raise CherryPickError(
                f"Cherry-pick has {len(issues)} issue(s): "
                + "; ".join(i.description for i in issues)
            )

        # Call resolver for each issue
        for issue in issues:
            resolution = resolver(issue)
            if resolution.action == "abort":
                raise CherryPickError(
                    f"Resolver aborted cherry-pick: {resolution.reasoning}"
                )
            if resolution.action == "skip":
                return CherryPickResult(
                    original_commit=original_info,
                    new_commit=None,
                    issues=issues,
                )
            if resolution.action == "resolved" and resolution.content_text is not None:
                resolved_content = resolution.content_text

    # Create the new commit
    if resolved_content is not None:
        # Use resolved content -- create as APPEND since EDIT target is missing
        from tract.models.content import FreeformContent

        new_content = FreeformContent(payload={"text": resolved_content})
        new_info = commit_engine.create_commit(
            content=new_content,
            operation=CommitOperation.APPEND,
            message=original_row.message,
            metadata=dict(original_row.metadata_json) if original_row.metadata_json else None,
            generation_config=(
                dict(original_row.generation_config_json)
                if original_row.generation_config_json
                else None
            ),
        )
    else:
        # Normal replay -- HEAD is already at current branch tip
        new_info = replay_commit(
            original_row=original_row,
            new_parent_hash=current_head,
            commit_engine=commit_engine,
            blob_repo=blob_repo,
        )

    return CherryPickResult(
        original_commit=original_info,
        new_commit=new_info,
        issues=issues,
    )


def rebase(
    tract_id: str,
    target_branch: str,
    commit_repo: CommitRepository,
    ref_repo: RefRepository,
    parent_repo: CommitParentRepository | None,
    blob_repo: BlobRepository,
    commit_engine: CommitEngine,
    annotation_repo: AnnotationRepository | None = None,
    *,
    resolver: ResolverCallable | None = None,
) -> RebaseResult:
    """Rebase the current branch onto a target branch.

    Replays commits from the current branch onto the target branch tip,
    producing new commits with new hashes and parentage.

    Args:
        tract_id: The tract identifier.
        target_branch: Name of the branch to rebase onto.
        commit_repo: Commit repository.
        ref_repo: Ref repository.
        parent_repo: Parent repository for multi-parent traversal.
        blob_repo: Blob repository.
        commit_engine: Commit engine for creating replayed commits.
        annotation_repo: Annotation repository (optional).
        resolver: Optional resolver for semantic safety warnings.

    Returns:
        RebaseResult describing the outcome.

    Raises:
        RebaseError: On merge commits in range, resolver abort, or other errors.
        SemanticSafetyError: If safety warnings detected and no resolver.
    """
    # Get current branch
    current_branch = ref_repo.get_current_branch(tract_id)
    if current_branch is None:
        raise RebaseError("Cannot rebase in detached HEAD state")

    current_tip = ref_repo.get_head(tract_id)
    if current_tip is None:
        raise RebaseError("Cannot rebase: no commits on current branch")

    # Get target branch tip
    target_tip = ref_repo.get_branch(tract_id, target_branch)
    if target_tip is None:
        from tract.exceptions import BranchNotFoundError

        raise BranchNotFoundError(target_branch)

    # If current tip is already an ancestor of target (or same), nothing to do
    if current_tip == target_tip:
        return RebaseResult(new_head=current_tip)

    # Find merge base
    merge_base = find_merge_base(commit_repo, parent_repo, current_tip, target_tip)

    # If target is already an ancestor of current (current is ahead), nothing to replay
    if merge_base == target_tip:
        return RebaseResult(new_head=current_tip)

    # Collect commits to replay (merge_base..current_tip, chronological order)
    if merge_base is not None:
        commits_to_replay = get_branch_commits(commit_repo, parent_repo, current_tip, merge_base)
    else:
        # No common ancestor -- replay all commits on current branch
        commits_to_replay = list(reversed(list(commit_repo.get_ancestors(current_tip))))

    if not commits_to_replay:
        return RebaseResult(new_head=current_tip)

    # Pre-flight: block if any commit in replay range has merge parents
    if parent_repo is not None:
        for c in commits_to_replay:
            parents = parent_repo.get_parents(c.commit_hash)
            if parents:
                raise RebaseError("Cannot rebase branch containing merge commits")

    # Build info list for original commits
    original_infos = [_row_to_info(c) for c in commits_to_replay]

    # Get target branch ancestors for EDIT target checking
    target_ancestors = get_all_ancestors(target_tip, commit_repo, parent_repo)

    # Semantic safety checks
    warnings: list[RebaseWarning] = []

    # Get target tip info for warning context
    target_tip_row = commit_repo.get(target_tip)
    target_tip_info = _row_to_info(target_tip_row) if target_tip_row else None

    for original_row, original_info in zip(commits_to_replay, original_infos):
        if original_row.operation == CommitOperation.EDIT and original_row.response_to is not None:
            # Check if EDIT target exists in target branch history
            if original_row.response_to not in target_ancestors:
                warnings.append(
                    RebaseWarning(
                        warning_type="edit_target_missing",
                        commit=original_info,
                        new_base=target_tip_info,
                        description=(
                            f"EDIT commit targets {original_row.response_to[:12]}... "
                            f"which does not exist on target branch '{target_branch}'"
                        ),
                    )
                )

    # Handle warnings
    if warnings:
        if resolver is None:
            raise SemanticSafetyError(
                f"Rebase has {len(warnings)} semantic safety warning(s): "
                + "; ".join(w.description for w in warnings)
            )

        for warning in warnings:
            resolution = resolver(warning)
            if resolution.action == "abort":
                raise RebaseError(
                    f"Resolver aborted rebase: {resolution.reasoning}"
                )
            # "resolved" or "skip" -- continue with the rebase

    # Replay commits atomically
    # Move HEAD to target branch tip (detach)
    ref_repo.detach_head(tract_id, target_tip)

    try:
        replayed_infos: list[CommitInfo] = []
        current_replay_parent = target_tip

        for original_row in commits_to_replay:
            # Replay the commit -- HEAD is at current_replay_parent
            new_info = replay_commit(
                original_row=original_row,
                new_parent_hash=current_replay_parent,
                commit_engine=commit_engine,
                blob_repo=blob_repo,
            )
            replayed_infos.append(new_info)
            current_replay_parent = new_info.commit_hash

        # Update current branch ref to point at the last replayed commit
        new_head = replayed_infos[-1].commit_hash
        ref_repo.set_branch(tract_id, current_branch, new_head)

        # Re-attach HEAD to the current branch
        ref_repo.attach_head(tract_id, current_branch)

    except Exception:
        # On any failure, re-attach HEAD to original branch position
        # The session will be rolled back by the caller (Tract facade)
        ref_repo.set_branch(tract_id, current_branch, current_tip)
        ref_repo.attach_head(tract_id, current_branch)
        raise

    return RebaseResult(
        replayed_commits=replayed_infos,
        original_commits=original_infos,
        warnings=warnings,
        new_head=new_head,
    )
