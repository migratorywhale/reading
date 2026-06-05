"""阿码专属共读系统 FastMCP entry point。端口 8774，数据 ama_reading_store.json。"""
import sys
sys.path.insert(0, '/home/linuxuser/reading_repo')

from fastmcp import FastMCP
from reading_tools import (
    reading_save_chapter, reading_add_note, reading_set_progress,
    reading_list_books, reading_get_book, reading_read_chapter,
    reading_get_outline,
)
from reading_jjwxc import (
    reading_jjwxc_install_cookies, reading_jjwxc_check_cookies,
    reading_jjwxc_fetch_toc, reading_jjwxc_fetch_chapter,
)
from file_storage import FileStorageAdapter

storage = FileStorageAdapter('/home/linuxuser/reading_repo/ama_reading_store.json')
mcp = FastMCP("ama-reading")


@mcp.tool()
def save_chapter(book: str, chapter: str, content: str, note: str = '', source: str = ''):
    """存一章。手动复制粘贴或 fetcher 抓的都进这里。"""
    return reading_save_chapter(storage, book, chapter, content, note, source)

@mcp.tool()
def add_note(book: str, chapter: str, note: str):
    """追加章节笔记，不覆盖正文。"""
    return reading_add_note(storage, book, chapter, note)

@mcp.tool()
def set_progress(book: str, chapter: str, status_note: str = ''):
    """手动标记进度。"""
    return reading_set_progress(storage, book, chapter, status_note)

@mcp.tool()
def list_books():
    """列出所有在读的书 + 进度。"""
    return reading_list_books(storage)

@mcp.tool()
def get_book(book: str, mode: str = 'lite'):
    """拿一本书全部。lite=元数据；full=全章节正文。"""
    return reading_get_book(storage, book, mode)

@mcp.tool()
def read_chapter(book: str, chapter: str, chunk_idx: int = 0, chunk_size: int = 2500):
    """分段读已存章节。"""
    return reading_read_chapter(storage, book, chapter, chunk_idx, chunk_size)

@mcp.tool()
def get_outline(book: str, chapter: str):
    """章节骨架摘要，约 50x 压缩。快速了解章节结构，不用读全文。"""
    return reading_get_outline(storage, book, chapter)

@mcp.tool()
def jjwxc_install_cookies(cookies_json: str):
    """装晋江 cookies。"""
    return reading_jjwxc_install_cookies(storage, cookies_json)

@mcp.tool()
async def jjwxc_check_cookies():
    """验 cookies 有效性。"""
    return await reading_jjwxc_check_cookies(storage)

@mcp.tool()
async def jjwxc_fetch_toc(novel_id: str):
    """抓章节列表（不需 cookies）。"""
    return await reading_jjwxc_fetch_toc(storage, novel_id)

@mcp.tool()
async def jjwxc_fetch_chapter(novel_id: str, chapter_id: str,
                              save_to_book: str = '', note: str = '', return_mode: str = 'lite'):
    """抓单章 + 可选自动 save。"""
    return await reading_jjwxc_fetch_chapter(
        storage, novel_id, chapter_id, save_to_book, note, return_mode)


if __name__ == '__main__':
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8774)
