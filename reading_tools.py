"""共读通用工具。Platform-agnostic + Storage-agnostic。"""
import re
from collections import Counter
from datetime import datetime
from typing import Protocol, Optional

try:
    import jieba.posseg as _pseg
    _JIEBA_OK = True
except ImportError:
    _JIEBA_OK = False


class StorageAdapter(Protocol):
    def get(self, key: str) -> Optional[str]: ...
    def set(self, key: str, value: str, tags: Optional[list] = None) -> None: ...
    def list_keys(self, prefix: str = '') -> list[str]: ...


def _bk(book, suffix): return f'reading:{book.strip()}:{suffix}'
def _ts(): return datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


def reading_save_chapter(storage, book, chapter, content, note='', source=''):
    if not book.strip() or not chapter.strip(): return {'error': 'book/chapter required'}
    if not content.strip(): return {'error': 'content empty'}
    b, c = book.strip(), chapter.strip()
    chap_key = _bk(b, f'ch:{c}')
    parts = [f'## {b} · {c}']
    if source: parts.append(f'[来源] {source}')
    parts += ['', content.strip()]
    if note.strip(): parts += ['', f'─── 笔记 ───\n{note.strip()}']
    storage.set(chap_key, '\n'.join(parts), tags=['reading', b])
    cnt = sum(1 for _ in storage.list_keys(_bk(b, 'ch:')))
    storage.set(_bk(b, 'progress'),
        f'## {b} · 进度\n最新章节: {c}\n更新时间: {_ts()}\n累计已存: {cnt} 章')
    return {'ok': True, 'key': chap_key, 'content_len': len(content),
            'has_note': bool(note.strip()), 'source': source or None}


def reading_add_note(storage, book, chapter, note):
    if not note.strip(): return {'error': 'note empty'}
    k = _bk(book.strip(), f'ch:{chapter.strip()}')
    existing = storage.get(k)
    if existing is None: return {'error': f'chapter not saved: {k}'}
    sep = '\n\n' if '─── 笔记 ───' in existing else '\n\n─── 笔记 ───\n'
    storage.set(k, existing.rstrip() + sep + f'[{_ts()}] {note.strip()}')
    return {'ok': True, 'key': k, 'note_added': True}


def reading_set_progress(storage, book, chapter, status_note=''):
    b = book.strip()
    cnt = sum(1 for _ in storage.list_keys(_bk(b, 'ch:')))
    parts = [f'## {b} · 进度', f'最新章节: {chapter.strip()}',
             f'更新时间: {_ts()}', f'已存章节数: {cnt}']
    if status_note.strip(): parts.append(f'\n用户留言: {status_note.strip()}')
    storage.set(_bk(b, 'progress'), '\n'.join(parts))
    return {'ok': True, 'book': b, 'chapter': chapter}


def reading_list_books(storage):
    books = {}
    for k in storage.list_keys('reading:'):
        parts = k.split(':', 2)
        if len(parts) < 3: continue
        book, rest = parts[1], parts[2]
        b = books.setdefault(book, {'book': book, 'latest_chapter': None,
            'chapters_saved': 0, 'last_update': None, 'has_summary': False})
        if rest.startswith('ch:'): b['chapters_saved'] += 1
        elif rest == 'progress':
            v = storage.get(k) or ''
            m1 = re.search(r'最新章节[::]\s*([^\n]+)', v)
            m2 = re.search(r'更新时间[::]\s*([^\n]+)', v)
            if m1: b['latest_chapter'] = m1.group(1).strip()
            if m2: b['last_update'] = m2.group(1).strip()
        elif rest == 'summary': b['has_summary'] = True
    return {'books': list(books.values()), 'count': len(books)}


def reading_get_book(storage, book, mode='lite'):
    b = book.strip()
    chap_keys = sorted(storage.list_keys(_bk(b, 'ch:')))
    progress = storage.get(_bk(b, 'progress')) or ''
    summary = storage.get(_bk(b, 'summary')) or ''
    out = {'book': b, 'progress': progress, 'chapter_count': len(chap_keys),
           'summary_preview': summary[:300] if summary else None}
    if mode == 'full':
        out['chapters'] = [{'key': k, 'content': storage.get(k)} for k in chap_keys]
        out['summary_full'] = summary or None
    else:
        out['chapter_keys'] = chap_keys
    return out


