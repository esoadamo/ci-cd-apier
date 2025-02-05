import re
from pathlib import Path
from shutil import copytree

DIR_JS = Path(__file__).parent / "js"


def patch_html(file_html: Path) -> None:
    """
    Patch the HTML file with the required JS files and copies the apier directory
    :param file_html: HTML file to patch
    :return: None
    """
    content = file_html.read_text()
    content = re.sub(r'(<\s*head.*?>)', '\\1\n<script src="apier/agewasm/wasm_exec.js"></script>\n<script src="apier/apier.js"></script>', content)
    file_html.write_text(content)

    dir_apier_target = file_html.parent / "apier"
    if dir_apier_target.exists():
        return
    copytree(DIR_JS, dir_apier_target)
