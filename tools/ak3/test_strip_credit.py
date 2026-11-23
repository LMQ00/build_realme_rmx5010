#!/usr/bin/env python3
"""strip_credit.py 的回归测试。"""
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).with_name("strip_credit.py")

ANY_KERNEL = """### AnyKernel3 Rust Loader
properties() { '
kernel.string=KernelSU by KernelSU Developersand and 本内核包来自TG频道(Channel)：https://t.me/qdykernel
do.devicecheck=0
do.modules=0
do.systemless=0
do.cleanup=1
'; } # end properties

tools/ak3-loader
rc=$?
exit "$rc"
"""

UPDATE_BINARY = """#!/sbin/sh
# AnyKernel3 Backend (DO NOT CHANGE)
# osm0sis @ xda-developers

KERNEL_STRING="$(file_getprop anykernel.sh kernel.string)";
ui_print "$KERNEL_STRING";
grep -oE 'AK_BASE.*' META-INF/com/google/android/updater-script >&2;
ui_print " " "AnyKernel3 by osm0sis @ xda-developers" " ";
ui_print " ";
"""


def run(root):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(root)],
        capture_output=True,
        text=True,
    )


class StripCreditTest(unittest.TestCase):
    def make_root(self, tmp, update_binary=UPDATE_BINARY):
        root = pathlib.Path(tmp)
        (root / "META-INF/com/google/android").mkdir(parents=True)
        (root / "anykernel.sh").write_text(ANY_KERNEL, encoding="utf-8")
        (root / "META-INF/com/google/android/update-binary").write_text(
            update_binary, encoding="utf-8"
        )
        return root

    def test_strips_custom_author_and_ak3_banner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            result = run(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            anykernel = (root / "anykernel.sh").read_text(encoding="utf-8")
            update_binary = (
                root / "META-INF/com/google/android/update-binary"
            ).read_text(encoding="utf-8")
            self.assertIn("kernel.string=KernelSU\n", anykernel)
            self.assertNotIn("qdykernel", anykernel)
            self.assertNotIn("KernelSU by KernelSU", anykernel)
            self.assertNotIn("AnyKernel3 by osm0sis", update_binary)
            # 只删署名 banner，安装逻辑保持原样。
            self.assertIn('ui_print "$KERNEL_STRING";', update_binary)
            self.assertIn("grep -oE 'AK_BASE.*'", update_binary)

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            self.assertEqual(run(root).returncode, 0)
            files = [root / "anykernel.sh", root / "META-INF/com/google/android/update-binary"]
            before = [p.read_bytes() for p in files]
            result = run(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(before, [p.read_bytes() for p in files])

    def test_rejects_residual_credit(self):
        update_binary = UPDATE_BINARY + 'ui_print "作者：秋刀鱼";\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp, update_binary)
            result = run(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("仍可能包含署名", result.stderr)

    def test_rejects_credit_in_banner_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            (root / "banner").write_text("作者：秋刀鱼\n", encoding="utf-8")
            result = run(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("banner:1", result.stderr)

    def test_rejects_missing_kernel_string_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            (root / "anykernel.sh").write_text(
                "### AnyKernel3 Rust Loader\n", encoding="utf-8"
            )
            result = run(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("kernel.string", result.stderr)


if __name__ == "__main__":
    unittest.main()
