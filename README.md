# NP / LXP 收割素材看板

复刻「Facerinna 收割广告看板」的 UI 与数据分析逻辑，数据源改为 **NP / LXP 两个品牌在 DMS 的 IG 投放数据**（印尼 ID + 马来 MY）。

提供两种形态：

| 形态 | 地址 | 说明 |
| --- | --- | --- |
| **实时版（Cloud Run）** | https://np-lxp-harvest-dashboard-1002667285186.asia-southeast1.run.app | 自带后端，页面右上角「刷新数据」按钮可实时向 DMS 拉取最新数据 |
| 静态版（GitHub Pages） | https://hujinweixtc-rgb.github.io/np-lxp-harvest-dashboard/ | 纯静态快照，只读 |

## 功能

- **素材快照**：素材明细与 DMS 素材页直接显示素材封面（视频显示 OSS 抽帧 + ▶ 角标，点击打开原素材）。
  DMS/OSS 域名有 Referer 防盗链，图片统一走 `/media-proxy` 代理（live 同源自建；static 回退 np-post-dashboard 代理服务）。


- **数据概览**：花费 / GMV / ROI / 曝光 / 点击 / 订单 / CTR / CVR / CPA 等 KPI，支持环比对比（上一周期 / 上月 / 自定义区间）
- **每日趋势**：花费、订单、ROI 三条曲线，支持图例点击开关
- **品牌 × 市场大盘**：NP / LXP × 印尼 / 马来 的花费、GMV、ROI、CTR、客单价、CPA 汇总
- **图文 vs 视频**：素材类型分布
- **产品排序**：按花费 / ROI / 单量 / CTR / GMV / CVR 排序
- **标签分析**：采用 DMS 官方一二三级标签字典（`refresh_labels.py` 拉 `kol/material/label/listByLevelAndParentId`，含 `category` 与 `parentId`），素材标签按 id 取官方标准名（Tab / 多空格排版归一），缺失层级沿 `parentId` 自动回溯补全。一级 → 二级 → 三级三层的花费、订单、ROI 分布，以及树状图与层级汇总表（达标线按收割三大类 awa / consi / conv 分档，仅该分档字段参与判定）
- **素材明细**：逐素材的 Ad name、国家、产品、类型、标签、花费、曝光、链接点击、订单、GMV、ROI、CPM、CTR、CVR、CPA
- **DMS 素材库**：包含封面预览、视频快照、下载链接（直连 OSS）
- **导出**：一键导出当前视图的所有表格为 Excel / CSV，支持「分享链接」（筛选条件写入 URL）

## 标签体系说明

DMS 里素材标签分两套体系（`category` 字段区分）：

| category | 含义 | 规模（每品牌） | 常见标签 |
|---|---|---|---|
| `design_igad` | 素材内容标签 | L1 326 / L2 1985 / L3 445 | 功效 Function、BA、产品对比集合、多品、痛点、前后对比、场景、种草Consi、AWA |
| `test_direction` | 测试方向标签 | L1 217 / L2 121 / L3 79 | Awareness、Consideration、Conversion、GIRL MATH、直播间切片、PUGC |

看板的「DMS 一级 / 二级 / 三级标签」列与树状图即官方标签（未打标的素材归入「未标注」组，排在最后）。
收割三大类（awa / consi / conv）是从一级标签名归一出来的辅助口径，只用于达标线判定，不再作为树根。

> 注：NP-ID 约 42%、LXP-MY 约 50% 的素材在 DMS 里本身就没打标签（素材库列表、素材分析页、单素材回捞、广告名四个途径交叉验证一致），这部分无法通过接口补齐。

## 筛选维度

品牌、国家、素材来源（设计素材 SC / 剪辑素材 JJ）、产品、一级标签、二级标签、素材类型、素材创建时间、关键词搜索、日期区间 + 环比。

## 实时刷新（Cloud Run 版）

页面右上角徽章显示运行形态：`live` = 已连后端，`static` = 静态托管（此时不显示刷新按钮，行为与原来完全一致）。

- **单击「刷新数据」**：快速刷新（约 2–3 分钟）——重拉大盘聚合 + 素材投放窗口（`advertisedPage`，含趋势/明细回补）+ 重新组装看板数据。
- **Shift + 单击**：完整刷新（约 6–8 分钟）——额外重拉整张广告表并识别新增素材、重刷全部近期素材的趋势明细。

刷新在服务端后台线程执行，页面轮询进度并实时显示阶段；完成后自动重新加载数据，**当前筛选条件保持不变**。

