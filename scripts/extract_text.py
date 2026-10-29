"""把 EPUB / PDF / DOCX / HTML / TXT / MD 转成带定位标记的纯文本，并给出篇幅统计和阅读策略建议。

用法:
    python -I extract_text.py <输入文件> <输出.txt>           # 全文
    python -I extract_text.py <输入文件> <输出.txt> --skim    # 速览档：目录 + 每章开头和结尾

输出文本中每个章节（EPUB 的 spine 项、DOCX 的标题段）或每一页（PDF）前面都有一行
`=== [定位] ===` 标记，章节内的小标题变成 `--- [小节] ---` 标记，解读时用它们标注引用位置。
统计信息打印到 stdout。
"""
import html
import os
import re
import shutil
import subprocess
import sys
import zipfile
from xml.etree import ElementTree as ET

LINE_WIDTH = 200          # 超过这个长度的行按句子折行，避免 Read 单行超限
SKIM_HEAD, SKIM_TAIL = 1500, 800
SUBHEAD = re.compile(r"(?m)^#{1,4} (.+)$")


def strip_html(text):
    text = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", text)
    text = re.sub(r"(?i)</(p|h[1-6]|div|li|tr|blockquote)>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<h([1-6])[^>]*>", lambda m: "\n" + "#" * int(m.group(1)) + " ", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = re.sub(r"[ \t　]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def local(tag):
    return tag.rsplit("}", 1)[-1]


def extract_epub(path):
    sections, images = [], 0
    with zipfile.ZipFile(path) as z:
        container = ET.fromstring(z.read("META-INF/container.xml"))
        opf_path = next(e.get("full-path") for e in container.iter() if local(e.tag) == "rootfile")
        opf_dir = os.path.dirname(opf_path)
        opf = ET.fromstring(z.read(opf_path))
        manifest = {}
        for e in opf.iter():
            if local(e.tag) == "item":
                manifest[e.get("id")] = e.get("href")
        spine = [e.get("idref") for e in opf.iter() if local(e.tag) == "itemref"]
        for idref in spine:
            href = manifest.get(idref)
            if not href:
                continue
            name = os.path.normpath(os.path.join(opf_dir, href)).replace("\\", "/")
            try:
                raw = z.read(name).decode("utf-8", errors="replace")
            except KeyError:
                continue
            images += len(re.findall(r"(?i)<(img|image)\b", raw))
            body = strip_html(raw)
            if body:
                sections.append((href, body))
    # 很多 EPUB 把章节标题单独放一页：把只有标题的短页并入下一页，并用首行做定位标签
    merged, pending = [], ""
    for href, body in sections:
        if len(body) < 40 and "\n" not in body:
            pending = (pending + " " + body).strip()
            continue
        if pending:
            body = pending + "\n" + body
            pending = ""
        first = body.splitlines()[0].lstrip("# ").strip()[:30]
        merged.append((f"{first} | {os.path.basename(href)}", body))
    if pending:
        merged.append((pending[:30], pending))
    return merged, images


def load_fitz():
    try:
        import pymupdf as fitz
        return fitz
    except ImportError:
        try:
            import fitz
            return fitz
        except ImportError:
            return None


def extract_pdf(path):
    """返回 (逐页列表, 图片数或 None, 目录[(级别, 标题, 起始页)])"""
    fitz = load_fitz()
    if fitz:
        pages, xrefs = [], set()
        with fitz.open(path) as doc:
            for i, page in enumerate(doc, 1):
                pages.append((f"p.{i}", page.get_text().strip()))
                xrefs.update(img[0] for img in page.get_images(full=True))
            toc = [(lvl, title.strip(), pg) for lvl, title, pg in doc.get_toc()]
        return pages, len(xrefs), toc
    try:
        from pypdf import PdfReader
        pages = [(f"p.{i}", (page.extract_text() or "").strip()) for i, page in enumerate(PdfReader(path).pages, 1)]
        return pages, None, []
    except ImportError:
        pass
    if shutil.which("pdftotext"):
        out = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, encoding="utf-8").stdout
        return [(f"p.{i}", p.strip()) for i, p in enumerate(out.split("\f"), 1)], None, []
    sys.exit("无法读取 PDF：请安装 pymupdf 或 pypdf（pip install pymupdf），或改用 pdf skill。")


def group_pdf_pages(pages, toc):
    """速览用：按 PDF 目录的一级条目把页合并成章；没有目录就每 10 页一组。"""
    starts = [(title, pg) for lvl, title, pg in toc if lvl == 1 and pg > 0]
    if len(starts) < 3:
        starts = [(title, pg) for lvl, title, pg in toc if lvl <= 2 and pg > 0]
    if len(starts) < 3:
        starts = [(f"p.{i}", i) for i in range(1, len(pages) + 1, 10)]
    if starts[0][1] > 1:
        starts.insert(0, ("前置部分", 1))
    groups = []
    for k, (title, start) in enumerate(starts):
        end = starts[k + 1][1] - 1 if k + 1 < len(starts) else len(pages)
        if end < start:
            continue
        body = "\n".join(b for _, b in pages[start - 1:end])
        groups.append((f"{title[:40]} | p.{start}–{end}", body))
    return groups


def extract_docx(path):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
        images = sum(1 for n in z.namelist() if n.startswith("word/media/"))
    sections, title, buf = [], "开头", []
    for p in root.iter():
        if local(p.tag) != "p":
            continue
        style = next((s.get(next(iter(s.attrib))) for s in p.iter() if local(s.tag) == "pStyle"), "") or ""
        text = "".join(t.text or "" for t in p.iter() if local(t.tag) == "t").strip()
        if not text:
            continue
        if re.match(r"(?i)(heading|标题)\s*[12]$", style):
            if buf:
                sections.append((title, "\n".join(buf)))
            title, buf = text, []
        buf.append(text)
    if buf:
        sections.append((title, "\n".join(buf)))
    return sections, images


def read_text_file(path):
    data = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_plain(path, is_html):
    text = read_text_file(path)
    images = len(re.findall(r"(?i)<img\b|!\[[^\]]*\]\(", text))
    if is_html:
        text = strip_html(text)
    # 按 Markdown 标题或“第X章”切分，便于定位
    parts = re.split(r"(?m)^(?=#{1,2} |第[一二三四五六七八九十百零〇\d]+[章篇部])", text)
    sections = []
    for i, part in enumerate(p for p in parts if p.strip()):
        head = part.strip().splitlines()[0][:40]
        sections.append((f"{i + 1} {head}", part.strip()))
    return sections or [("全文", text)], images


def wrap_long_lines(text):
    out = []
    for line in text.split("\n"):
        while len(line) > LINE_WIDTH:
            cut = max(line.rfind(p, 0, LINE_WIDTH) for p in "。！？；.!?;")
            if cut < LINE_WIDTH // 3:
                cut = LINE_WIDTH - 1
            out.append(line[:cut + 1])
            line = line[cut + 1:].lstrip()
        out.append(line)
    return "\n".join(out)


def mark_subheads(body):
    """首行保留为章名，其余 Markdown 标题行改成 --- [小节] --- 定位标记。"""
    lines = body.split("\n")
    rest = SUBHEAD.sub(lambda m: f"--- [{m.group(1).strip()[:40]}] ---", "\n".join(lines[1:]))
    return lines[0] + ("\n" + rest if rest else "")


def subsections(body):
    """返回 [(小节名, 字符数)]"""
    parts = re.split(r"(?m)^--- \[(.+?)\] ---$", body)
    return [(parts[i], len(parts[i + 1].strip())) for i in range(1, len(parts) - 1, 2)]


def skim(body):
    if len(body) <= SKIM_HEAD + SKIM_TAIL + 300:
        return body
    omitted = len(body) - SKIM_HEAD - SKIM_TAIL
    return f"{body[:SKIM_HEAD]}\n……（中略 {omitted} 字）……\n{body[-SKIM_TAIL:]}"


def count_chars(text):
    cjk = len(re.findall(r"[㐀-鿿豈-﫿]", text))
    words = len(re.findall(r"[A-Za-z]+", text))
    return cjk, words


def main():
    args = [a for a in sys.argv[1:] if a != "--skim"]
    skim_mode = "--skim" in sys.argv[1:]
    if len(args) != 2:
        sys.exit(__doc__)
    src, out = args
    ext = os.path.splitext(src)[1].lower()
    toc = []
    if ext == ".epub":
        sections, images = extract_epub(src)
    elif ext == ".pdf":
        sections, images, toc = extract_pdf(src)
    elif ext == ".docx":
        sections, images = extract_docx(src)
    elif ext in (".html", ".htm", ".xhtml"):
        sections, images = extract_plain(src, True)
    elif ext in (".txt", ".md", ".markdown"):
        sections, images = extract_plain(src, False)
    elif ext in (".mobi", ".azw", ".azw3"):
        sys.exit("MOBI/AZW 请先用 Calibre 转换：ebook-convert 输入.mobi 输出.epub，再处理 EPUB。")
    else:
        sys.exit(f"不支持的格式：{ext}")

    n_pages = len(sections) if ext == ".pdf" else None
    blank_pages = sum(1 for _, b in sections if len(b) < 50) if n_pages else 0
    full = "\n".join(b for _, b in sections)
    if ext == ".pdf" and skim_mode:
        sections = group_pdf_pages(sections, toc)
    # PDF 提取文本里的 “# ” 多是代码注释，不是标题
    sections = [(loc, wrap_long_lines(body if ext == ".pdf" else mark_subheads(body))) for loc, body in sections]

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        if skim_mode:
            f.write("=== [目录] ===\n")
            f.write("\n".join(f"{i}. {loc}（{len(b)} 字符）" for i, (loc, b) in enumerate(sections, 1)) + "\n")
        for loc, body in sections:
            f.write(f"\n=== [{loc}] ===\n{skim(body) if skim_mode else body}\n")

    cjk, words = count_chars(full)
    # 粗略 token 估算：中文约 1 字 ≈ 1 token，英文约 1 词 ≈ 1.3 token
    tokens = int(cjk * 1.0 + words * 1.3)
    print(f"输出：{out}" + ("（速览抽读版）" if skim_mode else ""))
    print(f"分段数：{len(sections)}  中文字数：{cjk}  英文词数：{words}  估算 tokens：约 {tokens}（全书）")
    if n_pages and blank_pages > n_pages * 0.5:
        print("⚠️ 超过一半的页几乎没有文字，可能是扫描版 PDF，需要 OCR（可用 pdf skill）。")
    if images:
        dense = images >= 50 or (n_pages and images >= 10 and images / n_pages >= 0.1)
        print(f"图片数：{images}" + ("  ⚠️ 本书依赖插图，文字提取会丢失图示信息，报告的“解读依据”里要说明；核心概念若主要靠图讲解，可用 Read 直接看对应页。" if dense else ""))
    if skim_mode:
        print("建议策略：读完本文件，再从全文中挑 2–3 个核心章节通读（见 SKILL.md 速览档）。")
    elif tokens < 120_000:
        print("建议策略：全文通读（按 25k tokens 左右分批读完整文件）。")
    else:
        print("建议策略：长书模式，逐章读并写章节笔记，最后综合（见 SKILL.md）。")
    if len(sections) > 80:
        print(f"\n共 {len(sections)} 段，省略逐段列表；用 grep 搜索 '=== \\[' 查看定位标记。")
        return
    show_sub = sum(len(subsections(b)) for _, b in sections) <= 150
    print("\n各段篇幅（定位 / 字符数）：")
    for loc, body in sections:
        print(f"  {loc[:50]:<50} {len(body)}")
        if show_sub:
            for name, n in subsections(body):
                print(f"      └ {name[:44]:<44} {n}")


if __name__ == "__main__":
    main()
