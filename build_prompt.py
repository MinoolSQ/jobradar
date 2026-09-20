#!/usr/bin/env python3
"""
Sastavlja prompt za zakazanu rutinu od routine_prompt.md i profil.md. Profil se
ne drzi u repozitorijumu, pa mora da udje u sam prompt.

    python build_prompt.py            # ispisuje na stdout
    python build_prompt.py --out prompt.txt
"""

import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent


def build():
    sablon = (HERE / "routine_prompt.md").read_text(encoding="utf-8")
    profil = (HERE / "profil.md").read_text(encoding="utf-8")
    # Profilu se skida naslov prvog nivoa da ne bode oči usred prompta.
    profil = "\n".join(line for line in profil.splitlines() if not line.startswith("# "))
    return sablon.replace("{{PROFIL}}", profil.strip())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="fajl u koji se upisuje prompt")
    args = parser.parse_args()
    prompt = build()
    if args.out:
        Path(args.out).write_text(prompt, encoding="utf-8")
        print("upisano %d karaktera u %s" % (len(prompt), args.out))
    else:
        print(prompt)


if __name__ == "__main__":
    main()
