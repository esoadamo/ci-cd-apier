import re
import json
from pathlib import Path
from shutil import copytree
from typing import Optional, TypedDict

DIR_JS = Path(__file__).parent / "js"


class APIERClientConfig(TypedDict):
    """
    Configuration for the client
    """
    age_public_key: str
    gitlab_pipeline_endpoint: str
    gitlab_token: str
    gitlab_branch: Optional[str]


def patch_html(file_html: Path, client_config: Optional[APIERClientConfig] = None) -> None:
    """
    Patch the HTML file with the required JS files and copies the apier directory
    :param file_html: HTML file to patch
    :param client_config: Optional client configuration used for automatic client creation
    :return: None
    """
    content = file_html.read_text()
    content = re.sub(r'(<\s*head.*?>)', '\\1\n<script src="apier/agewasm/wasm_exec.js"></script>\n<script src="apier/apier.js"></script>', content)
    file_html.write_text(content)

    dir_apier_target = file_html.parent / "apier"
    if dir_apier_target.exists():
        return
    copytree(DIR_JS, dir_apier_target)
    file_client_config = dir_apier_target / "client.json"
    if client_config is not None and not file_client_config.exists():
        file_client_config.write_text(json.dumps(client_config))