def reading_read_chapter(storage, book, chapter, chunk_idx=0, chunk_size=2500):
    k = _bk(book.strip(), f'ch:{chapter.strip()}')
    raw = storage.get(k)
    if raw is None: return {'error': f'章节未存: {k}'}
    content = str(raw); total = len(content)
    chunk_size = max(500, min(int(chunk_size), 6000))
    chunk_idx = max(0, int(chunk_idx))
    total_chunks = (total + chunk_size - 1) // chunk_size
    start = chunk_idx * chunk_size; end = start + chunk_size
    if start >= total: return {'error': f'chunk_idx out of range (total {total_chunks})'}
    return {'book': book.strip(), 'chapter': chapter.strip(),
            'chunk_idx': chunk_idx, 'chunks_total': total_chunks,
            'chars_returned': min(end, total) - start, 'total_chars': total,
            'content_chunk': content[start:end], 'has_more': end < total}


# ─── Outline（规则骨架，约 50x 压缩，不调 LLM）────────────────────────────

def _outline_first_sentence(p: str, max_chars: int = 80) -> str:
    m = re.match(r'^([^。！？\.\!\?\n]{4,%d}[。！？\.\!\?])' % max_chars, p)
    if m:
        return m.group(1).strip()
    snippet = p[:max_chars].strip()
    return snippet + ('…' if len(p) > max_chars else '')


def _outline_is_junk(p: str) -> bool:
    if len(p) < 8: return True
    if p.startswith(('##', '[', '【', '<', '─')): return True
    if re.search(r'\b(type|data|url|method|async|var|let|const)\s*:', p): return True
    code_chars = sum(p.count(c) for c in '{}=();')
    if code_chars / max(len(p), 1) > 0.05: return True
    if len(p) > 12:
        cn_chars = sum(1 for c in p if '一' <= c <= '鿿')
        if cn_chars / len(p) < 0.25: return True
    return False


def reading_get_outline(storage, book, chapter):
    """规则骨架摘要，约 50x 压缩。不调 LLM，只需 jieba。
    返回：开头/中间/结尾首句、主要实体、对话密度、头尾原文片段。"""
    k = _bk(book.strip(), f'ch:{chapter.strip()}')
    raw = storage.get(k)
    if raw is None: return {'error': f'章节未存: {k}'}

    text = str(raw)
    total_chars = len(text)
    if total_chars < 20: return {'error': 'content too short', 'key': k}

    # 分段
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    if len(paragraphs) < 10 or any(len(p) > 1500 for p in paragraphs):
        paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
    paragraphs = [p for p in paragraphs if not _outline_is_junk(p)]
    n = len(paragraphs)

    opening  = [_outline_first_sentence(p) for p in paragraphs[:3]]
    closing  = [_outline_first_sentence(p) for p in paragraphs[-2:]] if n > 5 else []
    middle = []
    if n > 5:
        candidates = list(range(3, n - 2))
        sample_n = min(6, len(candidates))
        step = max(1, len(candidates) // sample_n)
        for i in candidates[::step][:sample_n]:
            middle.append(_outline_first_sentence(paragraphs[i]))

    # 命名实体（jieba 词性标注）
    entities = []
    if _JIEBA_OK:
        try:
            freq: Counter = Counter()
            for w, flag in _pseg.cut(text[:30000]):
                w = w.strip()
                if len(w) >= 2 and flag in ('nr', 'nrt', 'nz', 'nt'):
                    freq[w] += 1
            entities = [{'name': n, 'count': c} for n, c in freq.most_common(5)]
        except Exception:
            pass

    # 对话密度
    quote_count = sum(text.count(q) for q in ('"', '“', '「', '『', '"'))
    speak_count = sum(text.count(s) for s in ('说道', '说：', '回答', '问道', '道：', '叫道', '笑道', '答道'))
    dialogue_density = round((quote_count + speak_count) / max(total_chars / 1000, 1), 1)

    summary_chars = sum(len(s) for s in opening + middle + closing) + 400
    compression_ratio = round(total_chars / max(summary_chars, 1), 1)

    return {
        'key': k,
        'book': book.strip(),
        'chapter': chapter.strip(),
        'total_chars': total_chars,
        'paragraph_count': n,
        'opening_sentences': opening,
        'middle_sentences': middle,
        'closing_sentences': closing,
        'main_entities': entities,
        'dialogue_density_per_1k': dialogue_density,
        'head_excerpt': text[:200],
        'tail_excerpt': text[-200:] if total_chars > 400 else '',
        'compression_ratio': compression_ratio,
    }