补充说明：

- DMS 当天花费**次日结算**，所以当天数字偏小属正常；刷新能拿到当天未结算的实时投放。
- 刷新结果会备份到 GCS，实例回收后冷启动仍能取到最新数据（而不是退回镜像快照）。
- 同一时刻只允许一个刷新任务，重复点击会提示「已有刷新任务在进行中」。

### 每天自动刷新

`.github/workflows/daily-refresh.yml` 每天早上 **8:30（北京时间）** 通过 GitHub Actions 调用
`POST /api/refresh?quick=1`，并每 30 秒轮询状态直到完成（兼作实例保活，避免刷新途中被回收）。
所以早上打开看板即是当天最新数据，无需手动点。

- 手动跑一次：仓库 Actions 页 → `daily-refresh` → Run workflow（可选 `quick` / `full`）
- 之所以用 Actions 而非 Cloud Scheduler：当前 GCP 账号虽有 `run.admin` / `secretmanager.admin`，
  但没有 `cloudscheduler.jobs.create` 权限。

## 数据来源与口径

数据来自 DMS `igad` 模块（`/api/admin-api/igad/...`）：

| 接口 | 用途 |
| --- | --- |
| `igad/advertisement/allPage` | 素材库（按国家隔离，是本看板的行集合来源） |
| `igad/advertisement/advertisedPage` | **素材分析素材页**：素材在窗口内的精确 花费 / 曝光 / 点击 / 链接点击 / 订单（按月分桶抓取，是窗口口径的权威来源） |
| `igad/advertisement/getAdvertisementDetials` | 单素材区间明细（曝光 / 点击 / 订单总量的摊分基数） |
| `igad/ads/page/all` | 广告投放明细，用于补充 Ad name / Campaign / 投放账号 |
| `igad/advertisement/getAdvertisementTrendByDate` | 单素材逐日 花费 / GMV（趋势曲线的数据底座） |
| `igad/stat/board/*`、`igad/ads/breakdown/*`、`igad/ads/product/board/selectAdDateBoardData` | 品牌 × 市场大盘（逐日 / 产品 / 素材类型 / 策划 / 人群维度） |

口径说明：

- `igad/advertisement/allPage` **按 `fm-country` 隔离**，因此 NP-ID 与 NP-MY 素材库不同；`igad/ads/page/all` **不按国家隔离**（跨市场全量池），仅作素材元信息补充；
- `dataFromType`：`2` = 设计素材（SC，DMS 页面「购物 GF」媒介），`1` = 剪辑素材（JJ）；
- **每日指标摊分**：趋势接口只给逐日 花费 / GMV，曝光 / 点击 / 订单来自区间明细总量，按当日花费占比摊到每一天；再用 `advertisedPage` 的**月度桶精确总量**校准桶内各天（最大余数法取整，保证窗口求和精确），桶外天数用「终身总量 − 各桶总量」的残差重摊，避免双重计数。这样任何与月界对齐的区间（如 10-01 ~ 10-14）都能与 DMS 素材页精确对上；
- 币种为 **USD**；
- 达标线（用于「成功率」）：ID `ROI≥5.6 / CTR≥0.64%`，MY `ROI≥5.2 / CTR≥0.90%`。

## 目录结构

```
index.html                 看板单文件（原生 JS + Canvas，无框架）
data/                      看板数据快照（镜像内置 + 本地输出）
raw/                       DMS 原始缓存（~550MB，已 gitignore）
raw.tar.gz                 raw/ 的精简压缩包（~42MB，部署时生成，已 gitignore）
Dockerfile                 Cloud Run 镜像（python:3.13-slim + TZ=Asia/Shanghai）
deploy.sh                  打包缓存 + 部署到 Cloud Run
.gcloudignore              Cloud Run 构建上下文过滤（排除 raw/、config/）
server/app.py              Cloud Run 服务：静态托管 + 刷新 API + GCS 持久化
scripts/dms_api.py         DMS API 客户端（四组合配置；token 从环境变量读取）
scripts/fetch_dms.py       首次全量抓取（带本地缓存）
scripts/refresh_board.py   大盘聚合增量刷新
scripts/refresh_adv.py     素材投放窗口（advertisedPage）按月分桶抓取 + 趋势明细回补
scripts/refresh_ads.py     广告表重拉 + 新增素材趋势/明细补齐
scripts/refresh_recent.py  近期活跃素材的趋势/明细重刷
scripts/build_data.py      原始数据 -> 看板 JSON
scripts/vision_theme.py    视觉模型提取素材快照主题词（智谱 GLM-4.6V-Flash 免费档）
scripts/pack_raw.py        raw/ -> raw.tar.gz（只打包管线实际读取的文件）
.github/workflows/         GitHub Actions（daily-refresh：每天 8:30 自动刷新）
scripts/setup_secrets.sh   把 token 写入 Secret Manager 并授权
```

