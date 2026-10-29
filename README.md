# book-deep-read

A Claude Code skill for structured, critical deep reading of non-fiction books and long articles (output in the user's language; built and tested mainly in Chinese).

对一本非虚构书或一篇长文章做结构化深度解读：不只回答"书里说了什么"，还回答"凭什么这么说""说得对不对、现在还对不对""在知识地图上的位置""对我有什么用"。

## 能做什么

六层分析框架：

| 层 | 问题 | 产出 |
|---|---|---|
| 0 定位 | 这是本什么书 | 作者背景、写作语境、作者想解决的问题 |
| 1 结构 | 说了什么 | 框架图、贯穿全书的暗线、各章要点 |
| 2 论点 | 主张什么 | 一句话核心观点、主要观点、关键概念、原文金句 |
| 3 证据 | 凭什么 | 论证链（钢人原则）、证据质量评级、引用出处 |
| 4 批判 | 对不对 | 论证漏洞、优缺点、时效性检验、自称立场 vs 实际立场 |
| 5 坐标 | 在哪个位置 | 所属学派、对立观点及代表作、前承后继、跨领域关联 |
| 6 应用 | 有什么用 | 生活应用、行动清单、怎么读、自测题 |

两条底线：**每条信息都标来源**（【原文·位置】【模型知识】【检索·来源】【推断】），**先钢人再批评**。

## 三个档位

| | 速览 | 标准（默认） | 深度 |
|---|---|---|---|
| 触发说法 | "讲了啥""值不值得读" | "总结""解读""深度解读" | "精读""帮我核实""还站得住吗" |
| 阅读 | 抽读（目录 + 各章首尾 + 2–3 章全文） | 全文 | 全文 + 章节笔记 |
| 联网核实 | 不做 | 按需 | 必做 |
| 篇幅 | 1500–3000 字 | 5000–9000 字 | 8000–15000 字 |

只给书名时进入概览模式，开头声明信息来源受限，不编造原文引文。

## 支持的输入

EPUB、PDF、DOCX、HTML、TXT、MD、网页链接，或只有书名。MOBI/AZW 需先用 Calibre 转成 EPUB；扫描版 PDF 需先 OCR。

`scripts/extract_text.py` 负责把文件转成带定位标记的文本（`=== [章节] ===`、`--- [小节] ---`），估算 token 数并建议阅读策略，提示插图过多等问题；`--skim` 参数输出速览档用的抽读版本。

## 安装

把整个目录复制到 Claude Code 的 skills 目录：

```bash
git clone https://github.com/CedricZhang93/book-deep-read.git ~/.claude/skills/book-deep-read
```

依赖：Python 3。读取 PDF 需要 `pymupdf`（推荐）或 `pypdf`：

```bash
pip install pymupdf
```

## 使用

```
帮我解读一下 /path/to/book.epub
这本书讲了啥？值不值得读？ /path/to/book.pdf
《思考，快与慢》的观点现在还站得住吗？
```

报告保存为 `<短书名>_深度解读.md`，放在源文件同目录；对话里只给简短汇报。

## 目录结构

```
book-deep-read/
├── SKILL.md                       # 主流程：输入、档位、阅读、分析、标注、核实、输出、自查
├── references/
│   ├── analysis-guide.md          # 六层分析指南（含 16 类论证漏洞清单）
│   ├── report-template.md         # 报告模板
│   └── genre-adaptations.md       # 技术书、论文、文章、历史传记、自助书、访谈录、译本的调整
├── scripts/
│   └── extract_text.py            # 文本提取与篇幅统计
└── examples/
    └── 标准档示例_总体经济篇.md     # 标准档完整示例
```

不适用于小说、诗歌等纯文学作品。
