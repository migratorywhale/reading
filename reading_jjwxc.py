"""晋江文学城 fetcher。使用 sync httpx，无需 playwright。"""
import json, re

_COOKIES_KEY = '_system:jjwxc_cookies'
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')


def reading_jjwxc_install_cookies(storage, cookies_json: str) -> dict:
    """安装晋江 cookies（一次性配置）。
    格式：从 DevTools 复制的 JSON 数组，或 name=value; 分隔的字符串。"""
    cleaned = []
    try:
        parsed = json.loads(cookies_json)
        if not isinstance(parsed, list): raise ValueError
        for c in parsed:
            if not isinstance(c, dict) or 'name' not in c: continue
            item = {'name': c['name'], 'value': c.get('value', ''),
                    'domain': c.get('domain') or '.jjwxc.net',
                    'path': c.get('path', '/')}
            cleaned.append(item)
    except (ValueError, TypeError):
        for p in cookies_json.split(';'):
            p = p.strip()
            if not p: continue
            eq = p.find('=')
            if eq < 0: continue
            cleaned.append({'name': p[:eq].strip(), 'value': p[eq+1:].strip(),
                            'domain': '.jjwxc.net', 'path': '/'})
    if not cleaned: return {'error': 'no valid cookies parsed'}
    storage.set(_COOKIES_KEY, json.dumps(cleaned, ensure_ascii=False))
    return {'ok': True, 'cookies_count': len(cleaned)}


def _load_cookies(storage) -> dict:
    raw = storage.get(_COOKIES_KEY)
    if not raw: return {}
    try:
        lst = json.loads(raw) if isinstance(raw, str) else raw
        return {c['name']: c['value'] for c in lst if isinstance(c, dict)}
    except Exception:
        return {}


def _httpx_get(url: str, cookies: dict = None) -> str:
    """Sync httpx GET，返回解码后的 HTML。"""
    import httpx
    headers = {'User-Agent': _UA, 'Accept-Language': 'zh-CN,zh;q=0.9'}
    with httpx.Client(timeout=20.0, headers=headers,
                      cookies=cookies or {}, follow_redirects=True) as c:
        r = c.get(url)
        r.encoding = 'gb18030'   # jjwxc 用 GBK 家族
        return r.text


def _parse_toc(html: str) -> dict:
    """从 jjwxc onebook.php 页面提取目录。
    bs4 的 html.parser 在畸形嵌套 HTML 里只能抓前 ~25 章；
    直接 regex chapterid 绕过这个限制。"""
    book_title = None
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        el = soup.select_one('h1.tit, h1, span[itemprop="name"]')
        if el: book_title = el.get_text(strip=True)
    except Exception:
        m = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        if m: book_title = m.group(1).strip()

    raw_ids = re.findall(r'chapterid=?["\']?(\d+)', html)
    unique_ids = sorted(set(raw_ids), key=int)

    titles: dict = {}
    for m in re.finditer(r'chapterid=?["\']?(\d+)["\']?[^>]*>([^<]{1,120})<', html):
        cid, txt = m.group(1), m.group(2).strip()
        if not txt or cid in titles: continue
        if re.search(r'第\s*\d+\s*章', txt) or len(txt) <= 30:
            titles[cid] = txt

    return {
        'book_title': book_title,
        'chapter_count': len(unique_ids),
        'chapters': [{'chapter_id': cid, 'title': titles.get(cid) or f'第{cid}章'}
                     for cid in unique_ids],
    }


