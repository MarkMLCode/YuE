#!/usr/bin/env python3
"""Create a local player for all candidates, including failures and audit flags."""
import argparse
import html
from pathlib import Path
from urllib.parse import quote

from common import read


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    a = p.parse_args()
    manifest = read(a.run / "batch.json")
    cards = []
    for c in sorted((a.run / "candidates").glob("*")):
        brief = read(c / "brief.json")
        status = read(c / "state.json") if (c / "state.json").exists() else {"status": "not_generated"}
        audit = read(c / "audit.json") if (c / "audit.json").exists() else {}
        review = read(c / "decision.json") if (c / "decision.json").exists() else {}
        src = quote(f"candidates/{c.name}/native/audio.flac")
        player = f'<audio controls preload="none" src="{src}"></audio>' if (c / "native/audio.flac").exists() else ""
        title = html.escape(brief["title"])
        flags = html.escape(", ".join(audit.get("issues", [])) if audit else "Not audited")
        detail = html.escape(str(status) + "\n" + str(review))
        style = html.escape(read(c / "request.json")["style"])
        cards.append(f'<article><h2>{title}</h2><p>{html.escape(c.name)}</p>{player}<p>{flags}</p>'
                     f'<details><summary>Prompt and screening result</summary><p>{style}</p><pre>{detail}</pre></details></article>')
    text = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>BGM candidate audition</title><style>body{max-width:900px;margin:40px auto;padding:0 20px;font:17px/1.6 system-ui}'
            'article{border:1px solid #aaa;padding:20px;margin:20px 0;border-radius:12px}audio{width:100%}pre{white-space:pre-wrap}</style>'
            f'<h1>{html.escape(manifest["theme"])}</h1><p>Compare full tracks and their endings. Audit results are automated screening, not a quality verdict.</p>'
            + "".join(cards) + '</html>')
    (a.run / "listen.html").write_text(text, encoding="utf-8")
    print(a.run / "listen.html")


if __name__ == "__main__":
    main()
