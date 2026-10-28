# 获取 Pixiv Cookie

不登录也能搜索和下载全年龄作品。想看 R-18 作品、R-18 排行榜，或者只有登录才能看的作品，就要把你自己账号的登录凭证（Cookie）交给脚本。

其实只需要**一个**值：`PHPSESSID`。它长这样：

```
12345678_AbCdEfGhIjKlMnOpQrStUvWxYz012345
```

下划线前面的数字是你的用户 ID，后面是一串随机字母。如果你拿到的值里**没有**“数字加下划线”的开头，说明你复制到的是没登录时的 Cookie，没用。

> **安全提醒**：这个值等于你的登录状态，谁拿到它，谁就能用你的账号浏览、收藏、关注。
> - 不要发给任何人，也不要贴进 AI 聊天框。让 AI 帮你用这个技能时，自己在终端里跑下面的命令。
> - 用完想作废，到 Pixiv 网页右上角退出登录，这个值就失效了。
> - 删除脚本保存的副本：`python scripts/pixiv.py cookie --clear`

## 方法一：自动获取（推荐）

电脑上装了 Chrome、Edge、Brave 或 Chromium 中的任意一个就行。

```bash
python scripts/pixiv.py cookie --login
```

1. 脚本会打开一个**全新的**浏览器窗口，里面是 Pixiv 登录页；
2. 你在这个窗口里正常登录（账号密码、谷歌登录、扫码都可以，遇到人机验证照常点）；
3. 登录成功后窗口会自动关闭，命令行显示「登录成功，Cookie 已保存」。

它是怎么做到的：

- 这个窗口用的是一个临时的空白配置，**不会读取**你平时浏览器里的任何数据（书签、密码、其他网站的登录状态都碰不到），用完整个临时配置会被删掉。
- 账号密码是你自己在 Pixiv 官网输入的，脚本看不到，也不经手。
- 脚本只读取 pixiv.net 下名为 `PHPSESSID` 的那一个 Cookie，确认是登录后的值就保存下来。

常见问题：

- **提示找不到浏览器**：用 `--browser` 指定程序路径，比如
  `--browser "C:\Program Files\Google\Chrome\Application\chrome.exe"`，
  或者设置环境变量 `PIXIV_BROWSER`。也可以改用下面的手动方法。
- **窗口一打开就关掉 / 连不上**：换一个浏览器试试（比如平时用 Chrome，就用 `--browser msedge`）。
- **登录太慢超时了**：默认等 5 分钟，可以加 `--timeout 600` 等 10 分钟。
- **没有图形界面的服务器**：自动方法用不了，请在自己电脑上拿到值，再用方法二保存到服务器。

## 方法二：手动复制

### 电脑浏览器（Chrome / Edge）

1. 打开 https://www.pixiv.net 并登录；
2. 按 `F12`（Mac 上按 `Cmd + Option + I`）打开开发者工具；
3. 顶部选「应用」（Application）标签，看不到就点 `»` 找；
4. 左侧展开「存储」→「Cookie」→ 点 `https://www.pixiv.net`；
5. 在右边的列表里找到名称为 `PHPSESSID` 的那一行，双击「值」那一格，全选复制。

### 电脑浏览器（Firefox）

1. 打开 https://www.pixiv.net 并登录；
2. 按 `F12`，选「存储」标签；
3. 左侧「Cookie」→ `https://www.pixiv.net`，找到 `PHPSESSID`，复制它的值。

### 只有手机

手机浏览器一般看不到 Cookie。可以：

- 安卓用 Kiwi 浏览器或装了开发者工具扩展的浏览器，按上面电脑的步骤操作；
- 或者借一台电脑登录一次，拿到值后发到自己手机上（注意别发到群里）。

### 保存到脚本里

复制好之后运行：

```bash
python scripts/pixiv.py cookie --set -
```

然后把值粘贴进去、回车。这样值不会留在命令历史里。直接粘 `PHPSESSID=...` 这一整段，或者整条 Cookie 请求头，也都能识别。

不想存文件的话，也可以设置环境变量（优先级比保存的文件高）：

```bash
# macOS / Linux
export PIXIV_PHPSESSID='12345678_AbCdEf...'
# Windows PowerShell
$env:PIXIV_PHPSESSID = '12345678_AbCdEf...'
```

## 检查是否生效

```bash
python scripts/pixiv.py cookie
```

显示「Cookie 有效」就成功了。显示「无效或已过期」就按上面的方法重新获取一次。Cookie 一般能用很久，但在网页上退出登录、改密码，或长时间不用之后会失效。

## 还是看不到 R-18？

Cookie 有效，但 R-18 作品搜不到、下载报「没有权限」，是因为 Pixiv 账号本身默认不显示 R-18 内容：

1. 打开 https://www.pixiv.net/settings/viewing
2. 把「浏览限制」里的 R-18（以及需要的话 R-18G）改成「显示」；
3. 保存后不用重新获取 Cookie，直接再试即可。

Pixiv 要求开启 R-18 显示的账号已满 18 岁。
