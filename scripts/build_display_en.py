#!/usr/bin/env python
"""构建英文模式下的数据值显示映射 data/display_en.json。

来源：
1) data/product_en_from_xlsx.json —— 用户提供的《投放产品名称管理.xlsx》内部简称/英文简称/投放产品名称；
2) data/theme_en_cache.json —— 既有视觉标签中文短语译文；
3) 本文件内的补充词典 —— 覆盖看板里 Excel 未收录的产品与 DMS 一/二/三级标签。

输出只影响展示层，不改写原始数据、不参与筛选逻辑。
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("DASH_DATA_DIR") or (ROOT / "data"))
OUT = DATA / "display_en.json"

# Excel 未覆盖的看板产品名（其余优先用 Excel 的英文简称）
PRODUCT_EXTRA = {
    "10%烟酰胺美白精华": "10% Niacinamide Brightening Serum",
    "2pcs 多效+竹炭洁面": "2pcs Multi-Effect + Charcoal Cleanser",
    "2pcs 祛痘+深度清洁洁面": "2pcs Acne + Deep Cleansing Cleanser",
    "2pcs沐浴露+止汗滚珠": "2pcs Body Wash + Deodorant Roll-On",
    "2pcs洁面-美白+深层清洁": "2pcs Cleanser - Brightening + Deep Clean",
    "2pcs洁面-美白+磨皮": "2pcs Cleanser - Brightening + Exfoliating",
    "2pcs防晒喷雾+洁颜皂": "2pcs Sunscreen Spray + Cleansing Bar",
    "377两件套": "377 2pcs Set",
    "377精华": "377 Serum",
    "377面霜": "377 Moisturizer",
    "3PCS洁面": "3PCS Cleanser Set",
    "3pcs 洁面+沐浴露+发型": "3pcs Cleanser + Body Wash + Hair Style",
    "3pcs洁面": "3pcs Cleanser Set",
    "4pcs男士套盒": "4pcs Men's Set",
    "4件套-美白+视黄醇": "4pcs Set - Brightening + Retinol",
    "5PCS-PDRN套组": "5PCS PDRN Set",
    "5X面霜": "5X Moisturizer",
    "5X面霜大样": "5X Moisturizer Sample",
    "6pcs男士理容套盒": "6pcs Men's Grooming Set",
    "7pcs男士套盒": "7pcs Men's Set",
    "B5啫喱面霜软管": "B5 Gel Cream Tube",
    "B5积雪草啫喱面霜软管30ml": "B5 Centella Gel Cream Tube 30ml",
    "BUY2GET3-2pcs日夜洁面+唇膏": "BUY2GET3 - 2pcs Day/Night Cleanser + Lip Balm",
    "BUY2GET3-2pcs日夜洁面+止汗滚珠": "BUY2GET3 - 2pcs Day/Night Cleanser + Deodorant",
    "LOW PH洁面": "Low pH Cleanser",
    "PDRN次抛精华": "PDRN Ampoule Serum",
    "PDRN次抛精华面霜2件套": "PDRN Ampoule Serum & Moisturizer 2pcs Set",
    "PDRN精华": "PDRN Serum",
    "PDRN美白啫喱片": "PDRN Brightening Gel Pads",
    "PDRN面膜": "PDRN Sheet Mask",
    "PDRN面霜": "PDRN Moisturizer",
    "combo:PDRN精华+PDRN面霜": "Combo: PDRN Serum + PDRN Moisturizer",
    "combo:磨皮棉片+美白面膜": "Combo: Exfoliating Pads + Brightening Mask",
    "gel洗面奶": "Gel Cleanser",
    "mini牛仔蓝色气垫": "Mini Denim Blue Cushion",
    "pdrn泵头洁面": "PDRN Pump Cleanser",
    "修复面霜": "Repair Moisturizer",
    "半哑精华绿色气垫": "Semi-Matte Serum Green Cushion",
    "哑光发泥": "Matte Hair Clay",
    "哑光气垫": "Matte Cushion",
    "哑光防晒": "Matte Sunscreen",
    "多效洁面": "Multi-Effect Cleanser",
    "多效洁面啫喱": "Multi-Effect Cleansing Gel",
    "头发造型套组": "Hair Styling Set",
    "定型霜": "Styling Cream",
    "底妆5件套": "5pcs Base Makeup Set",
    "弱酸美白洁面啫喱": "Low Acid Brightening Cleansing Gel",
    "强效去屑洗发水": "Intensive Anti-Dandruff Shampoo",
    "早晚洁面COMBO": "Day & Night Cleanser Combo",
    "有色润唇膏": "Tinted Lip Balm",
    "有色防晒": "Tinted Sunscreen",
    "止汗滚珠": "Deodorant Roll-On",
    "水光气垫": "Glow Cushion",
    "水光气垫-链子版": "Glow Cushion (Chain Version)",
    "水油喷雾": "Water-Oil Spray",
    "沐浴露合集": "All Body Washes",
    "洁面合集": "All Cleansers",
    "深层清洁洗面奶": "Deep Cleansing Face Wash",
    "温和洁面": "Gentle Cleanser",
    "滚珠合集": "All Roll-Ons",
    "烟酰胺传明酸素颜霜": "Niacinamide Tranexamic Tone-Up Cream",
    "烟酰胺美白面霜": "Niacinamide Brightening Moisturizer",
    "独立站": "Independent Site",
    "独立站5件套-PDRN面霜+精华+喷雾+玫瑰奶油洁面+有色防晒": "DTC 5pcs Set - PDRN Moisturizer + Serum + Spray + Rose Cream Cleanser + Tinted Sunscreen",
    "玫瑰奶油洁面": "Rose Cream Cleanser",
    "男士定型蓬松粉 (撒瓶装)": "Men's Volumizing Powder (Shaker)",
    "男士润唇膏": "Men's Lip Balm",
    "磨砂洁面": "Scrub Cleanser",
    "祛痘洁面": "Acne Cleanser",
    "竹炭洁面": "Charcoal Cleanser",
    "粉底棒": "Foundation Stick",
    "粉色PDRN水油喷雾": "Pink PDRN Water-Oil Spray",
    "素颜霜": "Tone-Up Cream",
    "绿色英雄沐浴露": "Green Hero Body Wash",
    "缎光定妆喷雾": "Satin Setting Spray",
    "美白洁面乳": "Brightening Cleanser",
    "美白爽肤水": "Brightening Toner",
    "美白祛痘COMBO": "Brightening & Acne Combo",
    "美白组合-面霜+精华": "Brightening Duo - Moisturizer + Serum",
    "美白防晒买2得3pcs": "Brightening Sunscreen Buy 2 Get 3pcs",
    "美白面膜": "Brightening Sheet Mask",
    "胶水妆前啫喱": "Glue-Like Makeup Base Gel",
    "蓝色气垫": "Blue Cushion",
    "蓝色睿蓝沐浴露": "Blue Rui Lan Body Wash",
    "视黄醇面膜": "Retinol Sheet Mask",
    "运动止汗滚珠": "Sport Deodorant Roll-On",
    "金色气垫": "Gold Cushion",
    "金色气垫替换装": "Gold Cushion Refill",
    "防晒4件套": "4pcs Sunscreen Set",
    "防晒喷雾": "Sunscreen Spray",
    "顺滑发蜡": "Smooth Hair Wax",
    "黄色信仰沐浴露": "Yellow Faith Body Wash",
    "黑色美白洁面皂": "Black Brightening Cleansing Bar",
}

TAG_EXTRA = {
    "0油光": "Zero Oil Shine",
    "0添加1": "Zero Additives 1",
    "0添加2": "Zero Additives 2",
    "14天焕肤": "14-Day Skin Renewal",
    "1功效": "Benefit 1",
    "1质地": "Texture 1",
    "3种": "3 Types",
    "6合一": "6-in-1",
    "7天功效": "7-Day Benefits",
    "不假白不发灰": "No White Cast, No Grey",
    "世界杯": "World Cup",
    "产品实拍": "Real Product Shot",
    "使用教学": "How to Use",
    "使用教程": "Tutorial",
    "使用方式": "Application",
    "使用步骤": "Usage Steps",
    "使用过程": "Application Process",
    "养肤": "Skin Nourishing",
    "冰感": "Cooling Sensation",
    "凉感": "Refreshing Feel",
    "分子": "Molecules",
    "分子成分": "Molecular Ingredients",
    "分子设计": "Molecular Design",
    "前后": "Before & After",
    "功效1": "Benefit 1",
    "功效2": "Benefit 2",
    "功效妆效": "Makeup Effect",
    "功效成分": "Functional Ingredients",
    "功效成分1": "Functional Ingredients 1",
    "功效成分2": "Functional Ingredients 2",
    "功效成分3": "Functional Ingredients 3",
    "功效痛点": "Concerns & Benefits",
    "医生形象": "Doctor Image",
    "医生心智": "Doctor Endorsement",
    "医研背书": "Medical Research Backing",
    "卡粉": "Cakey Makeup",
    "卡粉斑驳": "Cakey & Patchy",
    "发型": "Hairstyle",
    "变身": "Transformation",
    "口碑": "Word of Mouth",
    "口碑1": "Word of Mouth 1",
    "口袋": "Pocket",
    "合集": "Collection",
    "合集推荐": "Collection Picks",
    "吸油纸": "Oil Blotting Paper",
    "味道": "Scent",
    "品牌图": "Brand Visual",
    "喷雾合集": "Spray Collection",
    "四宫格": "4-Grid Layout",
    "场景": "Occasion",
    "场景合集": "Occasion Collection",
    "场景感": "Scene Setting",
    "场景感1": "Scene Setting 1",
    "场景感2": "Scene Setting 2",
    "城市": "City",
    "复合功效": "Multi-Benefit",
    "多效合一1": "Multi-Effect 1",
    "多效合一实验室": "Multi-Effect Lab",
    "多效合一质地": "Multi-Effect Texture",
    "多痛点": "Multiple Concerns",
    "多维数据": "Multi-Dimensional Data",
    "大小对比": "Size Comparison",
    "大质地": "Big Texture",
    "大质地1": "Big Texture 1",
    "天气": "Weather",
    "头盔": "Helmet",
    "妆容服帖": "Long-Lasting Makeup",
    "妆效": "Makeup Effect",
    "学生党": "Student Friendly",
    "实拍": "Real Shot",
    "实拍1": "Real Shot 1",
    "实拍2": "Real Shot 2",
    "实拍产品": "Product Real Shot",
    "实拍水感": "Watery Texture Shot",
    "实拍质地1": "Texture Shot 1",
    "实验室1": "Lab 1",
    "实验室2": "Lab 2",
    "实验室风": "Lab Style",
    "对比哑光喷雾": "Matte Spray Comparison",
    "对比哑光定妆喷雾": "Matte Setting Spray Comparison",
    "对比精华": "Serum Comparison",
    "对比美白洁面": "Brightening Cleanser Comparison",
    "小红书测评": "Xiaohongshu Review",
    "干皮对比": "Dry Skin Comparison",
    "底妆合集": "Base Makeup Collection",
    "成分1": "Ingredients 1",
    "成分功效": "Ingredients & Benefits",
    "成分讲解": "Ingredient Explanation",
    "成分设计": "Ingredient Design",
    "成功男人": "Successful Men",
    "所有肌肤": "All Skin Types",
    "手持产品1": "Hand-Held Product 1",
    "手持实拍": "Hand-Held Real Shot",
    "手持测评": "Hand-Held Review",
    "手挤质地": "Hand-Pressed Texture",
    "手挤质地1": "Hand-Pressed Texture 1",
    "手挤质地2": "Hand-Pressed Texture 2",
    "手挤质地3": "Hand-Pressed Texture 3",
    "手法": "Application Technique",
    "打卡": "Check-In",
    "护发成分": "Hair Care Ingredients",
    "搭配": "Combination",
    "摩托车": "Motorcycle",
    "教学": "Tutorial",
    "数字": "Numbers",
    "数据1": "Data 1",
    "数据2": "Data 2",
    "数据支撑": "Data Support",
    "数据支撑1": "Data Support 1",
    "数据支撑2": "Data Support 2",
    "数据支撑3": "Data Support 3",
    "早晚搭配": "Day & Night Routine",
    "时间设计": "Timeline Design",
    "暗色背景": "Dark Background",
    "曝光测试": "Exposure Test",
    "机制": "Mechanism",
    "检测仪": "Testing Device",
    "气垫合集": "Cushion Collection",
    "氧化暗沉": "Oxidation & Dullness",
    "水光肌": "Glass Skin",
    "水光肌教学": "Glass Skin Tutorial",
    "水感": "Watery Feel",
    "水感实拍": "Watery Real Shot",
    "水感质地": "Watery Texture",
    "沙漠大干皮": "Very Dry Skin",
    "油痘肌": "Oily Acne Skin",
    "油痘肌素颜霜": "Oily Acne Skin Tone-Up Cream",
    "泡沫上脸": "Foam on Face",
    "洗头过程": "Hair Washing Process",
    "洗澡过程": "Shower Process",
    "流动质地": "Flowing Texture",
    "测评": "Review",
    "深度成分讲解": "In-Depth Ingredient Breakdown",
    "清洁痘肌不刺激": "Gentle on Acne Skin",
    "湿热气候": "Hot & Humid Climate",
    "炎热天气持妆": "Long-Lasting in Hot Weather",
    "烟霾天": "Hazy Day",
    "热带场景": "Tropical Scene",
    "热带气候": "Tropical Climate",
    "熬夜急救": "Late-Night Rescue",
    "爆点叠加": "Layered Hooks",
    "用法": "Usage",
    "男士": "Men",
    "男士哑光": "Men's Matte",
    "痘坑": "Acne Scars",
    "痛点": "Skin Concern",
    "痛点0氧化": "Oxidation Concern",
    "痛点2": "Skin Concern 2",
    "痛点3": "Skin Concern 3",
    "皮肤管理": "Skin Care Routine",
    "直击痛点": "Targeted Concern",
    "真人": "Real Person",
    "真实种草": "Genuine Recommendation",
    "真实种草感": "Authentic Recommendation",
    "真实评论": "Real Review",
    "真实质地": "Real Texture",
    "瞬间控油提亮": "Instant Oil Control & Brightening",
    "社媒": "Social Media",
    "社媒口碑": "Social Proof",
    "种草": "Product Recommendation",
    "种草感1": "Recommendation Vibe 1",
    "科学感": "Scientific Feel",
    "科技感": "Tech Feel",
    "科普": "Education",
    "科普教学": "Educational Tutorial",
    "竞品": "Competitor",
    "细胞": "Cells",
    "缎光妆效": "Satin Makeup Finish",
    "肤感": "Skin Feel",
    "胶水概念": "Glue Concept",
    "色号": "Shade",
    "药妆实验室": "Cosmeceutical Lab",
    "药妆心智": "Cosmeceutical Positioning",
    "药妆感": "Cosmeceutical Feel",
    "蓝粉气垫": "Blue Pink Cushion",
    "表格": "Chart",
    "评论": "Comments",
    "诱人质地": "Luxurious Texture",
    "诱人质地-": "Luxurious Texture",
    "质地1": "Texture 1",
    "质地2": "Texture 2",
    "质地3": "Texture 3",
    "质地不厚重": "Lightweight Texture",
    "质地实拍": "Texture Real Shot",
    "质地挤出": "Texture Squeeze",
    "足球风调性": "Football Theme",
    "选色号": "Shade Selection",
    "通勤干爽": "Commute Freshness",
    "销量": "Sales",
    "防晒功效": "Sunscreen Benefits",
    "防晒合集": "Sunscreen Collection",
    "高级感": "Premium Feel",
    "高级感大质地": "Premium Big Texture",
    "高级感色号": "Premium Shades",
    "高级质地": "Premium Texture",
    "黑衣头屑": "Dandruff on Black Clothes",
}

# 少量易歧义项以本词典为准，覆盖 Excel / 视觉标签缓存里的直译
OVERRIDES = {
    "产品": "Product",
    "功效": "Efficacy",
    "痛点": "Skin Concern",
    "成分": "Ingredients",
    "质地": "Texture",
    "数据": "Data",
    "数据支持": "Data Support",
    "数据支撑": "Evidence",
    "种草": "Product Recommendation",
    "口碑": "Word of Mouth",
    "价格": "Price",
    "促销": "Promotion",
    "折扣": "Discount",
    "优惠券": "Voucher",
    "达人": "KOL",
    "医生": "Doctor",
    "实验室": "Lab",
    "高级感": "Premium Feel",
    "前后对比": "Before & After",
    "肤质": "Skin Type",
    "肤感": "Skin Feel",
    "色号": "Shade",
    "场景": "Occasion",
    "使用方法": "How to Use",
    "使用步骤": "Usage Steps",
    "早晚搭配": "Day & Night Routine",
    "新品上市": "New Launch",
    "未标注": "Unlabeled",
    "设计素材": "Design Material",
    "剪辑系统": "Editing System",
    "可下载": "Downloadable",
    "待DMS导出": "Pending DMS Export",
    "图文素材": "Image Creative",
    "视频素材": "Video Creative",
    "素材快照": "Creative Snapshot",
    "素材封面": "Cover",
}


def has_cn(s: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", s or ""))


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def main() -> None:
    xlsx = load_json(DATA / "product_en_from_xlsx.json", {})
    theme_cache = load_json(DATA / "theme_en_cache.json", {})

    products: dict[str, str] = {}
    for rec in xlsx.get("records") or []:
        en = str(rec.get("en") or "").strip()
        if not en or has_cn(en) or en.upper() in {"TBC", "N/A"}:
            continue
        for key in ("zh", "adName"):
            zh = str(rec.get(key) or "").strip()
            if zh and zh not in products:
                products[zh] = en
    # Excel 有重复中文名但英文写法不同，以下按看板实际产品口径固定
    products.update({
        "买4得5pcs": "5 PCS",
        "祛痘防晒": "Acne Defense Matte Serum Sunscreen",
        "B5面霜": "B5 Moisturizer",
        "B5身体脸部可用修复乳液": "B5 Face & Body Lotion",
        "美白防晒SPF50": "Brightening Sunscreen SPF 50",
        "美白面霜": "Niacinamide Brightening Moisturizer",
        "祛痘控油防晒": "Acne Defense Matte Serum Sunscreen",
        "全品类": "Multiple Product",
        "垂类达人": "High Vertical",
        "独立站": "Independent Site",
    })
    products.update(PRODUCT_EXTRA)

    # 只保留看板数据里实际出现过的标签，避免把 2 万多条视觉短语缓存全量下发前端
    used_tags: set[str] = set()
    materials = load_json(DATA / "materials.json", {})
    for row in materials.get("posts") or []:
        for field in ("tag1", "tag2", "tag3", "harvestTag"):
            val = str(row.get(field) or "").strip()
            if val:
                used_tags.add(val)

    tags: dict[str, str] = {}
    for zh, en in theme_cache.items():
        zh = str(zh).strip()
        en = str(en).strip()
        if zh in used_tags and en and not has_cn(en):
            tags[zh] = en
    tags.update(OVERRIDES)
    tags.update(TAG_EXTRA)

    out = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": {
            "products": "投放产品名称管理.xlsx + manual supplements",
            "tags": "theme_en_cache.json + manual supplements",
        },
        "products": dict(sorted(products.items())),
        "tags": dict(sorted(tags.items())),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"WROTE {OUT} products={len(products)} tags={len(tags)}")


if __name__ == "__main__":
    main()
