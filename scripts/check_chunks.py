"""检查 chunk JSON 文件中的 source 字段。"""
import json, sys
sys.path.insert(0, '.')
for fname in ['红楼梦', '三国演义']:
    path = f'chunks/{fname}.json'
    try:
        data = json.loads(open(path, encoding='utf-8').read())
        c0 = data[0] if data else {}
        print(f"{fname}: {len(data)} blocks, id={c0.get('id','?')}, source={c0.get('source','?')}")
    except Exception as e:
        print(f"{fname}: {e}")
