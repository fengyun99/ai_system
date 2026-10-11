# -*- coding: utf-8 -*-
"""精确修复 chat.py 残留的帧尾损坏（多余引号行 + item 帧缺尾）。"""
from pathlib import Path

p = Path("app/api/chat.py")
lines = p.read_text(encoding="utf-8").split("\n")
NL2 = chr(92) + "n" + chr(92) + "n"

out = []
i = 0
while i < len(lines):
    line = lines[i]
    # 1) 修复后的 meta 行后跟孤立引号行 → 删除孤立引号
    if line.strip() == '"' and i > 0 and "json.dumps({'type': 'meta'" in lines[i - 1]:
        i += 1
        continue
    # 2) item 帧行缺帧尾：yield f"data: {json.dumps(item, ensure_ascii=False)} 后跟空行
    if line.strip().startswith('yield f"data: {json.dumps(item, ensure_ascii=False)}') \
            and line.rstrip().endswith("ensure_ascii=False)}") \
            and i + 1 < len(lines) and lines[i + 1].strip() == "":
        out.append(line.rstrip()[:-1] + ")}" + '"' if False else line.rstrip()[: -len("ensure_ascii=False)}")] + "ensure_ascii=False)}" + NL2 + '"')
        i += 2  # 跳过残留空行（由我们补的行自带换行）
        continue
    out.append(line)
    i += 1

p.write_text("\n".join(out), encoding="utf-8")
import ast
ast.parse(p.read_text(encoding="utf-8"))
print("chat.py 语法 OK")
