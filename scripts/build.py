#!/usr/bin/env python3
"""Build and validate the resource index with Python 3.10+ (standard library)."""
import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    "文献研究": "literature", "论文读写": "writing", "数据分析": "data",
    "图表展示": "figures", "专业软件": "software", "生医实验": "biomed",
    "知识协作": "knowledge", "通用科研": "general",
}
TYPES = {"Skill", "Skill + MCP", "MCP", "MCP 套件", "工具包", "插件", "CLI", "工具", "工作流"}
TYPE_LABELS = {
    "Skill": "AI 技能（Skill）", "Skill + MCP": "AI 技能 + 工具连接（Skill + MCP）",
    "MCP": "工具连接服务（MCP）", "MCP 套件": "工具连接套件（MCP）",
    "CLI": "命令行工具（CLI）",
}
DIRECTORIES = {"glama.ai", "mcpmarket.com", "skillsmp.com", "www.awesomeskills.dev",
               "www.pulsemcp.com", "mcps.live", "smithery.ai", "explainx.ai", "aiagentivo.com"}
SUPPLEMENT_SECTIONS = {
    "directories": "Skill 合集与资源目录", "workspaces": "科研工作台与智能助手",
    "templates": "研究模板", "related": "设计、传播与其他延伸工具",
    "review": "候选与待核验记录", "notes": "历史需求缺口记录",
}


def md(text):
    return re.sub(r"([\\`*_[\]<>|])", r"\\\1", text.replace("\n", " ").strip())


def bucket(item):
    if "Skill" in item["type"]:
        return "skills"
    return "mcp" if "MCP" in item["type"] else "tools"


def source_note(item):
    return " · 目录来源" if urlsplit(item["source_url"]).netloc in DIRECTORIES else ""


def sections(items):
    result = []
    for group, anchor in GROUPS.items():
        selected = sorted((x for x in items if x["category"] == group), key=lambda x: (x["name"].casefold(), x["id"]))
        result += [f'<a id="{anchor}"></a>', f"### {group}（{len(selected)}）", ""]
        for item in selected:
            label = TYPE_LABELS.get(item['type'], item['type'])
            result.append(f'- [{md(item["name"])}]({item["source_url"]}) — {md(item["description"])} `[{label}{source_note(item)}]`')
        if not selected:
            result.append("暂未收录。")
        result.append("")
    return "\n".join(result)


def validate(payload, topics):
    assert set(payload) == {"title", "snapshot_date", "source", "date_note", "resources"}, "Unexpected catalog metadata"
    date.fromisoformat(payload["snapshot_date"])
    items = payload["resources"]
    assert items, "Empty catalog"
    ids, urls = set(), set()
    fields = {"id", "name", "type", "category", "description", "source_url", "tags", "catalog_record_date"}
    for item in items:
        assert set(item) == fields, f'Unexpected fields: {item.get("id")}'
        assert re.fullmatch(r"[A-Za-z0-9-]+", item["id"]), "Invalid ID"
        assert item["id"] not in ids, f'Duplicate ID: {item["id"]}'
        ids.add(item["id"])
        assert item["type"] in TYPES and item["category"] in GROUPS, item["id"]
        for key in ("name", "description", "source_url"):
            assert isinstance(item[key], str) and item[key].strip(), f'{item["id"]}: missing {key}'
        url = urlsplit(item["source_url"])
        assert url.scheme == "https" and url.netloc and not url.username and not url.password, item["id"]
        assert not re.search(r'[\s<>"()]', item["source_url"]), f'Unsafe Markdown URL: {item["id"]}'
        assert item["source_url"] not in urls, f'Duplicate URL: {item["source_url"]}'
        urls.add(item["source_url"])
        assert isinstance(item["tags"], list) and all(isinstance(t, str) for t in item["tags"]), item["id"]
        if item["catalog_record_date"]:
            date.fromisoformat(item["catalog_record_date"])
    slugs = set()
    for topic in topics:
        assert re.fullmatch(r"[a-z0-9-]+", topic["slug"]) and topic["slug"] not in slugs, "Invalid topic slug"
        slugs.add(topic["slug"])
        assert topic["steps"] and topic["tools"] and topic["checklist"], topic["slug"]
        for tool in topic["tools"]:
            assert tool["id"] in ids, f'Unknown topic resource: {tool["id"]}'


