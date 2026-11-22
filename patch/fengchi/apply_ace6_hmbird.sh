#!/bin/bash
# 把内核树里现有的 hmbird（风驰）实现升级到 Numbersf/SCHED_PATCH 的
# Ace 6 版完美风驰 SCX（fengchi_oneplus_ace_6.patch）。
#
# 用法：apply_ace6_hmbird.sh <内核源码目录>
#
# 为什么不用 patch -p1：
#   该补丁假定基线是 vanilla sched_ext 树（没有 kernel/sched/hmbird/），
#   会删除 sched_ext 并新增 hmbird。RMX5010 用的 6.6.118 源码已经内置
#   hmbird，直接打会大量冲突。这里改为：
#     1) 整份替换补丁里 14 个 new-file 的 post-image；
#     2) 适配 3 个和基线不同的钩子（core.c / tick-sched.c / select_task_rq）。
#
# 版本识别不在这里改：RMX5010 通过 DTBO 注入
#   /soc/oplus,hmbird/version_type { type = "HMBIRD_OGKI"; }
# 让 get_hmbird_version_type() 返回 HMBIRD_OGKI_VERSION。
set -euo pipefail

COMMON="$1"
if [ -z "$COMMON" ]; then
	echo "用法: apply_ace6_hmbird.sh <内核源码目录>" >&2
	exit 1
fi
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/hmbird"

fail() {
	echo "::error::$*" >&2
	exit 1
}

[ -d "$COMMON/kernel/sched" ] || fail "$COMMON 不像内核源码目录"
[ -f "$COMMON/kernel/sched/hmbird/hmbird.c" ] || fail "$COMMON 没有 kernel/sched/hmbird/，无法升级"
cd "$COMMON"

V="$(awk -F= '/^VERSION[ \t]*=/{gsub(/[ \t]/,"",$2);print $2}' Makefile)"
P="$(awk -F= '/^PATCHLEVEL[ \t]*=/{gsub(/[ \t]/,"",$2);print $2}' Makefile)"
S="$(awk -F= '/^SUBLEVEL[ \t]*=/{gsub(/[ \t]/,"",$2);print $2}' Makefile)"
[ "$V.$P.$S" = "6.6.118" ] || fail "期望 6.6.118，实际 $V.$P.$S"

echo "== [1/4] 校验并替换 Ace 6 hmbird 的 14 个文件 =="
(cd "$HERE" && sha256sum -c SHA256SUMS >/dev/null) || fail "vendored hmbird 文件哈希不匹配"
FILES="include/linux/sched/hmbird_proc_val.h
include/linux/sched/hmbird_version.h
kernel/sched/hmbird.h
kernel/sched/hmbird/hmbird.c
kernel/sched/hmbird/hmbird_misc.c
kernel/sched/hmbird/hmbird_sched.h
kernel/sched/hmbird/hmbird_sched_proc.c
kernel/sched/hmbird/hmbird_sched_proc.h
kernel/sched/hmbird/hmbird_shadow_tick.c
kernel/sched/hmbird/hmbird_shadow_tick.h
kernel/sched/hmbird/hmbird_trace.h
kernel/sched/hmbird/hmbird_util_track.c
kernel/sched/hmbird/hmbird_util_track.h
kernel/sched/hmbird/slim.h"
for f in $FILES; do
	install -m 0644 "$SRC/$f" "$f"
	echo "  + $f"
done

echo "== [2/4] core.c：删除已被 hmbird_post_fork() 吸收的 hmbird_fork() 调用 =="
python3 - kernel/sched/core.c <<'PY'
import re
import sys

p = sys.argv[1]
s = open(p, encoding="utf-8").read()
block = re.compile(r"#ifdef CONFIG_HMBIRD_SCHED\n[ \t]*hmbird_fork\(p\);\n#endif\n")
s2, n = block.subn("", s, count=1)
if n == 0:
    if "hmbird_fork(p)" in s:
        sys.exit("core.c 里有 hmbird_fork(p) 调用，但不是预期的 ifdef 块")
    print("  - core.c 已无 hmbird_fork 调用，跳过")
else:
    open(p, "w", encoding="utf-8").write(s2)
    print("  + core.c 已删除 hmbird_fork 块")
PY

echo "== [3/4] tick-sched.c：接入 shadow tick 的 nohz 停止入口 =="
python3 - kernel/time/tick-sched.c <<'PY'
import re
import sys

p = sys.argv[1]
s = open(p, encoding="utf-8").read()
changed = False

if "hmbird_shadow_tick.h" not in s:
    anchor = "#include <trace/events/timer.h>\n"
    if anchor not in s:
        sys.exit("tick-sched.c 找不到 #include <trace/events/timer.h>")
    inc = ('#ifdef CONFIG_HMBIRD_SCHED\n'
           '#include "../sched/hmbird/hmbird_shadow_tick.h"\n'
           '#endif\n')
    s = s.replace(anchor, anchor + inc, 1)
    changed = True
    print("  + tick-sched.c 已加 hmbird_shadow_tick.h")