## 图片主题词（视觉模型）

素材卡片下方与大图弹窗左下角的主题词，由 `scripts/vision_theme.py` 读取快照生成，
产物是 `data/image_themes.json`（按素材 key 索引）。模型用智谱 **GLM-4V-Flash**（`glm-4.6v-flash` 白天常 429，已切更稳的旧版），
官方免费档，不计费；补译用文本模型 `glm-4-flash`，同样免费。

```bash
export ZHIPU_API_KEY=你的key                       # bigmodel.cn → API Keys
python scripts/vision_theme.py --limit 300         # 按花费降序取前 300（覆盖 69% 花费）
python scripts/vision_theme.py --all               # 全量 4220 张
python scripts/vision_theme.py --brand NP --country ID --limit 100
python scripts/vision_theme.py --dry-run --limit 20  # 不调模型，仅用素材名规则兜底
```

- 已成功的素材默认跳过，可反复执行做增量；`--force` 强制重跑。
- 图片下载走阿里云 OSS 直连，视频用 `x-oss-process=video/snapshot` 取帧。
- 送模型前统一压到长边 1024 / JPEG q82（单张约 1150 输入 + 190 输出 tokens）。
- **防欠费护栏**：脚本只接受 `-flash` / `-flashx` / `-free` 结尾的模型名，服务端返回
  非免费档模型会立即中止。
- 图上文案会同时输出中文翻译（`onimageZh`），历史数据可用
  `python scripts/vision_theme.py --translate-onimage` 补译（免费文本模型 `glm-4-flash`）。

### 分析底稿（给其他 AI / BI 用）

`scripts/vision_theme.py` 跑完会自动调用 `scripts/export_themes.py`，把结果和素材
元数据、DMS 标签、投放指标拼成可直接消费的数据集，输出到 `data/theme_dataset/`：

| 文件 | 说明 |
|---|---|
| `themes.jsonl` | 一行一个素材（机器读取），含 `sellZh/sellSrc`、`copyZh/copySrc`、`onimage/onimageZh`、DMS 标签、花费/GMV/订单/ROI |
| `themes.csv` | 同上，UTF-8 BOM，Excel 直接打开 |
| `sell_keywords.csv` | 卖点关键词汇总（素材数 / 花费 / 订单 / GMV / ROI） |
| `copy_keywords.csv` | 文案主题关键词汇总 |
| `README.md` | 字段级数据字典 |

单独重跑导出：`python scripts/export_themes.py`（无分析数据时会安全跳过）。

## 凭据

DMS token **不写入源码**（本仓库公开，曾因此泄露过一次）。按优先级读取：

1. 环境变量 `DMS_TOKEN_NP` / `DMS_TOKEN_LXP`（Cloud Run 从 Secret Manager 注入）
2. 本地文件 `config/dms_tokens.json`（已 gitignore），格式 `{"NP": "...", "LXP": "..."}`

> ⚠️ 若 token 曾出现在提交历史中，请在 DMS 后台重新生成，然后执行
> `bash scripts/setup_secrets.sh` 更新 Secret Manager（无需重新部署服务）。

## 本地复现

```bash
# 0. 配置凭据
mkdir -p config && echo '{"NP":"<token>","LXP":"<token>"}' > config/dms_tokens.json

# 1. 首次全量抓取（结果缓存在 raw/，已 gitignore）
python scripts/fetch_dms.py            # 全部四个组合
python scripts/fetch_dms.py NP-ID      # 只抓某一个组合

# 2. 生成看板数据
python scripts/build_data.py

# 3. 本地预览
python -m http.server 8790
# 打开 http://127.0.0.1:8790/index.html

# 4. 增量刷新（等价于页面上的「刷新数据」）
python scripts/refresh_board.py && python scripts/refresh_adv.py && python scripts/build_data.py
```

## 部署 / 更新

```bash
# Cloud Run 实时版（每次改代码后执行）
bash deploy.sh

# 静态版：把新的 data/ 与 index.html 推到 GitHub Pages
git push origin main
```
