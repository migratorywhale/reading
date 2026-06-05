"""简单 JSON 文件 StorageAdapter，比走 ama_memory_server 更直接。"""
import json, os
from pathlib import Path
from typing import Optional

class FileStorageAdapter:
    """key-value 存在一个 JSON 文件里。够用，原子写入防损坏。"""
    def __init__(self, path: str = '/home/linuxuser/search_tool/reading/reading_store.json'):
        self.path = Path(path)
        if not self.path.exists():
            self.path.write_text('{}', encoding='utf-8')

    def _load(self) -> dict:
        try: return json.loads(self.path.read_text(encoding='utf-8'))
        except Exception: return {}

    def _save(self, data: dict):
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, self.path)

    def get(self, key: str) -> Optional[str]:
        return self._load().get(key)

    def set(self, key: str, value: str, tags: Optional[list] = None) -> None:
        data = self._load()
        data[key] = value
        self._save(data)

    def list_keys(self, prefix: str = '') -> list[str]:
        return [k for k in self._load() if k.startswith(prefix)]
