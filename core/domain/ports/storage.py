"""Storage port interfaces for session persistence and metadata."""

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from core.domain.entities.session import AgentSession


@runtime_checkable
class SessionStorePort(Protocol):
    """Port defining session storage and retrieval operations."""

    def generate_session_id(self) -> str:
        """Generates a unique main session identifier."""
        ...

    def generate_subagent_id(self) -> str:
        """Generates a unique subagent session identifier."""
        ...

    def create_main(self, session_id: Optional[str] = None, role: str = "worker") -> AgentSession:
        """Creates a new main session."""
        ...

    def create_subagent(
        self,
        parent_id: str,
        subagent_id: Optional[str] = None,
        role: str = "worker",
        title: str = "",
        prompt: str = "",
        status: str = "running",
        project_dir: str = "",
        branch_name: str = "",
        background: bool = True,
    ) -> AgentSession:
        """Creates a new subagent session."""
        ...

    def get(self, session_id: str, reload: bool = True) -> Optional[AgentSession]:
        """Retrieves a session by identifier."""
        ...

    def list(self, kind: Optional[str] = None) -> List[AgentSession]:
        """Lists all sessions for current project."""
        ...

    def list_main_sessions(self) -> List[Dict[str, Any]]:
        """Lists non-empty main sessions sorted by updated time."""
        ...

    def children(self, parent_id: str) -> List[AgentSession]:
        """Lists child subagent sessions for a parent session."""
        ...

    def save(self, session: AgentSession) -> None:
        """Persists a session to storage."""
        ...

    async def save_async(self, session: AgentSession) -> None:
        """Asynchronously persists a session to storage."""
        ...

    def delete(self, session_id: str) -> None:
        """Deletes a session from storage."""
        ...

    def set_active_session_id(self, session_id: str) -> None:
        """Sets active session ID for the project."""
        ...

    def find_session_by_title_or_id(
        self, identifier: str, parent_id: Optional[str] = None
    ) -> Optional[AgentSession]:
        """Finds session by ID or title search."""
        ...

    def is_session_locked(self, session_id: str) -> bool:
        """Checks if session is locked."""
        ...

    def acquire_session_lock(self, session_id: str) -> bool:
        """Acquires lock on session."""
        ...

    def release_session_lock(self, session_id: str) -> None:
        """Releases session lock."""
        ...

    def release_all_locks(self) -> None:
        """Releases all held session locks."""
        ...

    def steal_session_lock(self, session_id: str) -> bool:
        """Steals session lock from another process."""
        ...

    def fork_session(
        self,
        session_id: str,
        new_title: Optional[str] = None,
        up_to_msg_index: Optional[int] = None,
    ) -> Optional[AgentSession]:
        """Forks a session."""
        ...