def validate_coverage(payload, supplement, manifest):
    ids = {x['id'] for x in payload['resources']}
    urls = {x['source_url'] for x in payload['resources']}
    for item in supplement:
        assert item['id'] not in ids, f'Duplicate ID: {item["id"]}'
        ids.add(item['id'])
        assert item['section'] in SUPPLEMENT_SECTIONS, item['id']
        assert item['name'] and item['description'] and item['exclusion_reasons'], item['id']
        if item['catalog_record_date']:
            date.fromisoformat(item['catalog_record_date'])
        if item['source_url']:
            url = urlsplit(item['source_url'])
            assert url.scheme == 'https' and url.netloc and not url.username and not url.password, item['id']
            assert not re.search(r'[\s<>"()]', item['source_url']), item['id']
            assert item['source_url'] not in urls, f'Duplicate URL: {item["id"]}'
            urls.add(item['source_url'])
            assert item['section'] != 'notes', item['id']
        else:
            assert item['section'] == 'notes', item['id']
    baseline = []
    for source in manifest['sources']:
        assert source['count'] == len(source['ids']), source['name']
        baseline.extend(source['ids'])
    assert len(set(baseline)) == len(baseline), 'Duplicate source manifest IDs'
    assert set(baseline) <= ids, f'Missing original records: {sorted(set(baseline) - ids)}'


