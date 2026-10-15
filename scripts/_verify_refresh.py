"""对比刷新前后看板数据（同一窗口聚合），验证刷新未破坏一致性。

Usage:
    python _verify_refresh.py <old.json> <new.json> [d0] [d1]
"""
import json
import sys


def load(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def agg(payload, combo, d0, d1):
    s = o = g = imp = lc = 0.0
    n = 0
    for post in payload["posts"]:
        if f"{post.get('brand')}-{post.get('country')}" != combo:
            continue
        hit = False
        for day, v in (post.get("days") or {}).items():
            if d0 <= day <= d1:
                hit = True
                s += float(v.get("spend") or 0)
                o += float(v.get("conversions") or 0)
                g += float(v.get("purchaseValue") or 0)
                imp += float(v.get("impressions") or 0)
                lc += float(v.get("linkClick") or 0)
        if hit:
            n += 1
    return dict(posts=n, spend=round(s, 2), orders=int(o), gmv=round(g, 2),
                imp=int(imp), linkClick=int(lc))


def day_agg(payload, day):
    out = {}
    for post in payload["posts"]:
        v = (post.get("days") or {}).get(day)
        if not v:
            continue
        c = f"{post['brand']}-{post['country']}"
        d = out.setdefault(c, [0.0, 0.0, 0.0, 0])
        d[0] += float(v.get("spend") or 0)
        d[1] += float(v.get("conversions") or 0)
        d[2] += float(v.get("purchaseValue") or 0)
        d[3] += 1
    return out


def main():
    old_p, new_p = sys.argv[1], sys.argv[2]
    d0 = sys.argv[3] if len(sys.argv) > 3 else "2026-10-01"
    d1 = sys.argv[4] if len(sys.argv) > 4 else "2026-10-14"
    old, new = load(old_p), load(new_p)
    print(f"old generatedAt={old['generatedAt']}  posts={len(old['posts'])}")
    print(f"new generatedAt={new['generatedAt']}  posts={len(new['posts'])}")
    for combo in ("NP-ID", "NP-MY", "LXP-ID", "LXP-MY"):
        a = agg(old, combo, d0, d1)
        b = agg(new, combo, d0, d1)
        flag = "OK " if (abs(a["spend"] - b["spend"]) < 1 and abs(a["orders"] - b["orders"]) <= 2) else "DIFF"
        print(f"[{flag}] {combo} {d0}~{d1}")
        print(f"       old {a}")
        print(f"       new {b}")
    print()
    for day in ("2026-10-14", "2026-10-15"):
        rows = day_agg(new, day)
        print(f"=== 新数据 {day} ===")
        for c, v in sorted(rows.items()):
            print(f"  {c}: spend={v[0]:.2f} orders={int(v[1])} gmv={v[2]:.2f} materials={v[3]}")


if __name__ == "__main__":
    main()
