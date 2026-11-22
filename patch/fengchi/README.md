# Ace 6 完美风驰 SCX（hmbird）移植

## 来源

- 补丁：`fengchi_oneplus_ace_6.patch`
- 仓库：https://github.com/Numbersf/SCHED_PATCH（分支 `sm8750`）
- sha256：`0f835fea08a94e69409e9b4ffafd97af54c70c9871b25b788cb2eb5dafbbcc97`

该分支下 `fengchi_oneplus_13_b.patch`、`fengchi_oneplus_13t_b.patch`、`fengchi_oneplus_ace5_pro_b.patch`、`fengchi_oneplus_ace_6.patch` 四份文件字节完全相同，所以这里保留 `ace_6` 的名字。

## 为什么不直接打补丁

补丁的基线是 **vanilla sched_ext**：它会删除 `kernel/sched/ext.c`、`tools/sched_ext/`，并新增 `kernel/sched/hmbird/`。RMX5010 用的 cctv18 `oneplus/sm8750_b_16.0.0_oneplus_13_6.6.118` 源码已经内置 hmbird（且已经删掉 ext.c），直接 `patch -p1` 会在新文件创建和 core.c hunk 上大量冲突。

## 做法

`extract_hmbird.py` 从 vendored 补丁里提取 14 个 new-file 的 post-image，写入 `hmbird/` 并生成 `SHA256SUMS`。`apply_ace6_hmbird.sh` 再做：

1. 校验源码为 6.6.118、存在 `kernel/sched/hmbird/hmbird.c`；校验 14 个文件哈希。
2. 整份覆盖 14 个文件。
3. `kernel/sched/core.c`：删除

   ```c
   #ifdef CONFIG_HMBIRD_SCHED
           hmbird_fork(p);
   #endif
   ```

   因为 Ace 6 版把 prepare/入队逻辑并入了 `hmbird_post_fork()`。
4. `kernel/time/tick-sched.c`：若缺则补 `hmbird_shadow_tick.h` 和 `android_vh_tick_nohz_idle_stop_tick_handler()` 调用；本基线已有，脚本会跳过。
5. `kernel/sched/hmbird/hmbird.c`：给 `select_task_rq_hmbird()` 加 `LZ4KDS_HMBIRD_SELECT_GUARD`，把返回值收敛到 `task_cpu_possible_mask(p) ∩ cpu_active_mask`。
6. 断言 `gki_defconfig` 有 `CONFIG_HMBIRD_SCHED=y`。

## 14 个文件

- `include/linux/sched/hmbird_proc_val.h`
- `include/linux/sched/hmbird_version.h`
- `kernel/sched/hmbird.h`
- `kernel/sched/hmbird/hmbird.c`
- `kernel/sched/hmbird/hmbird_misc.c`
- `kernel/sched/hmbird/hmbird_sched.h`
- `kernel/sched/hmbird/hmbird_sched_proc.c`
- `kernel/sched/hmbird/hmbird_sched_proc.h`
- `kernel/sched/hmbird/hmbird_shadow_tick.c`
- `kernel/sched/hmbird/hmbird_shadow_tick.h`
- `kernel/sched/hmbird/hmbird_trace.h`
- `kernel/sched/hmbird/hmbird_util_track.c`
- `kernel/sched/hmbird/hmbird_util_track.h`
- `kernel/sched/hmbird/slim.h`

## 版本识别

这里不打 `hmbird_version.h` 的 `FORCE_OGKI` 回落。`get_hmbird_version_type()` 只认 DT 节点：

```text
/soc/oplus,hmbird/version_type
    type = "HMBIRD_OGKI"
```

所以必须配合 `tools/dtbo/patch_hmbird_dtbo.py` 生成的 DTBO；否则 `HMBIRD_UNKNOW_VERSION` 会让 `hmbird_proc_init()` 和 `hmbird_shadow_tick_init()` early-return。

## 升级补丁

1. 替换 `fengchi_oneplus_ace_6.patch`。
2. 跑 `python3 extract_hmbird.py` 重新生成 `hmbird/` 与 `SHA256SUMS`。
3. 重新确认三个锚点仍在；脚本会 fail-loud。
4. 跑一次 CI 构建。