def render(payload, topics, supplement):
    supplement = [x for x in supplement if x['section'] not in {'directories', 'notes'}]
    items = payload["resources"]
    buckets = {kind: [x for x in items if bucket(x) == kind] for kind in ("skills", "mcp", "tools")}
    counts = {key: len(value) for key, value in buckets.items()}
    extra_counts = Counter(x['section'] for x in supplement)
    linked_total = len(items) + sum(bool(x['source_url']) for x in supplement)
    record_total = len(items) + len(supplement)
    extra_links = '\n'.join(f'- [{title}](lists/{key}.md)：{extra_counts[key]} 条。' for key, title in SUPPLEMENT_SECTIONS.items() if key not in {'directories', 'notes'})
    directory_count = sum(bool(source_note(x)) for x in items)
    topic_links = "\n".join(f'- [{t["title"]}](topics/{t["slug"]}.md) — {t["description"]}' for t in topics)
    toc = " · ".join(f'[{group}](#{anchor})' for group, anchor in GROUPS.items())
    readme = f'''<!-- Generated by scripts/build.py. Edit data or the renderer, then rebuild. -->
# 科研 AI 工具与技能库

**[加入科研 AI 社区 → 联系 Moe 申请](https://skill.createsci.com/community)** · 说明研究方向与加入目的，人工审核后邀请加入。

**一个帮科研人员找工具、找教程、参考实际用法的开源资源目录。**

查文献、读论文、分析数据、画科研图、准备组会，遇到这些任务时，你可以在这里找到相关工具和学习资料，再前往原作者页面使用。每个条目尽量配上中文用途说明，方便你判断是否适合自己的研究。

这里的 **Skill** 是给 AI 的操作步骤与规则，**MCP** 用来连接 AI 与外部软件或数据；同时也收录独立科研软件、插件和脚本。不熟悉这些名称，也可以直接按任务找。

| 你想做什么 | 这里提供什么 | 从哪里开始 |
| --- | --- | --- |
| 找一个能帮忙的科研工具 | 按用途整理的 Skill、MCP、软件与原项目链接 | [工具清单](lists/all.md) · [网站筛选](https://skill.createsci.com/#catalog) |
| 学会一个方法或工具 | 图文教程、视频、课程、代码、文档与经验记录 | [教程目录](TUTORIALS.md) · [网站搜索](https://skill.createsci.com/tutorials) |
| 看一个研究任务具体怎么做 | 论文处理、数据分析、组会汇报的任务路线与实践案例 | [任务专题](https://skill.createsci.com/topics) · [实践案例](https://skill.createsci.com/cases) |
| 让 AI 帮自己找工具 | 一段可复制的使用指令，让支持联网的 AI 查询本站目录 | [复制使用指令](https://skill.createsci.com/guides/use-this-site) |

**第一次来？** 打开[在线网站](https://skill.createsci.com/)，按你正在做的任务找工具；已经知道想学什么，就直接查[教程目录](TUTORIALS.md)。GitHub 保留完整清单、来源与投稿入口，网站方便搜索和筛选。

收录是为了方便发现资源，不代表所有工具都已实测。工具按原项目说明安装或使用；教程保留作者与原文链接，付费或访问限制会单独标注。

[访问网站](https://skill.createsci.com/) · [教程目录](TUTORIALS.md) · [使用指南](https://skill.createsci.com/guides) · [教程计划](TUTORIAL-PLAN.md) · [贡献资源](CONTRIBUTING.md)

[![科研 AI 工具与技能库：找到好工具，也找到好用法。访问 skill.createsci.com](assets/research-skills-cover-zh.png)](https://skill.createsci.com/)

## 加入科研 AI 社区 · 申请制

**[联系 Moe，申请加入社区 →](https://skill.createsci.com/community)**

和认真做科研的人一起交流 Skill、MCP、科研软件与教程，分享真实问题、使用经验和踩坑记录。我们希望建设一个重视内容、愿意互相帮助的高质量社区，新手也欢迎。

**加入前请先联系我，并说明你的研究方向／正在做的项目、加入目的，以及希望交流的问题或经验。** 添加个人微信时备注“科研社区申请”。我们会根据加入目的与社区主题的匹配程度进行人工审核，通过后邀请加入。

社区采用 **联系维护者 → 说明目的 → 审核 → 邀请加入** 的方式，不公开微信群二维码。请认真提问、尊重作者和来源，不刷屏、不发无关广告。

**[查看联系方式与申请说明](https://skill.createsci.com/community)**

## 征集：把你做过、用过的好工具分享出来

[![优秀科研工具征集：好用的科研工具，一起分享出来。科研技能、MCP、软件、插件、脚本，欢迎推荐与自荐](assets/contribute-research-tools.png)](https://github.com/ZMoe2024/awesome-research-skills/issues/new?template=add-resource.yml)

你有没有做过一个能省下重复劳动的科研工具，或用过一个想推荐给同行的项目？欢迎来这里分享。

**科研 AI 技能（Skill）、工具连接服务（MCP）、桌面软件、在线工具、插件、脚本和工作流，都欢迎。** 查文献、读论文、分析数据、画科研图、准备汇报、操作专业软件，只要能解决一个具体问题，就值得介绍。

欢迎作者自荐，也欢迎使用者推荐。投稿只需写清楚：**项目叫什么、链接在哪里、能解决什么问题**。如果有使用截图、示例结果或上手教程，也欢迎一起附上；尚未实测请如实说明。

我们会核对项目来源与用途，收录时保留原项目链接和来源信息，尊重作者署名与许可。有完整实践记录的项目，也欢迎参与后续教程和案例共建。

**[推荐／自荐一个工具](https://github.com/ZMoe2024/awesome-research-skills/issues/new?template=add-resource.yml)** · [查看投稿说明](CONTRIBUTING.md) · [分享教程选题](https://github.com/ZMoe2024/awesome-research-skills/issues/new?template=tutorial.yml)

**[查看资源清单](lists/all.md)**：{record_total - extra_counts['review']} 项资源，另有 {extra_counts['review']} 条候选与待核验记录。按具体项目或工具条目整理，用途与可用性以原项目文档为准。

## 全部目录

- [AI 技能清单（Skill）](#skills)：{counts['skills']} 项，含同时提供工具连接的项目。
- [工具连接服务（MCP）](lists/mcp.md)：{counts['mcp']} 项。
- [其他科研工具](lists/tools.md)：{counts['tools']} 项。
{extra_links}

前三份清单对应网站展示的 {len(items)} 项，并补充科研工作台、研究模板和延伸工具。不同分组不重复计数。

## 从这里开始

1. 找到下面与你当前任务对应的分类，或先看一个专题。
2. 打开资源链接，确认项目功能、依赖、费用与客户端要求。
3. 用一份小样本试跑，核对输出，再放进自己的科研流程。

### 不熟悉这些名称？

| 名称 | 用来做什么 | 例子 |
| --- | --- | --- |
| AI 技能（Skill） | 给 AI 一套完成任务的步骤与规则，有时附带脚本或模板 | 按固定要求读论文、检查引用、整理汇报 |
| 工具连接服务（MCP） | 让支持的 AI 客户端访问外部软件或数据 | 查询文献库、调用统计软件 |
| 智能助手（Agent） | 结合指令和工具推进多步任务 | 查找资料、整理文件，再生成初稿 |
| 命令行工具（CLI） | 通过终端命令运行的软件 | 批量转换 PDF、导出数据 |

先读每个项目后面的中文用途，再决定是否打开原项目。英文项目名保留原写法，方便搜索和核对；具体配置要求以各自文档为准。

## 科研专题

{topic_links}

## 教程目录

**[查看科研教程与文章目录](TUTORIALS.md)** · [网站搜索与筛选](https://skill.createsci.com/tutorials)

图文、视频、课程、代码、文档和研究经验按主题集中列出；不按质量排名，付费或访问限制分别标注。

## 教程征集与计划

[![科研实用教程征集：把科研经验，写成一篇好教程。图文、视频、代码笔记、实操记录，欢迎分享和推荐](assets/contribute-tutorials.png)](https://github.com/ZMoe2024/awesome-research-skills/issues/new?template=tutorial.yml)

**你跑通过的方法、踩过的坑，也能帮后来的人少走弯路。** 欢迎投稿原创教程、推荐优秀教程，或分享一次完整的科研工具实操。图文、视频、代码笔记（Notebook）、软件上手指南都可以，围绕 Skill、MCP、科研软件或具体研究任务展开。

介绍教程讲什么、适合谁，再附上正文或原文链接即可。如果有样本、步骤、结果和排错记录，也欢迎一起分享。我们会核对来源与内容，保留作者署名和原文链接；未验证的步骤会如实说明。

**[投稿／推荐一篇教程](https://github.com/ZMoe2024/awesome-research-skills/issues/new?template=tutorial.yml)** · [提出想看的选题](https://github.com/ZMoe2024/awesome-research-skills/issues/new?template=tutorial.yml) · [查看教程征集说明与计划](TUTORIAL-PLAN.md)

已有指南与案例可以直接阅读，后续教程按下面的顺序准备，也欢迎参与共建。

| 内容 | 状态 | 入口或目标 |
| --- | --- | --- |
| 一段话，让 AI 来本站找工具 | 已有使用指南 | [在线阅读](https://skill.createsci.com/guides/use-this-site) |
| 一篇论文 → 带页码笔记与组会提纲 | 已有样本案例 | [查看案例与文件](https://skill.createsci.com/cases/attention-paper-notes) |
| 文献检索与 PDF 整理 | 计划中 | 从题名或 DOI 清单得到可核对的文献记录与归档文件 |
| 论文 PDF 解析与表格核对 | 计划中 | 完成一个解析工具的配置、小样本运行与原页对照 |
| 组会汇报与科研图 | 计划中 | 从论文和提纲制作可编辑图与幻灯片 |
| 数据分析与结果复现 | 计划中 | 从样本数据生成结果表、图和可重复运行的记录 |

[查看完整教程计划、已有内容与投稿方式](TUTORIAL-PLAN.md)。计划中的教程尚未发布，完成样本运行和结果核对后再提供正文入口。

## 让 AI 帮你挑

复制下面这段话，把最后一句换成你的问题。支持读取仓库或联网的 AI 可以据此查找；无法读取时，可将相关清单内容一起提供。

> 请从这个 Awesome Research Skills 仓库的 lists/all.md 和 topics 中，为我的科研任务寻找合适的工具。需要检索结构化信息时读取 data/full-catalog.json。优先给出 1–3 个匹配项，说明用途、原项目链接、使用条件和第一步操作；先核对原项目文档，不要编造功能、安装命令或已测试结论。注意条目的分组与状态，不将历史需求缺口当成工具。如果没有合适的收录，请明确说明。我的任务是：【在这里写下你的问题】。

<a id="skills"></a>

## AI 技能清单（Skill）

{toc}

类型与用途沿用现有目录记录，尚未逐项重新实测。`目录来源` 表示当前链接指向第三方目录，原项目地址仍待核实；这些条目保留供检索，不作为已确认的推荐。其他链接也不等于经过运行验证。

{sections(buckets['skills'])}
## 更多科研工具

- [工具连接服务（MCP）](lists/mcp.md)：{counts['mcp']} 项；兼有 AI 技能的项目已归入上面的技能清单。
- [其他工具清单](lists/tools.md)：{counts['tools']} 项软件、CLI、工具包、插件和工作流。
- [资源总表](lists/all.md)：{record_total - extra_counts['review']} 项资源与 {extra_counts['review']} 条待核验记录。
- [完整 JSON 数据](data/full-catalog.json)：保留稳定 ID 与分组状态，方便检索、同步和二次整理。

## 收录与更新

初始数据快照：**{payload['snapshot_date']}**，整理自[科研工具网站](https://skill.createsci.com/)使用的收录库。原站展示条目中 {directory_count} 项的链接仍为第三方目录中的具体工具页面，已标注，待补充原项目链接。快照日期表示整理时间；条目的原记录日期不代表最新版本、链接核验时间或测试日期。

欢迎通过 Issue 补充资源、报告失效链接，或按[贡献指南](CONTRIBUTING.md)提交 PR。收录说明、去重规则和本地检查见 [DATA.md](DATA.md)。

本仓库不镜像第三方 Skill 正文或工具源码。原项目的代码、名称、商标与文档由各自权利人持有，使用时遵循其许可。仓库原创整理内容与维护脚本采用 [MIT License](LICENSE)。
'''
    files = {"README.md": readme}
    all_body = ['# 科研资源总表', '', '[返回首页](../README.md) · [数据与核对说明](../DATA.md)', '',
                f'{record_total - extra_counts["review"]} 项资源，另有 {extra_counts["review"]} 条候选与待核验记录。', '',
                '用途与类型沿用收录信息，未逐项重新实测；候选和原站排除项保留状态说明。', '',
                '## 原站展示资源', '', sections(items)]
    for key, title in SUPPLEMENT_SECTIONS.items():
        if key in {'directories', 'notes'}:
            continue
        selected = sorted((x for x in supplement if x['section'] == key), key=lambda x: (x['name'].casefold(), x['id']))
        intro = {
            'directories': '原站按资源类型排除了这些目录、合集或市场入口。它们可用于继续发现 Skill；收录一个合集不等于已逐项审查其中所有内容。',
            'workspaces': '原站排除了 workspace 类型，现保留其科研工作台、Agent 系统与组合工作流入口。',
            'templates': '原站排除了模板类型，现保留研究组织与复现模板。',
            'related': '这些记录被原站的前端设计、中文社媒分类或社媒关键词规则过滤。保留原分类，供设计、传播等延伸任务检索。',
            'review': '这些记录原先标为 candidate、prompt-only，或被原站按名称排除。排除原因不一定等于项目失效；本次未重新验证，不应作为已确认可用的推荐。',
            'notes': '这些是没有项目链接的历史需求记录，不计入资源数量。原状态 covered 表示原目录标记已覆盖，不表示现在仍是缺口。',
        }[key]
        body = [f'# {title}', '', '[返回首页](../README.md) · [完整总表](all.md)', '', f'共 {len(selected)} 条。{intro}', '']
        entries = []
        for item in selected:
            name = f'[{md(item["name"])}]({item["source_url"]})' if item['source_url'] else md(item['name'])
            entries += [f'### {name}', '', f'{md(item["description"])}', '',
                        f'- ID：`{item["id"]}`；原类型：`{item["original_type"]}`；原分类：{md(item["category"])}。',
                        f'- 原状态：`{item["status"]}`；执行标记：`{item["execution_level"]}`。',
                        f'- 原站过滤原因：`{", ".join(item["exclusion_reasons"])}`（[说明](../DATA.md#原站过滤原因)）。', '']
        files[f'lists/{key}.md'] = '\n'.join(body + entries)
        all_body += [f'## {title}（{len(selected)}）', '', intro, ''] + entries
    files['lists/all.md'] = '\n'.join(all_body)
    full_items = [dict(x, section=bucket(x), record_kind='resource') for x in items]
    full_items += [dict(x, type=x['original_type'], record_kind='candidate' if x['section'] == 'review' else 'resource') for x in supplement]
    files['data/full-catalog.json'] = json.dumps({'snapshot_date': payload['snapshot_date'], 'record_count': record_total, 'resource_count': record_total - extra_counts['review'], 'candidate_count': extra_counts['review'], 'linked_record_count': linked_total, 'records': full_items}, ensure_ascii=False, indent=2) + '\n'
    for kind, title in (("mcp", "工具连接服务（MCP）"), ("tools", "其他科研工具")):
        files[f"lists/{kind}.md"] = f'''<!-- Generated by scripts/build.py. -->
# {title}

[返回首页](../README.md) · [收录说明](../DATA.md)

共 {counts[kind]} 项，按科研任务分类。Skill + MCP 已放入首页 Skill 清单；条目不重复计数。

类型与用途来自目录记录，未逐项重新实测。标有 `目录来源` 的链接仍待补充原项目地址。费用、依赖和可用性以原项目说明为准。

{toc}

{sections(buckets[kind])}
'''
    by_id = {x["id"]: x for x in items}
    for topic in topics:
        body = [f'# {topic["title"]}', '', '[返回首页](../README.md#科研专题)', '', topic['description'], '',
                f'适合：{topic["audience"]}。', '', f'预期产出：{topic["output"]}。', '', '## 操作路线', '']
        for index, step in enumerate(topic['steps'], 1):
            body += [f'{index}. **{step["title"]}**：{step["text"]}']
        body += ['', '## 按需求选工具', '', '以下是基于目录信息整理的操作建议，具体配置以原项目文档为准。', '']
        for tool in topic['tools']:
            item = by_id[tool['id']]
            body += [f'### [{md(item["name"])}]({item["source_url"]})', '',
                     f'类型：{TYPE_LABELS.get(item["type"], item["type"])}。', '', f'- 适合：{tool["fit"]}', f'- 第一步：{tool["start"]}',
                     f'- 检查：{tool["check"]}', f'- 使用条件与局限：{tool["limit"]}', '']
        body += ['## 完成前检查', ''] + [f'- [ ] {x}' for x in topic['checklist']] + ['']
        files[f'topics/{topic["slug"]}.md'] = '\n'.join(body)
    return {path: content.rstrip() + '\n' for path, content in files.items()}


