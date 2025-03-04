import json
from enum import Enum
from uuid import UUID
from pathlib import Path
from typing import Dict, Callable, Optional, TypedDict
from os import getcwd, environ
from traceback import print_exc
from datetime import datetime, timezone
from shutil import copytree

from ssage import SSAGE
import jinja2
from jinja2.sandbox import SandboxedEnvironment

from .patcher import patch_html, APIERClientConfig


class APIEREndpointMode(Enum):
    API = "api"
    TEMPLATE = "template"
    RAW = "raw"


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
        self.parent = parent


class APIERGitlabClientConfig(TypedDict):
    """
    Configuration for the client
    """
    gitlab_pipeline_endpoint: str
    gitlab_token: str
    gitlab_branch: Optional[str]


class APIER:
    """
    APIER class to have Flask-like routing for CI/CD requests
    """

    def __init__(self,
                 age_key: str,
                 dir_webpage: Optional[Path] = None,
                 dir_responses: Optional[Path] = None,
                 dir_templates: Optional[Path] = None,
                 dir_static: Optional[Path] = None,
                 dir_requests: Optional[Path] = None,
                 support_large_requests: bool = True,
                 client_config: Optional[APIERGitlabClientConfig] = None
                 ):
        """
        Initialize the APIER object
        :param age_key: local secret key
        :param dir_webpage: directory to store all webpages, defaults to public in the current directory
        :param dir_responses: directory to store responses, defaults to apier-responses in webpage or the current directory
        :param dir_templates: directory to store templates, defaults to templates in the current directory
        :param dir_static: directory to store static files, defaults to static in the current directory
        :param dir_requests: directory to store larget requests, defaults to apier-requests in the current directory
        :param support_large_requests: if True, support large requests
        """
        self.__decryptor = SSAGE(age_key)
        self.__dir_responses = dir_responses
        self.__dir_webpage = dir_webpage or Path(getcwd()) / "public"
        if not self.__dir_responses:
            self.__dir_responses = self.__dir_webpage / "apier-responses"
        self.__dir_templates = dir_templates or Path(getcwd()) / "templates"
        self.__dir_static = dir_static or Path(getcwd()) / "static"
        self.__dir_requests = dir_requests or Path(getcwd()) / "apier-requests"
        self.__support_large_requests = support_large_requests
        self.__client_config: APIERClientConfig = {
            "age_public_key": self.public_key,
            "gitlab_pipeline_endpoint": client_config["gitlab_pipeline_endpoint"],
            "gitlab_token": client_config["gitlab_token"],
            "gitlab_branch": client_config["gitlab_branch"]
        } if client_config else {}
        self.__paths: Dict[APIEREndpointMode, Dict[str, Callable[[any], str]]] = {
            APIEREndpointMode.API: {},
            APIEREndpointMode.TEMPLATE: {},
            APIEREndpointMode.RAW: {}
        }

    def render_template(self, template_name: str, **kwargs) -> str:
        """
        Render a template with the given arguments
        :param template_name: name of the template file
        :param kwargs: arguments to pass to the template
        :return: rendered template
        """
        if not self.__dir_templates:
            raise FileNotFoundError("Templates directory not found")
        template_loader = jinja2.FileSystemLoader(searchpath=[str(self.__dir_templates)])
        template_env = SandboxedEnvironment(loader=template_loader)
        template = template_env.get_template(template_name)
        return template.render(**kwargs)

    def register_path(self, path: str, handler: Callable[[any], str], mode: APIEREndpointMode = APIEREndpointMode.API) -> None:
        """
        Register a path with a handler
        :param path: virtual request path
        :param handler: function to handle the request
        :param mode: endpoint mode, required to decide how to handle the request
        :return: None
        """
        self.__paths[mode][path] = handler

    def route(self, path: str, mode: APIEREndpointMode = APIEREndpointMode.API):
        """
        Decorator to register a path with a handler
        :param path: virtual request path
        :param mode: endpoint mode, required to decide how to handle the request
        :return: decorator
        """
        def decorator(func: Callable[[any], str]):
            self.register_path(path, func, mode)
            return func
        return decorator

    def process_requests(
            self,
            data_env_name: str = "APIER_DATA",
            empty_ok: bool = True,
            always_success: bool = True,
            delete_old_responses: bool = True,
            build_static_pages: bool = True
    ) -> None:
        """
        Process the current request stored in the environment variable
        :param data_env_name: name of the environment variable containing the request
        :param empty_ok: if True, do not raise an error if there is no request
        :param always_success: if True, do not raise an error if there is an exception
        :param delete_old_responses: if True, delete old responses
        :param build_static_pages: if True, build static pages
        :return: None
        """
        # noinspection PyBroadException
        try:
            if delete_old_responses:
                self.purge_old_responses()
                self.purge_old_requests()
            if build_static_pages:
                self.build_static_pages()
            self.__dir_responses.mkdir(parents=True, exist_ok=True)
            data = environ.get(data_env_name)
            if not data:
                if empty_ok:
                    print('[*] No request to process')
                    return
                raise APIERClientError(f"Missing request data: {data_env_name}")
            if data.startswith('MP_'):
                if not self.__support_large_requests:
                    raise APIERClientError("Large requests not supported")
                data = self.process_large_request(data)
                if data is None:
                    return
            self.process_single_request(data)
        except Exception:
            if always_success:
                print_exc()
            else:
                raise

    def process_large_request(self, data_part: str) -> Optional[str]:
        """
        Process a large request and combine all parts if available, otherwise save the part
        :param data_part: raw request data part
        :return: combined request data if all parts are available, None otherwise
        """
        # data format is `MP_${requestId}_${part_index}_${parts_total}_${part_data}`
        parts = data_part.split('_')
        try:
            if parts[0] != 'MP':
                raise ValueError("Invalid prefix")
            request_id = parts[1]
            part_index = int(parts[2])
            parts_total = int(parts[3])
            part_data = parts[4]
        except (IndexError, ValueError):
            raise APIERClientError("Invalid large request data")

        print(f'[*] Combining large request {request_id} part {part_index}/{parts_total}')
        path_part = self.__dir_requests / f"{request_id}_{part_index}_{parts_total}.txt"
        path_part.parent.mkdir(parents=True, exist_ok=True)
        path_part.write_text(json.dumps({
            "id": request_id,
            "index": part_index,
            "total": parts_total,
            "time": datetime.now(tz=timezone.utc).isoformat(),
            "data": part_data
        }))

        # Check if all parts are available
        for i in range(parts_total):
            path = self.__dir_requests / f"{request_id}_{i + 1}_{parts_total}.txt"
            if not path.exists():
                print(f'[*] Large request {request_id} part {i + 1}/{parts_total} missing')
                return None

        # Combine all parts
        data = ''
        for i in range(parts_total):
            path = self.__dir_requests / f"{request_id}_{i + 1}_{parts_total}.txt"
            data += json.loads(path.read_text())["data"]
            path.unlink(missing_ok=True)

        return data

    def build_static_pages(self) -> bool:
        """
        Build static pages from templates
        :return: True if all pages were built successfully
        """
        if self.__dir_webpage is None:
            return False
        self.__dir_webpage.mkdir(parents=True, exist_ok=True)

        if self.__dir_static is not None and self.__dir_static.exists():
            copytree(self.__dir_static, self.__dir_webpage / "static", dirs_exist_ok=True)

        for endpoint_mode in (APIEREndpointMode.RAW, APIEREndpointMode.TEMPLATE):
            for route_path, function in self.__paths[endpoint_mode].items():
                response = function(None)
                if route_path == '/':
                    route_path = "index.html"
                else:
                    route_path = route_path.lstrip('/')

                if endpoint_mode == APIEREndpointMode.TEMPLATE and route_path.count('.') == 0:
                    route_path = f"{route_path}.html"

                path_response = self.__dir_webpage / route_path
                path_response.write_text(response)
                if route_path.lower().endswith('.html'):
                    patch_html(path_response, self.__client_config)

        return True

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

        request_handler = self.__paths[APIEREndpointMode.API].get(request_path)
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
        if not self.__dir_responses.exists():
            return
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

    def purge_old_requests(self, minutes: int = 15) -> None:
        """
        Purge old requests from the requests directory
        :param minutes: minutes to keep the request
        :return: None
        """
        if not self.__dir_requests.exists():
            return
        now = datetime.now(tz=timezone.utc)
        for file in self.__dir_requests.glob("*.txt"):
            try:
                content = json.loads(file.read_text())
                date = datetime.fromisoformat(content["time"])
                if (now - date).total_seconds() / 60 > minutes:
                    print(f'[*] Purging old request {file.name}')
                    file.unlink()
            except Exception as e:
                print(f'[!] Error while purging request {file.name}: {e}')
                file.unlink()

    @property
    def public_key(self) -> str:
        """
        Local AGE public key
        :return: public key
        """
        return self.__decryptor.public_key
