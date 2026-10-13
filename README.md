# NP / LXP 收割素材看板

复刻「Facerinna 收割广告看板」的 UI 与数据分析逻辑，数据源改为 **NP / LXP 两个品牌在 DMS 的 IG 投放数据**（印尼 ID + 马来 MY）。纯静态站点，无后端依赖，可直接托管在 GitHub Pages。

## 在线地址

```
https://hujinweixtc-rgb.github.io/np-lxp-harvest-dashboard/
```

## 功能

- **数据概览**：花费 / GMV / ROI / 曝光 / 点击 / 订单 / CTR / CVR / CPA 等 KPI，支持环比对比（上一周期 / 上月 / 自定义区间）
- **每日趋势**：花费、订单、ROI 三条曲线，支持图例点击开关
- **品牌 × 市场大盘**：NP / LXP × 印尼 / 马来 的花费、GMV、ROI、CTR、客单价、CPA 汇总
- **图文 vs 视频**：素材类型分布
- **产品排序**：按花费 / ROI / 单量 / CTR / GMV / CVR 排序
- **收割标签分析**：一级（大方向）/ 二级（主题）/ 三级（测试点）三层的花费、订单、ROI 分布，以及树状图与层级汇总表（含达标素材数与成功率）
- **素材明细**：逐素材的 Ad name、国家、产品、类型、标签、花费、曝光、链接点击、订单、GMV、ROI、CPM、CTR、CVR、CPA
- **DMS 素材库**：包含封面预览、视频快照、下载链接（直连 OSS）
- **导出**：一键导出当前视图的所有表格为 Excel / CSV，支持「分享链接」（筛选条件写入 URL）

## 筛选维度

品牌、国家、产品、收割一级标签、收割二级标签、素材类型、素材创建时间、关键词搜索、日期区间 + 环比。

## 数据来源与口径

数据来自 DMS `igad` 模块（`/api/admin-api/igad/...`）：

| 接口 | 用途 |
| --- | --- |
| `igad/advertisement/allPage` | 素材库（按国家隔离，是本看板的行集合来源） |
| `igad/ads/page/all` | 广告投放明细，用于补充 Ad name / Campaign / 投放账号 |
| `igad/advertisement/getAdvertisementTrendByDate` | 单素材逐日 花费 / GMV（趋势曲线的数据底座） |
| `igad/ads/product/board/selectAdDateBoardData` | 品牌 × 市场大盘逐日数据 |
| `igad/stat/board/product`、`igad/stat/board/materialType`、`igad/stat/board/planPic` | 产品 / 素材类型 / 策划维度大盘 |

口径说明：

- `igad/advertisement/allPage` **按 `fm-country` 隔离**，因此 NP-ID（3530 条）与 NP-MY（744 条）素材库不同；
- `igad/ads/page/all` **不按国家隔离**（返回跨 TH / US / MY 等的全量池），因此仅作为素材元信息的补充来源，并优先取 `adAccountName` 国家标记匹配的投放记录；
- 币种为 **USD**（DMS 侧未标注币种，按美金口径展示）；
- 达标线（用于「成功率」）：ID `ROI≥5.6 / CTR≥0.64%`，MY `ROI≥5.2 / CTR≥0.90%`。

## 目录结构

```
index.html                 看板单文件（原生 JS + Canvas，无框架）
data/materials.json        主数据载荷（逐素材 + 逐日 spend/GMV）
data/dms_materials.json    DMS 素材库（预览 / 下载链接）
data/board.json            品牌 × 市场大盘数据
scripts/dms_api.py         DMS API 客户端（四组合配置）
scripts/fetch_dms.py       原始数据抓取（带本地缓存 raw/）
scripts/build_data.py      原始数据 -> 看板 JSON
```

## 本地复现

```bash
# 1. 抓取原始数据（结果缓存在 raw/，已 gitignore）
python scripts/fetch_dms.py            # 全部四个组合
python scripts/fetch_dms.py NP-ID      # 只抓某一个组合

# 2. 生成看板数据
python scripts/build_data.py

# 3. 本地预览
python -m http.server 8790
# 打开 http://127.0.0.1:8790/index.html
```

## 部署

仓库为纯静态站点，推送到 `main` 分支后由 GitHub Pages 直接托管（已含 `.nojekyll`）。