def check_local_links():
    for document in ROOT.rglob('*.md'):
        if '.git' in document.parts:
            continue
        content = document.read_text(encoding='utf-8')
        for link in re.findall(r'\]\(([^)]+)\)', content):
            if urlsplit(link).scheme:
                continue
            path, _, fragment = unquote(link).partition('#')
            target = (document.parent / path).resolve() if path else document
            assert target.is_relative_to(ROOT), f'Link outside repository: {document}: {link}'
            assert target.is_file(), f'Broken local link: {document}: {link}'
            if fragment and target.suffix == '.md':
                text = target.read_text(encoding='utf-8')
                headings = re.findall(r'^#+ (.+)$', text, re.M)
                anchors = {re.sub(r'[^\w\- ]', '', h.lower()).replace(' ', '-') for h in headings}
                anchors.update(re.findall(r'<a id="([^"]+)"', text))
                assert fragment in anchors, f'Unknown anchor: {document}: {link}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate data, generated files and local links without writing')
    args = parser.parse_args()
    payload = json.loads((ROOT / 'data/resources.json').read_text(encoding='utf-8'))
    topics = json.loads((ROOT / 'data/topics.json').read_text(encoding='utf-8'))
    supplement = json.loads((ROOT / 'data/supplement.json').read_text(encoding='utf-8'))
    manifest = json.loads((ROOT / 'data/source-manifest.json').read_text(encoding='utf-8'))
    validate(payload, topics)
    validate_coverage(payload, supplement, manifest)
    expected = render(payload, topics, supplement)
    for relative, text in expected.items():
        file = ROOT / relative
        if args.check:
            assert file.exists() and file.read_text(encoding='utf-8') == text, f'Run python scripts/build.py: {relative}'
        else:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(text, encoding='utf-8', newline='\n')
    check_local_links()
    counts = Counter(bucket(item) for item in payload['resources'])
    print(f'PASS: {len(payload["resources"]) + len(supplement)} records; original-source coverage complete; {dict(counts)}; {len(topics)} topics; local links and generated files valid.')


if __name__ == '__main__':
    try:
        main()
    except (AssertionError, ValueError, KeyError, TypeError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        sys.exit(1)
