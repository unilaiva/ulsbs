"""Check CWL option tables against their TeX sources (no TeXstudio required)."""

import re
import sys
from pathlib import Path


def key_table(file: Path, selector: str) -> set[str]:
    """Return keys in the exact CWL selector block, without value hints."""
    lines = file.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"#keyvals:{selector}") + 1
    end = lines.index("#endkeyvals", start)
    return {
        re.split(r"[=#]", row, maxsplit=1)[0]
        for row in lines[start:end]
        if row and not row.startswith("#")
    }


def check_keys(actual: set[str], expected: set[str], source: str, *, subset: bool = False) -> None:
    """Fail with differences; curated class tables may omit valid options."""
    extra = actual - expected
    missing = set() if subset else expected - actual
    if extra or missing:
        raise SystemExit(f"{source}: extra={sorted(extra)}, missing={sorted(missing)}")


def main() -> None:
    """Check generic tables, plus project shims if their directory is supplied."""
    cwl = Path(__file__).resolve().parent
    tex = cwl.parents[1] / "src/ulsbs/assets/tex"
    song = (tex / "ulsbs-song.code.tex").read_text(encoding="utf-8")
    audio = (tex / "ulsbs-song-metadata.code.tex").read_text(encoding="utf-8")
    cls = (tex / "ulsbs-songbook.cls").read_text(encoding="utf-8")
    song_keys = set(
        re.findall(r"^\\(?:__ulsbs_song_key:nn\s+|ulNewSongKey)\{([^{}]+)\}", song, re.M)
    )
    audio_keys = set(re.findall(r"^\\define@key\{audio\}\{([^{}]+)\}", audio, re.M))
    class_keys = set(
        re.findall(r"^\\Declare(?:String)?Option(?:\[[^\]\n]*\])?\{([^{}]+)\}", cls, re.M)
    )
    check_keys(key_table(cwl / "ulsbs.cwl", r"\beginsong,\begin{song}"), song_keys, "song")
    check_keys(key_table(cwl / "ulsbs.cwl", r"\audio"), audio_keys, "audio")
    base_keys = key_table(cwl / "ulsbs-songbook.cwl", r"\documentclass/ulsbs-songbook#c")
    check_keys(base_keys, class_keys, "ulsbs-songbook", subset=True)

    if len(sys.argv) > 1:
        shims = Path(sys.argv[1])
        for name in ("ulsbs-songbook-astral-default", "ulsbs-songbook-unilaiva-default"):
            file = shims / f"{name}.cwl"
            if "#include:ulsbs-songbook" not in file.read_text(encoding="utf-8").splitlines():
                raise SystemExit(f"{file}: missing base CWL dependency")
            check_keys(key_table(file, rf"\documentclass/{name}#c"), class_keys, name, subset=True)
    print("CWL key tables match the ULSBS sources.")


if __name__ == "__main__":
    main()
