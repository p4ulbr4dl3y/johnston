"""Storage port interfaces for session persistence and metadata."""

from typing import Any, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class SessionStorePort(Protocol):
    """Port defining session storage and retrieval operations."""

    def generate_session_id(self) -> str:
        """Generates a unique main session identifier."""
        ...

    def generate_subagent_id(self) -> str:
        """Generates a unique subagent session identifier."""
        ...

    def create_main(self, session_id: str, system_prompt: Optional[str] = None) -> Any:
        """Creates a new main session."""
        ...

    def get_session(self, session_id: str) -> Optional[Any]:
        """Retrieves a session by identifier."""
        ...

    def save_session(self, session: Any) -> None:
        """Persists a session to storage."""
        ...

    def delete_session(self, session_id: str) -> bool:
        """Deletes a session from storage."""
        ...

    def list_sessions(self) -> List[Any]:
        """Lists all main sessions."""
        ...
