#!/usr/bin/env python3
"""Inject /soc/oplus,hmbird/version_type { type = "HMBIRD_OGKI"; } into a DTBO.

Only entries whose root oplus,project-id matches --project-id are touched
(default 0x6018 = RMX5010).  Each target entry gets one new fragment with
target = <&soc>; the fragment is appended after the highest existing
fragment@N so no existing structure offset moves.  The original file is never
modified: output is written atomically to --output.

The FDT text is produced/compiled with dtc (stdin/stdout, no temp files).
Before inserting anything we verify that a dtc round-trip of the untouched
entry is lossless; after inserting we verify the fragment, the __fixups__/soc
entry, the preserved fragment set, and that non-target entries are byte
identical to the input.
"""
import argparse
import hashlib
import os
import pathlib
import re
import struct
import subprocess
import sys

DTBO_MAGIC = 0xD7B7AB1E
FDT_MAGIC = 0xD00DFEED
FRAG_RE = re.compile(r"\bfragment@(\d+)\s*\{")
ROOT_CLOSE_RE = re.compile(r"\n\};\s*\Z")

FRAGMENT = """\n\tfragment@{idx} {{\n\t\ttarget = <&soc>;\n\n\t\t__overlay__ {{\n\t\t\toplus,hmbird {{\n\t\t\t\tversion_type {{\n\t\t\t\t\ttype = "{typ}";\n\t\t\t\t}};\n\t\t\t}};\n\t\t}};\n\t}};\n"""


def die(msg, code=1):
    print("error: %s" % msg, file=sys.stderr)
    raise SystemExit(code)


def align4(n):
    return (n + 3) & ~3


def cstr(buf, off):
    end = buf.find(b"\x00", off)
    if end < 0:
        die("unterminated string at %d" % off)
    return buf[off:end].decode("utf-8", "replace")