else:
    print("  - tick-sched.c 已有 hmbird_shadow_tick.h，跳过")

if "android_vh_tick_nohz_idle_stop_tick_handler" not in s:
    m = re.search(r"^([ \t]*)trace_android_vh_tick_nohz_idle_stop_tick\(NULL\);\n", s, re.M)
    if not m:
        sys.exit("tick-sched.c 找不到 trace_android_vh_tick_nohz_idle_stop_tick(NULL);")
    call = ("#ifdef CONFIG_HMBIRD_SCHED\n"
            + m.group(1) + "android_vh_tick_nohz_idle_stop_tick_handler(NULL,NULL);\n"
            "#endif\n")
    s = s[:m.end()] + call + s[m.end():]
    changed = True
    print("  + tick-sched.c 已加 shadow tick handler 调用")
else:
    print("  - tick-sched.c 已有 handler 调用，跳过")

if changed:
    open(p, "w", encoding="utf-8").write(s)
PY

echo "== [4/4] hmbird.c：select_task_rq 收敛到允许的 CPU =="
python3 - kernel/sched/hmbird/hmbird.c <<'PY'
import sys

p = sys.argv[1]
s = open(p, encoding="utf-8").read()

old = """static int select_task_rq_hmbird(struct task_struct *p, int prev_cpu, int wake_flags)
{
	return hmbird_select_cpu_dfl(p, prev_cpu, wake_flags);
}
"""

new = """static int select_task_rq_hmbird(struct task_struct *p, int prev_cpu, int wake_flags)
{
	int cpu = hmbird_select_cpu_dfl(p, prev_cpu, wake_flags);

	/*
	 * LZ4KDS_HMBIRD_SELECT_GUARD:
	 * hmbird_select_cpu_dfl() 的若干分支会返回不在 p 允许集合里的 CPU
	 * （例如 prev_cpu 或 pick_idle 的结果）。core.c 对 hmbird class 又
	 * 跳过了 select_fallback_rq()，所以这里必须自己兜住。
	 */
	if (unlikely(!cpumask_test_cpu(cpu, task_cpu_possible_mask(p)))) {
		int fallback = cpumask_any_and(task_cpu_possible_mask(p), cpu_active_mask);

		if (fallback < nr_cpu_ids)
			cpu = fallback;
	}

	return cpu;
}
"""

if "LZ4KDS_HMBIRD_SELECT_GUARD" in s:
    print("  - hmbird.c 已有 select guard，跳过")
elif old not in s:
    sys.exit("hmbird.c 找不到 select_task_rq_hmbird 的预期片段")
else:
    open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
    print("  + hmbird.c 已加 select guard")
PY

echo "== gki_defconfig =="
DEFCONFIG=arch/arm64/configs/gki_defconfig
if grep -qxF 'CONFIG_HMBIRD_SCHED=y' "$DEFCONFIG"; then
	echo "  - 已有 CONFIG_HMBIRD_SCHED=y"
else
	echo 'CONFIG_HMBIRD_SCHED=y' >> "$DEFCONFIG"
	echo "  + 已追加 CONFIG_HMBIRD_SCHED=y"
fi

echo "== 自检 =="
grep -q 'LZ4KDS_HMBIRD_SELECT_GUARD' kernel/sched/hmbird/hmbird.c || fail "select guard 未生效"
if grep -q 'hmbird_fork(p)' kernel/sched/core.c; then
	fail "core.c 仍残留 hmbird_fork(p)"
fi
grep -q 'hmbird_shadow_tick.h' kernel/time/tick-sched.c || fail "tick-sched 头文件未插入"
grep -q 'android_vh_tick_nohz_idle_stop_tick_handler' kernel/time/tick-sched.c || fail "tick-sched handler 未插入"
grep -q 'tick_hit' kernel/sched/hmbird/hmbird_shadow_tick.c || fail "shadow_tick 不是 Ace 6 版本"
grep -q 'boost_policy' kernel/sched/hmbird/hmbird_sched_proc.c || fail "proc 不是 Ace 6 版本"
grep -q 'hmbird_post_fork' kernel/sched/hmbird/hmbird.c || fail "hmbird.c 缺少 post_fork"
grep -q 'scx_systemui_pid' kernel/sched/hmbird/slim.h || fail "slim.h 缺少 systemui 声明"
grep -qxF 'CONFIG_HMBIRD_SCHED=y' "$DEFCONFIG" || fail "gki_defconfig 未启用 HMBIRD"
echo "Ace 6 完美风驰 SCX 已接入（DTBO 负责 OGKI 版本声明）"
