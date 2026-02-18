"""Built-in policies for Trace's policy engine.

Provides four ready-to-use policies:
- CompressPolicy: Auto-compress when token usage exceeds threshold
- PinPolicy: Auto-pin commits based on content type
- BranchPolicy: Detect content type tangents and propose branching
- RebasePolicy: Detect stale branches and propose archiving
"""

from tract.policy.builtin.branch import BranchPolicy
from tract.policy.builtin.compress import CompressPolicy
from tract.policy.builtin.pin import PinPolicy
from tract.policy.builtin.rebase import RebasePolicy

__all__ = [
    "CompressPolicy",
    "PinPolicy",
    "BranchPolicy",
    "RebasePolicy",
]
