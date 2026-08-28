"""Checkpoint manager port interface and resolution."""

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class CheckpointPort(Protocol):
    """Port defining the checkpoint management interface."""

    def is_valid_checkpoint_target(self, project_path: Optional[str] = None) -> bool:
        """Checks if target path is a valid git workspace and safe for checkpoints."""
        ...

    def create_checkpoint(
        self,
        session_id: str,
        message_index: int,
        project_path: Optional[str] = None,
        auto_init: bool = True,
    ) -> Optional[str]:
        """Creates a shadow git commit containing tracked & untracked working tree state."""
        ...

    def restore_checkpoint(
        self,
        session_id: str,
        message_index: int,
        project_path: Optional[str] = None,
    ) -> bool:
        """Restores repository working tree state to saved checkpoint."""
        ...

    def purge_checkpoints_after(
        self,
        session_id: str,
        target_message_index: int,
        project_path: Optional[str] = None,
    ) -> None:
        """Retires checkpoints with index > target_message_index for given session."""
        ...

    def get_diff_details_batch(
        self,
        session_id: str,
        message_indices: list[int],
        project_path: Optional[str] = None,
    ) -> dict[int, Optional[tuple[str, list[str]]]]:
        """Calculates line changes and changed files between checkpoints and current workspace."""
        ...

    def get_checkpoint_diff(
        self,
        session_id: str,
        message_index: Optional[int] = None,
        project_path: Optional[str] = None,
    ) -> list[tuple[str, str, int, int]]:
        """Calculates full diff between a session checkpoint and current workspace."""
        ...


_default_checkpoint_manager: Optional[CheckpointPort] = None


def set_default_checkpoint_manager(manager: Optional[CheckpointPort]) -> None:
    """Sets or overrides the default checkpoint manager port implementation."""
    global _default_checkpoint_manager
    _default_checkpoint_manager = manager


def get_checkpoint_manager() -> Optional[CheckpointPort]:
    """Resolves the active checkpoint manager port implementation."""
    global _default_checkpoint_manager
    return _default_checkpoint_manager