def _parse_chapter(html: str) -> dict:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {'error': 'bs4 not installed'}
    soup = BeautifulSoup(html, 'lxml')
    container = soup.select_one('div.noveltext') or soup.select_one('#oneboolt')
    if not container:
        body_text = soup.get_text()
        return {'title': None, 'content': None,
                'vip_required': bool(re.search(r'(购买本章|VIP章节|订阅|登录后阅读)', body_text))}
    h2 = container.find('h2')
    title = h2.get_text(strip=True) if h2 else None
    for tag in container.select('script, style, ins, .readsmall, .smallreadbody'):
        tag.decompose()
    if h2:
        for sib in list(h2.previous_siblings):
            if hasattr(sib, 'decompose'): sib.decompose()
            elif hasattr(sib, 'extract'): sib.extract()
        h2.decompose()
    text = container.get_text(separator='\n', strip=True)
    text = re.split(r'插入书签|作者有话说|显示所有文的作话', text, maxsplit=1)[0].strip()
    text = re.sub(r'\n{3,}', '\n\n', text)
    body_text = soup.get_text()
    vip_required = bool(re.search(r'(购买本章|VIP章节|订阅|登录后阅读)', body_text)) and not text
    return {'title': title, 'content': text or None, 'vip_required': vip_required}


async def reading_jjwxc_check_cookies(storage):
    """检查 cookies 是否有效（快速验证）。"""
    cookies = _load_cookies(storage)
    if not cookies: return {'ok': False, 'reason': 'no cookies stored', 'count': 0}
    try:
        html = _httpx_get('https://my.jjwxc.net/', cookies)
        if 'login' in html.lower()[:500]:
            return {'ok': False, 'reason': 'expired or invalid', 'count': len(cookies)}
        return {'ok': True, 'count': len(cookies)}
    except Exception as e:
        return {'ok': False, 'reason': str(e), 'count': len(cookies)}


async def reading_jjwxc_fetch_toc(storage, novel_id: str) -> dict:
    """抓晋江小说目录（不需要 cookies）。"""
    if not str(novel_id).strip().isdigit():
        return {'error': 'novel_id must be numeric'}
    url = f'http://www.jjwxc.net/onebook.php?novelid={novel_id}'
    try:
        html = _httpx_get(url, cookies={})
    except Exception as e:
        return {'error': f'fetch failed: {e}'}
    parsed = _parse_toc(html)
    parsed['novel_id'] = novel_id
    parsed['source_url'] = url
    return parsed


async def reading_jjwxc_fetch_chapter(storage, novel_id, chapter_id,
                                       save_to_book='', note='', return_mode='lite'):
    """抓晋江单章正文，可选自动存储。"""
    if not str(novel_id).strip().isdigit() or not str(chapter_id).strip().isdigit():
        return {'error': 'novel_id and chapter_id must be numeric'}
    if return_mode not in ('lite', 'preview', 'full'):
        return {'error': "return_mode must be 'lite'/'preview'/'full'"}
    url = f'http://www.jjwxc.net/onebook.php?novelid={novel_id}&chapterid={chapter_id}'
    cookies = _load_cookies(storage)
    try:
        html = _httpx_get(url, cookies)
    except Exception as e:
        return {'error': f'fetch failed: {e}'}

    parsed = _parse_chapter(html)
    meta = {'novel_id': novel_id, 'chapter_id': chapter_id, 'title': parsed.get('title')}
    if parsed.get('vip_required') and not parsed.get('content'):
        return {**meta, 'vip_required': True, 'hint': 'VIP 章节需要有效 cookies'}
    if not parsed.get('content'):
        return {**meta, 'hint': 'parser 未找到正文，selector 可能已变更', 'url': url}

    content = parsed['content']
    content_len = len(content)
    saved_key = None

    if save_to_book.strip():
        parsed_title = (parsed.get('title') or '').strip()
        ch_label = (f'ch{chapter_id}_{parsed_title}'
                    if parsed_title and '章' in parsed_title and len(parsed_title) < 30
                    else f'ch{chapter_id}')
        from reading_tools import reading_save_chapter
        save_result = reading_save_chapter(storage=storage, book=save_to_book,
            chapter=ch_label, content=content, note=note, source='晋江')
        saved_key = save_result.get('key')

    out = {**meta, 'content_len': content_len, 'saved_key': saved_key}
    if return_mode == 'lite':
        out['preview'] = content[:100].replace('\n', ' ')
        out['hint'] = '用 read_chapter(book, chapter, chunk_idx) 分段读正文'
    elif return_mode == 'preview':
        out['first_500'] = content[:500]
        out['last_300'] = content[-300:] if content_len > 800 else None
    else:
        out['content'] = content
    return out
