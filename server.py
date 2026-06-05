"""小克共读系统 FastMCP entry point。端口 8770，数据 reading_store.json。"""
import sys, os, json, asyncio
from pathlib import Path

sys.path.insert(0, '/home/linuxuser/reading_repo')
sys.path.insert(0, '/home/linuxuser/reading_repo/weread')

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

storage = FileStorageAdapter('/home/linuxuser/reading_repo/reading_store.json')
mcp = FastMCP("reading")

# weread state 路径（和 cognition_server 共用同一个，方便将来整合）
_MCP_MEMORY_DIR = Path(os.environ.get('MCP_MEMORY_DIR', Path.home() / '.mcp-memory'))
WEREAD_STATE_PATH = str(_MCP_MEMORY_DIR / 'weread_state.json')

# 懒加载 weread 模块
_WR_OK = False
try:
    from weread_fetch import (
        check_state_valid as _wr_check,
        fetch_chapter as _wr_chap,
        fetch_book_toc as _wr_toc,
    )
    from weread_write import (
        add_review as _wr_add_review,
        delete_review as _wr_del_review,
        list_reviews as _wr_list_reviews,
        list_bookmarks as _wr_list_bms,
        list_bookshelf as _wr_list_shelf,
    )
    _WR_OK = True
except Exception as e:
    print(f'[server] weread module not loaded: {e}', file=sys.stderr)


def _wr_run(coro):
    """在同步 MCP tool 上下文里跑异步 coro。"""
    if not _WR_OK:
        return {'error': 'weread module not loaded — check weread_state.json'}
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as ex:
                return ex.submit(lambda: asyncio.run(coro)).result()
    except RuntimeError:
        pass
    return asyncio.run(coro)


def _wr_save(key: str, data):
    storage.set(key, json.dumps(data, ensure_ascii=False))


# ─── 基础阅读工具 ─────────────────────────────────────────────────────────

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

# ─── 晋江工具 ────────────────────────────────────────────────────────────

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

# ─── 微信读书工具 ──────────────────────────────────────────────────────────

@mcp.tool()
def weread_list_bookshelf() -> str:
    """列出微信读书书架（书单 + 阅读进度）。需要 weread_state.json。"""
    data = _wr_run(_wr_list_shelf(WEREAD_STATE_PATH))
    if isinstance(data, dict) and 'error' in data:
        return json.dumps(data, ensure_ascii=False)
    books = data.get('books', []) if isinstance(data, dict) else []
    return json.dumps({
        'total': len(books),
        'books': [{'bookId': b.get('bookId'), 'title': b.get('title'),
                   'author': b.get('author'), 'finishReading': b.get('finishReading')}
                  for b in books[:100]]
    }, ensure_ascii=False)

@mcp.tool()
def weread_fetch_toc(book_id: str) -> str:
    """抓微信读书章节目录（开浏览器，约 8-12s）。结果存入 reading_store。"""
    data = _wr_run(_wr_toc(WEREAD_STATE_PATH, book_id))
    key = f'reading:book:weread:{book_id}:toc'
    _wr_save(key, data)
    chapters = data.get('chapters', []) if isinstance(data, dict) else []
    return json.dumps({
        'saved_to': key, 'chapter_count': len(chapters),
        'title': data.get('title') if isinstance(data, dict) else None,
        'chapters': chapters[:50],
    }, ensure_ascii=False)

@mcp.tool()
def weread_fetch_chapter(book_id: str, chapter_uid: str = '', max_pages: int = 200) -> str:
    """抓微信读书单章正文。chapter_uid='' 从上次阅读位置续读。"""
    data = _wr_run(_wr_chap(WEREAD_STATE_PATH, book_id, chapter_uid, max_pages))
    key = f'reading:book:weread:{book_id}:ch:{chapter_uid or "current"}'
    _wr_save(key, data)
    return json.dumps({
        'saved_to': key,
        'title': data.get('title') if isinstance(data, dict) else None,
        'text_len': len(data.get('text', '')) if isinstance(data, dict) else 0,
        'preview': data.get('text', '')[:200] if isinstance(data, dict) else '',
    }, ensure_ascii=False)

@mcp.tool()
def weread_list_notes(book_id: str, mine: bool = True) -> str:
    """列出微信读书书评/段落笔记。"""
    data = _wr_run(_wr_list_reviews(WEREAD_STATE_PATH, book_id, mine=mine))
    reviews = data.get('reviews', []) if isinstance(data, dict) else []
    return json.dumps({
        'total': data.get('totalCount', len(reviews)) if isinstance(data, dict) else 0,
        'reviews': [{'reviewId': (r.get('review') or r).get('reviewId'),
                     'content': (r.get('review') or r).get('content'),
                     'chapterUid': (r.get('review') or r).get('chapterUid')}
                    for r in reviews[:50]]
    }, ensure_ascii=False)

@mcp.tool()
def weread_add_note(book_id: str, chapter_uid: int, content: str,
                    range_str: str = '', is_private: bool = False) -> str:
    """在微信读书章节留笔记。range_str='' 为章节级，'1234-1256' 精确锚定到原文。"""
    data = _wr_run(_wr_add_review(WEREAD_STATE_PATH, book_id, chapter_uid,
                                   content, range_str or None, is_private))
    return json.dumps(data, ensure_ascii=False)

@mcp.tool()
def weread_delete_note(review_id: str) -> str:
    """删除微信读书笔记。review_id 从 add_note 或 list_notes 获取。"""
    data = _wr_run(_wr_del_review(WEREAD_STATE_PATH, review_id))
    return json.dumps(data, ensure_ascii=False)

@mcp.tool()
def weread_list_highlights(book_id: str) -> str:
    """列出微信读书高亮划线。"""
    data = _wr_run(_wr_list_bms(WEREAD_STATE_PATH, book_id))
    return json.dumps(data, ensure_ascii=False)


if __name__ == '__main__':
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8770)
