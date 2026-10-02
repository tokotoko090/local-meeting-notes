"""Prompt templates and atomic text writes shared by the server and worker."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

TEMPLATE_SNAPSHOT_ENV = 'LOCAL_MEETING_NOTES_PROMPT_SNAPSHOT'
DEFAULT_PROMPT_TEMPLATE = '''# 依頼

以下は会議の文字起こしです。mic は自分の発言、system はPCから聞こえた相手側や共有音声です。この文字起こしをもとに、議事録を作成してください。

# 出力形式

## 会議概要
*

## 決定事項
*

## 議論内容
*

## ToDo

| 担当 | 内容 | 期限 |
| -- | -- | -- |

## 保留事項
*

## 次回確認事項
*

## 重要発言
*'''


def require_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError('プロンプトを空にはできません。内容を入力してください。')
    return value


def render_prompt(template: str, transcript: str) -> str:
    return require_text(template) + '\n\n## 文字起こし全文\n\n' + transcript + '\n'


def worker_template() -> str:
    snapshot = os.environ.get(TEMPLATE_SNAPSHOT_ENV)
    if snapshot:
        return require_text(Path(snapshot).read_text(encoding='utf-8'))
    return DEFAULT_PROMPT_TEMPLATE


def atomic_write_text(path: Path, text: str) -> None:
    """Replace a file after a complete write, never follow the target symlink."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=path.parent, prefix=f'.{path.name}.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
