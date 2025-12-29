from typing import Optional
from pathlib import Path
from uuid import uuid4
from os import environ
from time import time

from .constants import DATA_ENV_VARIABLE, DIR_REQUESTS_BUFFER, DIR_RESPONSES
from .exceptions import APIERClientError


class Preprocessor:
    def __init__(
            self,
            env_data_variable: str = DATA_ENV_VARIABLE,
            dir_requests_buffer = Path(DIR_REQUESTS_BUFFER),
            large_requests_enabled: bool = True,
        ):
        """
        Initialize the request preprocessor.

        Args:
            env_data_variable: Name of the environment variable that carries request data.
            dir_requests_buffer: Base directory used to store current requests and leftovers.
            large_requests_enabled: Whether multipart (MP_...) requests are supported.
        """
        self.env_data_variable = env_data_variable
        self.dir_request = dir_requests_buffer / "current"
        self.dir_request_leftovers = dir_requests_buffer / "leftovers"
        self.__support_large_requests = large_requests_enabled
        self.dir_request.mkdir(parents=True, exist_ok=True)
        self.dir_request_leftovers.mkdir(parents=True, exist_ok=True)

    def save_request(self) -> Optional[str]:
        """
        Persist request data from the environment into buffered storage.

        Supports multipart payloads prefixed with 'MP_' that arrive in parts.

        Returns:
            The full assembled request data if all parts are present and moved to the
            current request directory; otherwise None (waiting for more parts or no data).

        Raises:
            APIERClientError: If large requests are disabled or multipart data is malformed.
        """
        if not environ.get(self.env_data_variable):
            return None

        # Load request data from environment variable
        requests_data = environ[self.env_data_variable]

        # Handle large requests
        if requests_data.startswith('MP_'):
            if not self.__support_large_requests:
                raise APIERClientError("Large requests not supported")
            parts = requests_data.split('_')
            try:
                if parts[0] != 'MP':
                    raise ValueError("Invalid prefix")
                request_id = parts[1]
                part_index = int(parts[2])
                parts_total = int(parts[3])
                part_data = parts[4]
            except (IndexError, ValueError):
                raise APIERClientError("Invalid large request data")
        # Handle normal requests
        else:
            request_id = str(uuid4())
            part_index = 1
            parts_total = 1
            part_data = requests_data

        # Save the part data to a leftover file
        request_leftover_dir = self.dir_request_leftovers / request_id
        request_leftover_dir.mkdir(parents=True, exist_ok=True)
        part_file = request_leftover_dir / f"part_{part_index:04d}.txt"
        part_file.write_text(part_data)
        time_file = request_leftover_dir / f"time.txt"
        time_file.write_text(str(int(time())))
        
        # If all parts are not yet received, return None
        parts_saved_count = len(list(request_leftover_dir.glob("part_*.txt"))) 
        if parts_saved_count != parts_total:
            print(f"[*] Waiting for more parts for request {request_id} ({parts_saved_count}/{parts_total})")
            return None

        # Assemble full request data inside the main request directory
        full_request_data = ''
        for file in sorted(request_leftover_dir.glob("part_*.txt")):
            full_request_data += file.read_text()
        final_request_file = self.dir_request / f"{request_id}.txt"
        final_request_file.write_text(full_request_data)

        # Clean up leftover parts
        for file in request_leftover_dir.glob("*.txt"):
            file.unlink()
        request_leftover_dir.rmdir()
        return full_request_data

    def load_request(self) -> Optional[str]:
        """
        Load a single request from the current requests directory.

        If no current request exists, attempts to save one from the environment
        and returns its data.

        Returns:
            The loaded request data, or None if no data is available.
        """
        request_files = list(self.dir_request.glob("*.txt"))
        if not request_files:
            return self.save_request()
        request_file = request_files[0]
        request_data = request_file.read_text()
        request_file.unlink()
        return request_data

    def delete_old_requests(self, max_age_seconds: int = 3600):
        """
        Remove leftover multipart request fragments older than the given age.

        Args:
            max_age_seconds: Age threshold in seconds for cleanup of leftovers.
        """
        current_time = int(time())
        for request_dir in self.dir_request_leftovers.iterdir():
            if not request_dir.is_dir():
                continue
            time_file = request_dir / "time.txt"
            delete = False
            try:
                request_time = int(time_file.read_text())
                delete = (current_time - request_time) > max_age_seconds
            except (FileNotFoundError, ValueError):
                delete = True
            if delete:
                for file in request_dir.glob("*"):
                    file.unlink()
                request_dir.rmdir()
                print(f"[*] Cleaned up old requests in {request_dir.name}")

def main() -> None:
    """
    Entry point to save a request from the environment and cleanup leftovers.
    """
    preprocessor = Preprocessor()
    request_file = preprocessor.save_request()
    if request_file:
        print(f"[*] Saved request data to file.")
    else:
        print(f"[*] No request data found in environment variable.")
    preprocessor.delete_old_requests()


if __name__ == "__main__":
    main()
