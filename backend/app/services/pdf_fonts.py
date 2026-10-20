"""Only the two build-time font assets can be fetched by the PDF renderer."""

from pathlib import Path


FONT_FILES = ('HuhuaResumeCJK-Regular.otf', 'HuhuaResumeCJK-Bold.otf')


def font_paths():
    from app.config import get_settings

    directory = get_settings().PDF_CJK_FONT_DIR
    paths = [Path(directory) / name for name in FONT_FILES] if directory else []
    return paths if paths and all(path.is_file() for path in paths) else []


def font_resources():
    paths = font_paths()
    if not paths:
        return '', {}
    resources = {f'huhua-font:{weight}': path.read_bytes()
                 for weight, path in zip((400, 700), paths)}
    rules = ''.join(
        f"@font-face {{font-family: 'Huhua Resume CJK'; font-weight: {weight}; "
        f"src: url('huhua-font:{weight}');}}" for weight in (400, 700))
    # 生僻字、繁体和原字体的其余字符仍交给完整 SC 字体及系统回退。
    rules += "body {font-family: 'Huhua Resume CJK', 'Noto Sans CJK SC', sans-serif !important;}"
    return rules, resources
