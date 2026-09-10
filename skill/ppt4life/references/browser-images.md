# 用真实浏览器搜索并下载配图（BrowserSkill 集成）

> 目标：当 PPT 需要**真实素材**（实景照片、产品图、行业配图）时，用 `bsk` 驱动用户**已登录的真实浏览器**去搜索、筛选并下载图片，落地到本地再嵌入 PPT。
> 本文件是 [Tencent/BrowserSkill](https://github.com/Tencent/BrowserSkill)（MIT）在 ppt4life 中的集成用法。

## 0. 前置条件（首次使用需一次性配置）

1. **安装 `bsk` CLI**
   - Windows（PowerShell）：`irm https://raw.githubusercontent.com/Tencent/BrowserSkill/main/install.ps1 | iex`
   - macOS / Linux：`curl -fsSL https://raw.githubusercontent.com/Tencent/BrowserSkill/main/install.sh | sh`
   - 安装到 `~/.local/bin`，验证：`bsk --version`
2. **安装浏览器扩展**：从 Chrome Web Store / Edge Add-ons 安装 BrowserSkill 扩展（Chrome 或 Edge）。
3. 检查连接：`bsk doctor`；查看已连接的浏览器：`bsk browsers`。
4. 若 `bsk` 不可用（未安装/未连接），**不要卡住**——回退到 AI 生图（`ImageGen`）或矢量自绘，并告知用户。

## 1. 会话生命周期（每个浏览器任务必须成对出现）

```text
bsk session start [--no-focus]     # 记下打印的 4 位 session id；--no-focus 尽量不打扰用户
bsk ... --session <id>             # 所有会话内命令都要带 --session
bsk session stop <id>              # 成功和失败路径都要执行，归还借用的标签页
```
不要依赖空闲超时清理；任务达成就停止会话。

## 2. 观察—操作—观察（默认循环）

```text
bsk navigate <url> --session <id>
bsk observe --session <id>
# 需要时：click / hover / scroll-to / fill / press ...
bsk observe --session <id>          # 导航或页面明显变化后重新观察
```
读取页面的手段按需升级：`observe`（语义）→ `observe --probe-hover`（疑似 hover 菜单）→ `snapshot`（无障碍树）→ `get-html`（精确标记/隐藏元数据）→ `screenshot`（布局/样式/视觉证据）。

## 3. 图片搜索与下载流程（推荐：免版权图库，最合规）

以 Unsplash / Pexels / Pixabay 等免版权图库为首选：

```bash
# 1) 开会话
bsk session start --no-focus                 # 得到如 abcd

# 2) 打开图库搜索页（关键词用英文命中率更高；空格转 %20）
bsk navigate "https://unsplash.com/s/photos/<keyword>" --session abcd
bsk observe --session abcd

# 3) 找到目标图片（列表页点进详情页，或直接定位图片元素 ref）
bsk click @e12 --session abcd
bsk observe --session abcd

# 4) 精确拿到图片直链（get-html 提取 <img> 的 src，或页面内的原图下载链接）
bsk get-html --session abcd

# 5) 下载图片到工作区（对可下载元素/链接）
bsk download @e5 --out "<workspace>/assets/img/hero-bg.jpg" --session abcd

# 6) 结束会话
bsk session stop abcd
```

要点：
- `bsk download <ref> --out <path>` 默认**拒绝覆盖**，需要替换时加 `--overwrite`。
- 若页面没有可直接下载的元素，用第 4 步拿到的**图片直链**，再用 `curl` 下载到 `assets/img/`。
- 图片直链常带尺寸参数，尽量取“原图/大图”地址以满足 ≥1920px。

## 4. 用搜索引擎图片（素材更广，但注意版权）

```bash
bsk navigate "https://www.bing.com/images/search?q=<关键词>" --session abcd
bsk observe --session abcd
bsk get-html --session abcd        # 从标记中提取 img 的 src / murl
# 再对目标图下载（download 或 curl 直链）
```
百度图片同理（`https://image.baidu.com/search/index?tn=baiduimage&word=<关键词>`）。

> ⚠️ **版权**：搜索引擎图片可能受版权保护，**仅供内部参考/临时使用需谨慎**；对外正式材料优先用免版权图库或公司自有素材，并标注来源。

## 5. 借用的标签页与人工介入

- 只操作 **Agent Window**（隔离窗口，复用登录态）；需操作用户自己的标签页时：`bsk tab list --scope user --session <id>` → `bsk tab borrow <tab-id>` → 用完立即 `bsk tab return <tab-id>`。
- 遇到登录/验证码/OTP/确认弹窗：`bsk request-help`（给出精确提示），等用户完成后重新 `observe` 再继续。
- **绝不**提取凭证、Cookie、Token 等敏感信息；**绝不**在银行/SSO/密码管理等页面操作。

## 6. 与配图策略的衔接

- 下载/生成的所有图片统一存 `assets/img/`，按语义命名，并记录**来源**（便于标注出处）。
- 下载后做**清晰度与比例检查**（宽 ≥1920px、不变形），不合格就改用 AI 生图或矢量自绘。
- 缺真实素材的**概念/氛围图**不要硬找，直接用 `ImageGen`（见 `visuals.md` 第 4 节）。

## 7. 失败与回退

| 情况 | 处理 |
|---|---|
| `bsk` 未安装/未连接 | 回退：AI 生图（ImageGen）或矢量自绘；并提示用户可安装 BrowserSkill 启用真实素材 |
| 页面无下载元素 | 用 `get-html` 取直链 → `curl` 下载 |
| 需要登录/验证码 | `bsk request-help` 请用户接管，完成后重新 `observe` |
| 两次尝试无进展 | 停止硬试，报告阻塞点并给出替代方案 |