def check_dtc(dtc):
    try:
        r = subprocess.run([dtc, "--version"], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        die("找不到 dtc，请安装 device-tree-compiler")
    if r.returncode != 0:
        die("dtc --version 失败: %s" % r.stderr.strip())
    return r.stdout.strip()


def run_dtc(dtc, args, data):
    r = subprocess.run([dtc, "-qq"] + args, input=data,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        die("dtc %s 失败: %s" % (" ".join(args), r.stderr.decode("utf-8", "replace")[:800]))
    return r.stdout


def fdt_root_props(blob):
    if len(blob) < 40:
        die("FDT 太短")
    magic, total, off_struct, off_strings, off_rsv, ver, last, cpuid, size_str, size_struct = \
        struct.unpack_from(">10I", blob, 0)
    if magic != FDT_MAGIC:
        die("FDT magic 错误: 0x%08x" % magic)
    if total > len(blob):
        die("FDT total_size %d 超过 entry 大小 %d" % (total, len(blob)))
    strings = blob[off_strings:off_strings + size_str]
    pos = off_struct
    depth = 0
    props = {}
    while True:
        if pos + 4 > len(blob):
            die("FDT struct 越界")
        tok = struct.unpack_from(">I", blob, pos)[0]
        pos += 4
        if tok == 1:          # BEGIN_NODE
            end = blob.find(b"\x00", pos)
            if end < 0:
                die("FDT node 名未终止")
            pos = align4(end + 1)
            depth += 1
        elif tok == 2:        # END_NODE
            depth -= 1
        elif tok == 3:        # PROP
            ln, nameoff = struct.unpack_from(">II", blob, pos)
            pos += 8
            val = blob[pos:pos + ln]
            pos = align4(pos + ln)
            if depth == 1:
                props[cstr(strings, nameoff)] = val
        elif tok == 4:        # NOP
            pass
        elif tok == 9:        # END
            break
        else:
            die("FDT token 0x%x 无法识别" % tok)
    return props


def fragment_set(dts):
    return set(int(x) for x in FRAG_RE.findall(dts))


def patch_entry(dtc, blob, typ, idx):
    dts = run_dtc(dtc, ["-I", "dtb", "-O", "dts", "-"], blob).decode("utf-8")

    # Sanity: this dtc must round-trip the untouched entry without any change.
    rt = run_dtc(dtc, ["-I", "dts", "-O", "dtb", "-@", "-o", "/dev/stdout", "-"], dts.encode())
    back = run_dtc(dtc, ["-I", "dtb", "-O", "dts", "-"], rt).decode("utf-8")
    if back != dts:
        die("dtc round-trip 改变了 entry 语义，拒绝继续")

    old_frags = fragment_set(dts)
    if idx in old_frags:
        die("fragment@%d 已存在" % idx)
    m = ROOT_CLOSE_RE.search(dts)
    if not m:
        die("找不到根节点收尾 };")
    frag = FRAGMENT.format(idx=idx, typ=typ)
    new_dts = dts[:m.start()] + frag + dts[m.start():]
    new_blob = run_dtc(dtc, ["-I", "dts", "-O", "dtb", "-@", "-o", "/dev/stdout", "-"], new_dts.encode())

    out = run_dtc(dtc, ["-I", "dtb", "-O", "dts", "-"], new_blob).decode("utf-8")
    if out.count(typ) != 1:
        die("新 entry 里 %s 出现 %d 次（期望 1）" % (typ, out.count(typ)))
    if "oplus,hmbird" not in out or "version_type" not in out:
        die("新 entry 缺少 oplus,hmbird/version_type")
    if "target = <&soc>" not in out:
        die("新 entry 缺少 target = <&soc>")
    if fragment_set(out) != old_frags | {idx}:
        die("fragment 集合异常：期望 %s，实际 %s" % (sorted(old_frags | {idx}), sorted(fragment_set(out))))
    fixup = '"/fragment@%d:target:0"' % idx
    if fixup not in out:
        die("__fixups__/soc 里没有 %s" % fixup)
    return new_blob


def main():
    ap = argparse.ArgumentParser(description="给 DTBO 注入 HMBIRD_OGKI 版本节点")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--project-id", default="0x6018", help="oplus,project-id，默认 0x6018")
    ap.add_argument("--type", default="HMBIRD_OGKI")
    ap.add_argument("--fragment", type=int, default=0, help="强制 fragment 编号；默认最大+1")
    ap.add_argument("--dtc", default="dtc")
    ap.add_argument("--pad-to", type=lambda s: int(s, 0), default=0,
                    help="补零到指定字节数（给需要整分区镜像的刷写工具）")
    args = ap.parse_args()

    inp = pathlib.Path(args.input)
    out = pathlib.Path(args.output)
    if not inp.is_file():
        die("输入不存在: %s" % inp)
    if inp.resolve() == out.resolve():
        die("--input 与 --output 不能是同一个文件")

    dtc_ver = check_dtc(args.dtc)
    project_id = int(args.project_id, 0)

    data = inp.read_bytes()
    if len(data) < 32:
        die("文件太短，不是 DTBO")
    magic, total, header_size, entry_size, entry_count, entries_offset, page_size, version = \
        struct.unpack_from(">8I", data, 0)
    if magic != DTBO_MAGIC:
        die("DTBO magic 错误: 0x%08x（期望 0x%08x）" % (magic, DTBO_MAGIC))
    if header_size != 32 or entry_size != 32:
        die("不支持的 DTBO header/entry size: %d/%d" % (header_size, entry_size))
    if entries_offset + entry_count * entry_size > len(data):
        die("DTBO 表越界")
    if total > len(data):
        die("DTBO total_size %d 超过文件大小 %d" % (total, len(data)))

    print("dtc: %s" % dtc_ver)
    print("input: %s (%d bytes, sha256 %s)" % (inp, len(data), hashlib.sha256(data).hexdigest()))
    print("entries: %d, total_size: %d" % (entry_count, total))

    entries = []
    for i in range(entry_count):
        sz, off, ent_id, rev, c0, c1, c2, c3 = struct.unpack_from(">8I", data, entries_offset + i * entry_size)
        if off + sz > len(data) or sz < 40:
            die("entry %d 越界或过小" % i)
        blob = data[off:off + sz]
        props = fdt_root_props(blob)
        pid = None
        if "oplus,project-id" in props:
            raw = props["oplus,project-id"]
            if len(raw) == 4:
                pid = struct.unpack(">I", raw)[0]
            elif len(raw) == 8:
                pid = struct.unpack(">II", raw)[0]
        entries.append({"i": i, "size": sz, "off": off, "id": ent_id, "rev": rev,
                        "custom": (c0, c1, c2, c3), "blob": blob, "pid": pid})
        print("  entry %d: size=%d project=%s%s" % (
            i, sz, ("0x%x" % pid) if pid is not None else "absent",
            "  <-- target" if pid == project_id else ""))

    targets = [e for e in entries if e["pid"] == project_id]
    if not targets:
        die("没有任何 entry 的 oplus,project-id == 0x%x" % project_id, code=2)

    for e in targets:
        if e["blob"].count(args.type.encode()) or b"oplus,hmbird" in e["blob"]:
            print("  entry %d 已包含 %s，保持原样" % (e["i"], args.type))
            continue
        if args.fragment:
            idx = args.fragment
        else:
            idx = max(fragment_set(run_dtc(args.dtc, ["-I", "dtb", "-O", "dts", "-"],
                                          e["blob"]).decode("utf-8")), default=0) + 1
        print("  entry %d: 注入 fragment@%d (%s)" % (e["i"], idx, args.type))
        e["new_blob"] = patch_entry(args.dtc, e["blob"], args.type, idx)

    # Rebuild the container: header + table + sequential payload.
    cur = entries_offset + entry_count * entry_size
    table = bytearray()
    payload = bytearray()
    for e in entries:
        blob = e.get("new_blob", e["blob"])
        table += struct.pack(">8I", len(blob), cur, e["id"], e["rev"], *e["custom"])
        payload += blob
        cur += len(blob)
    new_total = cur
    header = struct.pack(">8I", magic, new_total, header_size, entry_size,
                         entry_count, entries_offset, page_size, version)
    image = header + table + payload

    if args.pad_to:
        if args.pad_to < new_total:
            die("--pad-to %d 小于镜像 %d" % (args.pad_to, new_total))
        image += b"\x00" * (args.pad_to - new_total)

    # Post checks.
    m2, t2, h2, e2, c2, o2, p2, v2 = struct.unpack_from(">8I", image, 0)
    if (m2, t2, h2, e2, c2, o2, p2, v2) != (magic, new_total, header_size, entry_size,
                                            entry_count, entries_offset, page_size, version):
        die("重建后的 header 不自洽")
    for e in entries:
        sz, off = struct.unpack_from(">II", image, entries_offset + e["i"] * entry_size)
        blob = image[off:off + sz]
        if struct.unpack_from(">I", blob, 0)[0] != FDT_MAGIC:
            die("entry %d 的 FDT magic 错误" % e["i"])
        if e["pid"] == project_id and not e["blob"].count(args.type.encode()):
            if blob.count(args.type.encode()) != 1:
                die("entry %d 的 %s 数量不是 1" % (e["i"], args.type))
        elif e["pid"] != project_id:
            if blob != e["blob"]:
                die("非目标 entry %d 被意外修改" % e["i"])

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_bytes(image)
    os.replace(tmp, out)
    os.chmod(out, 0o644)
    print("output: %s (%d bytes, sha256 %s)" % (out, len(image), hashlib.sha256(image).hexdigest()))
    print("OK")


if __name__ == "__main__":
    main()
