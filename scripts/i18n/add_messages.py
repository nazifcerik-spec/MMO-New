"""Dev helper: merge a nested {key: [en,tr,zh-CN,es]} dict into the four message catalogs."""
import json, sys
LOCALES = ["en", "tr", "zh-CN", "es"]

def pick(d, i):
    return {k: (v[i] if isinstance(v, list) else pick(v, i)) for k, v in d.items()}

def merge(a, b):
    for k, v in b.items():
        a[k] = merge(a.get(k, {}), v) if isinstance(v, dict) else v
    return a

add = json.load(open(sys.argv[1]))
for i, l in enumerate(LOCALES):
    p = f"messages/{l}.json"
    m = json.load(open(p))
    merge(m, pick(add, i))
    json.dump(m, open(p, "w"), ensure_ascii=False, indent=2)
    open(p, "a").write("\n")
