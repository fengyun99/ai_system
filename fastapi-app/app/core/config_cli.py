# -*- coding: utf-8 -*-
"""CLI：明文 → Enc[...]（Java 同款 SM4-CTR）。

用法：python -m app.core.config_cli <明文>
"""
import sys

from .config_loader import encrypt_to_enc


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python -m app.core.config_cli <明文>")
        raise SystemExit(1)
    print(encrypt_to_enc(sys.argv[1]))


if __name__ == "__main__":
    main()
