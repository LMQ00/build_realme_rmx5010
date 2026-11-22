#!/usr/bin/env python3
"""Extract the 14 Ace 6 hmbird post-image files from the vendored Fengchi patch.

The Numbersf patch is generated against a vanilla sched_ext tree and creates the
hmbird implementation as new files.  We keep that patch for provenance, but the
build consumes these extracted files so the apply step is deterministic and
hash-checked.
"""
import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
PATCH = ROOT / "fengchi_oneplus_ace_6.patch"
OUT = ROOT / "hmbird"
SUMS = ROOT / "SHA256SUMS"

FILES = [
    "include/linux/sched/hmbird_proc_val.h",
    "include/linux/sched/hmbird_version.h",
    "kernel/sched/hmbird.h",
    "kernel/sched/hmbird/hmbird.c",
    "kernel/sched/hmbird/hmbird_misc.c",
    "kernel/sched/hmbird/hmbird_sched.h",
    "kernel/sched/hmbird/hmbird_sched_proc.c",
    "kernel/sched/hmbird/hmbird_sched_proc.h",
    "kernel/sched/hmbird/hmbird_shadow_tick.c",
    "kernel/sched/hmbird/hmbird_shadow_tick.h",
    "kernel/sched/hmbird/hmbird_trace.h",
    "kernel/sched/hmbird/hmbird_util_track.c",
    "kernel/sched/hmbird/hmbird_util_track.h",
    "kernel/sched/hmbird/slim.h",
]

def extract(text, path):
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        header = lines[i].rstrip("\n")
        if header == "diff --git b/%s a/%s" % (path, path):
            j = i + 1
            new_file = False
            while j < len(lines) and not lines[j].startswith("@@"):
                if lines[j].startswith("new file mode"):
                    new_file = True
                j += 1
            if not new_file:
                raise SystemExit("%s: not a new file in patch" % path)
            body = []
            while j < len(lines) and lines[j].startswith("@"):
                j += 1
                while j < len(lines):
                    line = lines[j]
                    if line.startswith("diff --git "):
                        break
                    if line.startswith("+"):
                        if not line.startswith("+++"):
                            body.append(line[1:])
                    elif line.startswith("-") or line.startswith(" "):
                        raise SystemExit("%s: unexpected non-added line" % path)
                    elif line.strip() == "":
                        body.append("\n")
                    else:
                        break
                    j += 1
                break
            return "".join(body)
        i += 1
    raise SystemExit("%s: not found in patch" % path)

def main():
    text = PATCH.read_text(encoding="utf-8")
    rows = []
    for path in FILES:
        content = extract(text, path)
        if not content.endswith("\n"):
            content += "\n"
        dest = OUT / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        digest = hashlib.sha256(content.encode()).hexdigest()
        rows.append("%s  hmbird/%s" % (digest, path))
        print("%s  %s" % (digest, path))
    SUMS.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print("wrote %d files + SHA256SUMS" % len(rows))

if __name__ == "__main__":
    main()
