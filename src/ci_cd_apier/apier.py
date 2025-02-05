import json
from uuid import UUID
from pathlib import Path
from typing import Dict, Callable, Optional
from os import getcwd, environ
from traceback import print_exc
from datetime import datetime, timezone

from ssage import SSAGE


class APIERClientError(Exception):
    """
    Raised when there is an error in the client request
    """
    pass


class APIERServerError(Exception):
    """
    Raised when there is an error in the server response
    """
    def __init__(self, message: str, request_id: str, request_age_public_key: str, parent: Exception):
        super().__init__(message, parent)
        self.request_id = request_id
        self.request_age_public_key = request_age_public_key


class APIER:
    """
    APIER class to have Flask-like routing for CI/CD requests
    """

    def __init__(self, age_key: str, dir_responses: Optional[Path] = None):
        """
        Initialize the APIER object
        :param age_key: local secret key
        :param dir_responses: directory to store responses
        """
        self.__decryptor = SSAGE(age_key)
        self.__dir_responses = dir_responses or (Path(getcwd()) / "responses")
        self.__paths: Dict[str, Callable[[any], str]] = {}

    def register_path(self, path: str, handler: Callable[[any], str]) -> None:
        """
        Register a path with a handler
        :param path: virtual request path
        :param handler: function to handle the request
        :return: None
        """
        self.__paths[path] = handler

    def route(self, path: str):
        """
        Decorator to register a path with a handler
        :param path: virtual request path
        :return: decorator
        """
        def decorator(func: Callable[[any], str]):
            self.register_path(path, func)
            return func
        return decorator

    def process_requests(
            self,
            data_env_name: str = "APIER_DATA",
            empty_ok: bool = True,
            always_success: bool = True,
            delete_old_responses: bool = True
    ) -> None:
        """
        Process the current request stored in the environment variable
        :param data_env_name: name of the environment variable containing the request
        :param empty_ok: if True, do not raise an error if there is no request
        :param always_success: if True, do not raise an error if there is an exception
        :param delete_old_responses: if True, delete old responses
        :return: None
        """
        # noinspection PyBroadException
        try:
            if delete_old_responses:
                self.purge_old_responses()
            data = environ.get(data_env_name)
            if not data:
                if empty_ok:
                    print('[*] No request to process')
                    return
                raise APIERClientError(f"Missing request data: {data_env_name}")
            self.process_single_request(data)
        except Exception:
            if always_success:
                print_exc()
            else:
                raise

    def process_single_request(self, request_raw: str) -> None:
        """
        Process a single request and saves the response to responses directory
        :param request_raw: raw request data
        :return: None
        """
        exception = None

        try:
            request_str = self.__decryptor.decrypt(request_raw)
        except Exception as e:
            raise APIERClientError(f"Request decryption failed: {e}", e)

        try:
            request = json.loads(request_str)
        except json.JSONDecodeError as e:
            raise APIERClientError(f"Request parsing failed: {e}", e)

        try:
            request_path = request["path"]
            request_id = request["id"]
            request_age_public_key = request["age_public_key"]
            request_data = request["data"]
        except KeyError as e:
            raise APIERClientError(f"Request missing required fields: {e}", e)

        try:
            UUID(request_id)
        except ValueError:
            raise APIERClientError(f"Invalid request_id: {request_id}")

        print(f'[*] Processing request {request_id}')

        request_handler = self.__paths.get(request_path)
        if request_path is None:
            raise APIERClientError(f"Path not registered: {request_path}")

        try:
            response_data = request_handler(request_data)
            status = 'success'
        except Exception as e:
            status = 'error'
            response_data = 'There was an internal error while processing the request'
            exception = APIERServerError(f"Request handler failed: {e}", request_id, request_age_public_key, e)

        try:
            response = json.dumps({
                "id": request_id,
                "status": status,
                "data": response_data,
                "date": datetime.now(tz=timezone.utc).isoformat()
            })
        except Exception as e:
            raise APIERServerError(f"Cannot serialize answer: {e}", request_id, request_age_public_key, e)

        try:
            response_encrypted = self.__decryptor.encrypt(response, additional_recipients=[request_age_public_key])
        except Exception as e:
            raise APIERClientError(f"Response encryption failed: {e}", e)

        path_response = self.__dir_responses / f"{Path(request_id).name}.txt"
        path_response.write_text(response_encrypted)

        if exception:
            raise exception

    def purge_old_responses(self, minutes: int = 1) -> None:
        """
        Purge old responses from the responses directory
        :param minutes: minutes to keep the response
        :return: None
        """
        now = datetime.now(tz=timezone.utc)
        for file in self.__dir_responses.glob("*.txt"):
            try:
                content = json.loads(self.__decryptor.decrypt(file.read_text()))
                date = datetime.fromisoformat(content["date"])
                if (now - date).total_seconds() / 60 > minutes:
                    print(f'[*] Purging old response {file.name}')
                    file.unlink()
            except Exception as e:
                print(f'[!] Error while purging response {file.name}: {e}')
                file.unlink()

    @property
    def public_key(self) -> str:
        """
        Local AGE public key
        :return: public key
        """
        return self.__decryptor.public_key
