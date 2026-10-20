# 素材卖点 / 文案关键词 数据集（AI 分析底稿）

由 `scripts/export_themes.py` 从 `data/image_themes.json` 导出，源数据为视觉模型
（智谱 `glm-4v-flash`，免费档）对 Shopee 广告素材封面快照的读取结果。

## 文件

| 文件 | 说明 |
|---|---|
| `themes.jsonl` | 一行一个素材，机器读取用（JSON Lines，UTF-8） |
| `themes.csv` | 同上，UTF-8 BOM，Excel 可直接打开 |
| `sell_keywords.csv` | 卖点关键词汇总（按花费降序） |
| `copy_keywords.csv` | 文案主题关键词汇总（按花费降序） |

## themes 字段

| 字段 | 含义 |
|---|---|
| `materialCode` | DMS 素材编号（唯一键，可与 `dms_materials.json` / `materials.json` 关联） |
| `brand` / `country` / `product` | 品牌（NP / LXP）、市场（ID / MY）、产品 |
| `materialName` / `adName` | 素材名称、广告名称（原始） |
| `dmsTag1..dmsTag3` | DMS 官方一/二/三级标签 |
| `isVideo` | 是否视频素材（Y/N），主题词来自视频封面帧 |
| `spend` / `orders` / `gmv` / `roi` | 该素材全周期投放指标（USD） |
| `lang` | 画面文字语言：id 印尼语 / ms 马来语 / en 英语 / none |
| `scene` | 画面场景（中文，≤10 字） |
| `onimage` | 画面上出现的文案原文（源语言，最多 2 条，`|` 分隔） |
| `onimageZh` | 上述文案的简体中文翻译 |
| `sellZh` / `sellSrc` | 卖点标签，中文 / 源语言，多条用 ` | ` 分隔 |
| `copyZh` / `copySrc` | 文案主题关键词，中文 / 源语言，同上 |
| `model` / `analyzedAt` | 生成该行的模型与分析时间 |

## keyword 汇总字段

`keyword`、`materials`（涉及素材数）、`spend`（花费合计）、`orders`、`gmv`、
`roi`（GMV / 花费）。同一素材内重复关键词只计一次。

## 注意

- 主题词由视觉模型读图生成，**仅供创意分析参考**，不是 DMS 官方口径。
- 未分析的素材不在本数据集中；覆盖率见 `data/image_themes.json` 的条目数。
- 指标是素材全周期值；按日期窗口的口径请用 `data/materials.json` 的逐日 `days`。
