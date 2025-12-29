from pathlib import Path
from time import time

from .constants import DIR_RESPONSES, DIR_RESPONSES_BUFFER

class Postprocessor:
    def __init__(
            self,
            dir_responses: Path = Path(DIR_RESPONSES),
            dir_responses_buffer: Path = Path(DIR_RESPONSES_BUFFER),
        ):
        """
        Initialize the response postprocessor.

        Args:
            dir_responses: Directory where final encrypted responses are stored.
            dir_responses_buffer: Base directory used for buffering and leftovers.
        """
        self.dir_responses = dir_responses
        self.dir_responses_buffer = dir_responses_buffer / "leftovers"
        self.dir_responses_buffer.mkdir(parents=True, exist_ok=True)
        self.dir_responses.mkdir(parents=True, exist_ok=True)

    def save_response(self, response_id: str, response_data: str) -> None:
        """
        Save an encrypted response and its timestamp to the responses directory.

        Args:
            response_id: Unique identifier of the request/response.
            response_data: Encrypted response payload to persist.
        """
        response_file = self.dir_responses / f"{response_id}.txt"
        response_file.write_text(response_data)
        response_file.with_name(f"{response_id}.time.txt").write_text(str(int(time())))

    def delete_old_responses(self, max_age_seconds: int = 300):
        """
        Delete buffered response files older than the provided age threshold.

        Args:
            max_age_seconds: Age threshold in seconds for cleanup.
        """
        current_time = int(time())
        for response_time_file in self.dir_responses_buffer.glob("*.time.txt"):
            try:
                response_time = int(response_time_file.read_text())
                if (current_time - response_time) > max_age_seconds:
                    response_file = self.dir_responses / response_time_file.name.replace(".time.txt", ".txt")
                    if response_file.exists():
                        response_file.unlink()
                    response_time_file.unlink()
                    print(f"[*] Cleaned up old response {response_time_file.name}")
            except (FileNotFoundError, ValueError):
                response_time_file.unlink()

    def copy_responses_from_buffer(self) -> None:
        """
        Move buffered response payloads into the main responses directory.
        Skips timestamp files.
        """
        for response_file in self.dir_responses_buffer.glob("*.txt"):
            if response_file.name.endswith(".time.txt"):
                continue
            target_file = self.dir_responses / response_file.name
            target_file.write_text(response_file.read_text())
            response_file.unlink()

    def copy_responses_to_buffer(self) -> None:
        """
        Copy new responses from the main directory into the buffer directory
        when a buffered counterpart does not yet exist.
        """
        for response_file in self.dir_responses.glob("*.txt"):
            buffer_file = self.dir_responses_buffer / response_file.name
            if not buffer_file.exists():
                buffer_file.write_text(response_file.read_text())


def main() -> None:
    """
    Entry point for periodic response maintenance: cleanup and sync.
    """
    postprocessor = Postprocessor()
    postprocessor.delete_old_responses()
    postprocessor.copy_responses_from_buffer()
    postprocessor.copy_responses_to_buffer()


if __name__ == "__main__":
    main()
