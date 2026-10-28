# pixiv-skill

一个给 AI 助手用的 Pixiv 技能：搜索、看排行、查详情、下载插画、漫画、动图和小说。

技能本身是一份 `SKILL.md` 加一个 Python 脚本，遵循通用的 [Agent Skills](https://agentskills.io) 格式，所以 Claude Code、Codex、OpenClaw、Hermes Agent、DeepSeek Harness 等支持技能的助手都能用。脚本也可以脱离助手，直接在命令行里用。

## 功能

- **搜索**：插画、漫画、小说分开搜；可按最新、最旧、热门（男性向 / 女性向）排序；可按收藏数筛选；可只看全年龄或只看 R-18。
- **排行榜**：日榜、周榜、月榜、新人榜、原创榜、AI 榜、R-18 榜等，可按插画、漫画、动图过滤，可看历史日期。
- **详情**：作品、小说、小说系列（含章节目录）、画师（含作品数和最新作品）。
- **下载**：
  - 单张图直接保存原图；
  - 多页作品合成一个 PDF（超过 50 页自动分卷），也可以存成图片文件夹；
  - 动图（ugoira）转成 GIF；
  - 小说存成 TXT，Pixiv 的注音、章节、插图标记会转成可读文字；
  - 整个小说系列一键下载，合并成一个 TXT 或每篇一个文件。
- **链接直接用**：作品、小说、系列、画师主页的链接都能自动识别。
- **对助手友好**：结果是纯文本（或 `--json`），不用 Markdown，聊天软件里也能正常显示；每个下载的文件都会打印 `SAVED: 路径`；出错有明确的退出码。

## 安装

先装 Python 3.9 或更新版本，然后：

```bash
git clone https://github.com/elither-gpt/pixiv-skill.git
cd pixiv-skill
pip install -r requirements.txt
```

再把整个文件夹放到你的助手读取技能的目录。文件夹名建议用 `pixiv`：

| 助手 | 技能目录 |
| --- | --- |
| Claude Code | `~/.claude/skills/pixiv/` |
| Codex | `~/.codex/skills/pixiv/` |
| OpenClaw | `~/.openclaw/workspace/skills/pixiv/` |
| Hermes Agent | `~/.hermes/skills/pixiv/`（Windows 为 `%LOCALAPPDATA%\hermes\skills\pixiv\`） |
| 通用 | `~/.agents/skills/pixiv/` 或项目里的 `.agents/skills/pixiv/` |

各家目录可能会变，以对应助手的文档为准。

### DeepSeek Harness（dsh）

可以像上面一样放进 `~/.dsh/skills/pixiv/`，也可以当插件装，装好后技能会自动出现：

```bash
dsh plugin --profile web add github:elither-gpt/pixiv-skill
```

把 `web` 换成你用的配置名（如 `tui`、`headless`）。Python 依赖仍要自己装：`pip install -r requirements.txt`。

## 登录（可选）

不登录也能搜索和下载全年龄作品。R-18 作品、R-18 排行榜需要你自己的 Pixiv 登录凭证，其实只要 `PHPSESSID` 这一个值。

最省事的办法：

```bash
python scripts/pixiv.py cookie --login
```

脚本会打开一个全新的临时浏览器窗口（支持 Chrome、Edge、Brave、Chromium），你在里面自己登录 Pixiv，成功后窗口自动关闭，Cookie 自动保存。这个窗口不会读取你平时浏览器里的任何数据，用完就删；账号密码也只在 Pixiv 官网上输入，脚本碰不到。

也可以在浏览器开发者工具里手动复制 `PHPSESSID`，再运行 `python scripts/pixiv.py cookie --set -` 粘贴进去。各浏览器的详细步骤、手机上怎么弄、常见问题，见 **[获取 Cookie 教程](docs/cookie.md)**。

凭证保存在本机：Windows 是 `%APPDATA%\pixiv-skill\cookie.json`，其他系统是 `~/.config/pixiv-skill/cookie.json`。它不在技能文件夹里，更新技能不会丢，也不会被误传到 Git。也可以用环境变量 `PIXIV_PHPSESSID` 或 `PIXIV_COOKIE` 代替。

R-18 内容还需要在 Pixiv 账号设置里打开 R-18 显示。

**不要把凭证发给 AI 或贴进聊天里**，它等同于你的账号登录状态。

## 命令行用法

```bash
python scripts/pixiv.py search 初音ミク -n 10
python scripts/pixiv.py search 猫 -t novel -o popular
python scripts/pixiv.py search 風景 -b 1000          # 本页只留收藏 1000 以上的
python scripts/pixiv.py rank weekly -t manga
python scripts/pixiv.py info https://www.pixiv.net/artworks/12345678
python scripts/pixiv.py info s:1234567                # 小说系列和章节目录
python scripts/pixiv.py user https://www.pixiv.net/users/12345 -t novel
python scripts/pixiv.py download 12345678 n:23456789 --out ./downloads
python scripts/pixiv.py download https://www.pixiv.net/novel/series/1234567
python scripts/pixiv.py cookie                        # 检查登录状态
python scripts/pixiv.py cookie --login                # 打开浏览器登录并保存 Cookie
```

每个命令都可以加 `--help` 看完整参数，加 `--json` 输出机器可读结果。

下载目录：`--out` 指定的目录 > 环境变量 `PIXIV_DOWNLOAD_DIR` > 当前目录下的 `pixiv-downloads`。

### 目标写法

| 写法 | 含义 |
| --- | --- |
| `https://www.pixiv.net/artworks/123` 或 `123` | 插画 / 漫画 / 动图 |
| `https://www.pixiv.net/novel/show.php?id=123` 或 `n:123` | 小说 |
| `https://www.pixiv.net/novel/series/123` 或 `s:123` | 小说系列 |
| `https://www.pixiv.net/users/123` 或 `u:123` | 画师 |

### 退出码

| 代码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 1 | 其他错误，或一次下多个时有部分失败 |
| 2 | 参数写错或看不懂目标 |
| 3 | 没登录、凭证失效，或账号没开 R-18 显示 |
| 4 | 作品不存在、已删除或不公开 |
| 5 | 网络问题、Pixiv 服务器出错或被限流（已自动重试过） |

## 注意事项

- 热门排序需要 Pixiv 会员，没有会员时 Pixiv 会悄悄按最新排序返回。
- 插画和漫画的搜索结果里没有收藏数，用 `-b` 筛选时要逐个查询，每个约 1 秒，而且只筛当前这一页（60 个）。只想看热门作品，用排行榜更快。
- 脚本默认每次请求至少间隔 0.7 秒，请不要调得太低，也不要拿来大批量爬取。
- 下载的作品版权归原作者所有，仅供个人欣赏，未经作者许可请勿转载。
- 本项目与 Pixiv 官方无关，用的是 Pixiv 网页版自己用的接口，Pixiv 改版后可能失效。

## 开发

```bash
python -m unittest discover -s tests   # 离线测试，不需要联网
```

代码结构：

| 文件 | 作用 |
| --- | --- |
| `scripts/pixiv.py` | 入口 |
| `scripts/pixiv_skill/api.py` | Pixiv 接口：限速、重试、错误分类 |
| `scripts/pixiv_skill/models.py` | 把不同接口的返回统一成一种作品格式，并生成文字输出 |
| `scripts/pixiv_skill/download.py` | 下载、合成 PDF、转 GIF、小说排版 |
| `scripts/pixiv_skill/targets.py` | 识别链接和 ID |
| `scripts/pixiv_skill/config.py` | 凭证和下载目录 |
| `scripts/pixiv_skill/login.py` | 打开临时浏览器窗口登录并读取 Cookie（只用标准库） |
| `scripts/pixiv_skill/cli.py` | 命令行参数和输出 |
| `dsh/index.js` | DeepSeek Harness 插件外壳，只负责把技能登记给 dsh |

## 许可证

[MIT](LICENSE)
