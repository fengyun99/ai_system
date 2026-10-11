# -*- coding: utf-8 -*-
"""修复 chat.py 中被写坏的 SSE 帧尾（把真实换行恢复为字面 \\n\\n）。"""
from pathlib import Path

p = Path("app/api/chat.py")
s = p.read_text(encoding="utf-8")
NL2 = chr(92) + "n" + chr(92) + "n"   # 字面 \n\n

# 损坏形态：...ensure_ascii=False)}<真实换行><空行>    （帧尾 \n\n 被写成真实换行）
broken1 = (
    "        yield f\"data: {json.dumps({'type': 'meta', 'conversation_id': conv.id, "
    "'turn_id': turn.id, 'title': conv.title}, ensure_ascii=False)}\n\n"
)
fixed1 = (
    "        yield f\"data: {json.dumps({'type': 'meta', 'conversation_id': conv.id, "
    "'turn_id': turn.id, 'title': conv.title}, ensure_ascii=False)}" + NL2 + "\"\n"
)
if broken1 in s:
    s = s.replace(broken1, fixed1)
    print("meta 帧修复")

broken2 = (
    "                yield f\"data: {json.dumps({'type': 'done', 'turn_id': turn.id}, "
    "ensure_ascii=False)}\n\n"
)
fixed2 = (
    "                yield f\"data: {json.dumps({'type': 'done', 'turn_id': turn.id}, "
    "ensure_ascii=False)}" + NL2 + "\"\n"
)
if broken2 in s:
    s = s.replace(broken2, fixed2)
    print("done 帧修复")

p.write_text(s, encoding="utf-8")
import ast
ast.parse(s)
print("语法 OK")
