import json
from enum import Enum
from uuid import UUID
from pathlib import Path
from typing import Any, Dict, Callable, Optional, TypedDict
from os import getcwd
from traceback import print_exc
from datetime import datetime, timezone
from shutil import copytree

from ssage import SSAGE
import jinja2
from jinja2.sandbox import SandboxedEnvironment

from .exceptions import APIERClientError, APIERServerError
from .patcher import patch_html, APIERClientConfig
from .preprocessor import Preprocessor
from .postprocessor import Postprocessor


HANDLER_FUNCTION = Callable[[Any], Optional[str]]


class APIEREndpointMode(Enum):
    API = "api"
    TEMPLATE = "template"
    RAW = "raw"


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
                 dir_templates: Optional[Path] = None,
                 dir_static: Optional[Path] = None,
                 client_config: Optional[APIERGitlabClientConfig] = None
                 ):
        """
        Initialize the APIER object
        :param age_key: local secret key
        :param dir_webpage: directory to store all webpages, defaults to public in the current directory
        :param dir_templates: directory to store templates, defaults to templates in the current directory
        :param dir_static: directory to store static files, defaults to static in the current directory
        :param client_config: GitLab client configuration
        :return: None
        """
        self.__decryptor = SSAGE(age_key)
        self.__dir_webpage = dir_webpage or Path(getcwd()) / "public"
        self.__dir_templates = dir_templates or Path(getcwd()) / "templates"
        self.__dir_static = dir_static or Path(getcwd()) / "static"
        self.__client_config: APIERClientConfig = {
            "age_public_key": self.public_key,
            "gitlab_pipeline_endpoint": client_config["gitlab_pipeline_endpoint"],
            "gitlab_token": client_config["gitlab_token"],
            "gitlab_branch": client_config["gitlab_branch"]
        } if client_config else APIERClientConfig(age_public_key=self.public_key)
        self.__paths: Dict[APIEREndpointMode, Dict[str, HANDLER_FUNCTION]] = {
            APIEREndpointMode.API: {},
            APIEREndpointMode.TEMPLATE: {},
            APIEREndpointMode.RAW: {}
        }
        self.__preprocessor = Preprocessor()
        self.__postprocessor = Postprocessor()

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

    def register_path(self, path: str, handler: HANDLER_FUNCTION, mode: APIEREndpointMode = APIEREndpointMode.API) -> None:
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
        def decorator(func: HANDLER_FUNCTION):
            self.register_path(path, func, mode)
            return func
        return decorator

    def process_requests(
            self,
            empty_ok: bool = True,
            always_success: bool = True
    ) -> None:
        """
        Process the current request stored in the environment variable
        :param empty_ok: if True, do not raise an error if there is no request
        :param always_success: if True, do not raise an error if there is an exception
        :return: None
        """
        # noinspection PyBroadException
        try:
            self._build_static_pages()
            data = self.__preprocessor.load_request()
            if not data:
                if empty_ok:
                    print('[*] No request to process')
                    return
                raise APIERClientError("Missing request data")
            self._process_single_request(data)
        except Exception:
            if always_success:
                print_exc()
            else:
                raise

    def _build_static_pages(self) -> bool:
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
                assert response is not None, f"Handler for {route_path=} returned None while building static pages"
                if route_path == '/':
                    route_path = "index.html"
                else:
                    route_path = route_path.lstrip('/')

                if endpoint_mode == APIEREndpointMode.TEMPLATE and route_path.count('.') == 0:
                    route_path = f"{route_path}.html"

                path_response = self.__dir_webpage / route_path
                path_response.relative_to(self.__dir_webpage)
                path_response.parent.mkdir(parents=True, exist_ok=True)
                path_response.write_text(response)
                if route_path.lower().endswith('.html'):
                    patch_html(path_response, self.__client_config)

        return True

    def _process_single_request(self, request_raw: str) -> None:
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
        if request_handler is None:
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

        self.__postprocessor.save_response(request_id, response_encrypted)

        if exception:
            raise exception

    @property
    def public_key(self) -> str:
        """
        Local AGE public key
        :return: public key
        """
        return self.__decryptor.public_key
