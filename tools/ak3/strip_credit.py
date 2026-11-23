#!/usr/bin/env python3
"""去除 AnyKernel3 安装输出中的作者/署名信息。

AK3 模板由 main.bin 在构建时从上游 clone，署名只能在这之后处理。
这里只改「安装脚本会打印」的内容：

  * anykernel.sh 的 kernel.string —— update-binary 会把它 ui_print 出来；
  * update-binary 里 AK3 自带的 osm0sis banner。

不改 tools/ak3-core.sh 和包内的说明 txt：它们参与 ak3-loader 的完整性 /
载荷校验，改动会破坏刷入流程。处理完后会再扫一遍会被打印的内容，
确认没有残留，避免上游改文案后署名被静默带出。

用法：strip_credit.py <AnyKernel3 目录>
"""
import argparse
import pathlib
import re
import sys

AK3_ROOT_MARKER = "META-INF/com/google/android/update-binary"
ANY_KERNEL = "anykernel.sh"
KERNEL_STRING = "kernel.string=KernelSU"

KERNEL_STRING_RE = re.compile(r"^(?P<indent>[ \t]*)kernel\.string=.*?(?P<eol>\r?\n)?$")
AK3_BANNER_RE = re.compile(
    r"^\s*ui_print\b.*(?:AnyKernel3\s+by\s+osm0sis|osm0sis\s*@\s*xda-developers)"
)

# 只用于判断「会被打印的内容」里是否还有署名，不要拿去扫注释。
CREDIT_MARKERS = (
    "qdykernel",
    "秋刀鱼",
    "酷安",
    "作者",
    "署名",
    "osm0sis",
    "xda-developers",
    "t.me/",
)
CREDIT_BY_RE = re.compile(r"\bby\b(?![-/])", re.IGNORECASE)

# update-binary 会 ui_printfile 这两个文件（存在时）。
PRINTED_FILES = ("banner", "version")


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def has_credit(text):
    lowered = text.lower()
    if any(marker.lower() in lowered for marker in CREDIT_MARKERS):
        return True
    return CREDIT_BY_RE.search(text) is not None


def read_lines(path):
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def strip_kernel_string(anykernel):
    lines = read_lines(anykernel)
    count = 0
    for i, line in enumerate(lines):
        m = KERNEL_STRING_RE.match(line)
        if not m:
            continue
        lines[i] = f"{m.group('indent')}{KERNEL_STRING}{m.group('eol') or ''}"
        count += 1
    if count == 0:
        die(f"{anykernel} 里找不到 kernel.string= 锚点，上游模板可能已变更")
    if count > 1:
        die(f"{anykernel} 里出现 {count} 个 kernel.string=，不确定该保留哪个")
    text = "".join(lines)
    if text != anykernel.read_text(encoding="utf-8"):
        anykernel.write_text(text, encoding="utf-8")
        print(f"[ak3] 已归一化 {ANY_KERNEL}: {KERNEL_STRING}")


def strip_ak3_banner(update_binary):
    lines = read_lines(update_binary)
    kept = []
    removed = 0
    for line in lines:
        if AK3_BANNER_RE.search(line):
            removed += 1
            continue
        kept.append(line)
    if removed:
        update_binary.write_text("".join(kept), encoding="utf-8")
        print(f"[ak3] 已移除 AK3 署名 banner: {removed} 行")


def check_printed_credit(path, kind):
    problems = []
    for lineno, line in enumerate(read_lines(path), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if has_credit(line):
            problems.append(f"{kind}:{lineno}: {stripped}")
    return problems


def verify(root, anykernel, update_binary):
    problems = []
    problems += check_printed_credit(anykernel, ANY_KERNEL)
    problems += check_printed_credit(update_binary, "update-binary")
    for name in PRINTED_FILES:
        p = root / name
        if not p.is_file():
            continue
        for lineno, line in enumerate(read_lines(p), 1):
            if has_credit(line):
                problems.append(f"{name}:{lineno}: {line.strip()}")
    if problems:
        die("安装输出里仍可能包含署名：\n  " + "\n  ".join(problems))


def main():
    parser = argparse.ArgumentParser(description="去除 AnyKernel3 安装输出中的作者/署名信息")
    parser.add_argument("root", type=pathlib.Path, help="AnyKernel3 解包目录")
    args = parser.parse_args()

    root = args.root
    anykernel = root / ANY_KERNEL
    update_binary = root / AK3_ROOT_MARKER
    if not anykernel.is_file():
        die(f"找不到 {anykernel}")
    if not update_binary.is_file():
        die(f"找不到 {update_binary}")

    strip_kernel_string(anykernel)
    strip_ak3_banner(update_binary)
    verify(root, anykernel, update_binary)
    print(f"[ak3] 署名检查通过: {root}")


if __name__ == "__main__":
    main()
