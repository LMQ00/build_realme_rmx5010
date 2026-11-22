# build_realme_rmx5010

真我 GT7 Pro（RMX5010 / SM8750 / 6.6.118）专用内核构建仓库。

以 [LMQ00/build_oneplus_sm8750](https://github.com/LMQ00/build_oneplus_sm8750) 的 realme_GT7pro + LZ4KDS 实现为基线，加入 **Ace 6 版完美风驰 SCX**，并用 **DTBO 注入 HMBIRD_OGKI** 让内核识别风驰版本。

## 先读：三条硬约束

1. **本仓库只产出文件，不执行刷机。** CI 只编译和上传 artifact；本地工具只写普通文件，不碰分区。
2. **DTBO 改动会使 AVB 失效。** 原 dtbo 在 0x703000 有 AVB0 footer；本仓库不伪造、不重签。后续刷入必须已解锁并关闭验证，且先备份原 dtbo。
3. **没刷 DTBO 时风驰不会启用。** 本仓库刻意不打 `hmbird_version.h` 的 `FORCE_OGKI` 回落补丁；版本识别只认 `/soc/oplus,hmbird/version_type`。

## 特性

- LZ4K / LZ4KD in-tree 压缩 + HybridSwap zram 驱动 + KSU 侧载模块 + RMX5010 原厂 CRC 预检
- Ace 6 完美风驰 SCX（Numbersf/SCHED_PATCH `fengchi_oneplus_ace_6.patch`）
- DTBO 注入 `oplus,hmbird/version_type = HMBIRD_OGKI`（仅 0x6018 的两个 overlay）
- 可选 BakaSU、SUSFS、BBG、ADIOS、Re-Kernel、Droidspaces；输出 AnyKernel3 与 LZ4KDS 模块
- 源码固定到 `2a4726b11594dd57d0779d2685fad5c81e5ed553`，避免分支漂移破坏移植锚点

## 目录

```text
.github/workflows/Build_rmx5010.yml   # 单机型构建工作流
patch/lz4kds/                          # LZ4KDS 实现（intree/driver/module/abi/scripts）
patch/fengchi/                         # Ace 6 风驰补丁、提取文件、apply 脚本
patch/Fix_Screen_Flickering.patch      # 6.6.118 屏幕闪烁修复
patch/adios_ioscheduler_6.6.patch      # 可选 ADIOS
tools/dtbo/patch_hmbird_dtbo.py        # DTBO 注入工具（本地）
```

## 构建

1. Fork / clone 本仓库。
2. Actions → `Build_rmx5010` → Run workflow。
3. 首次建议 `enable_release=false`，只拿 artifact；确认无误后再开 release。

| 输入 | 默认 | 说明 |
|---|---|---|
| `enable_release` | false | 是否创建 Release |
| `custom_kernel_suffix` | 空 | 内核后缀，留空用设备官方值 |
| `custom_kernel_time` | 空 | 构建时间字符串，留空用设备官方值 |
| `enable_susfs` | true | SUSFS |
| `enable_droidspaces` | false | Droidspaces 容器 |
| `enable_ReKernel` | false | Re-Kernel |
| `enable_Adios` | true | ADIOS IO 调度器 |
| `enable_bbg` | true | BBG 基带守护 |

产物：`AK3_<ksuver>_realme_GT7pro_BakaSU` 与 `LZ4KDS_module_realme_GT7pro`。

## LZ4KDS（照搬参考实现）

1. `apply_intree.sh` 把 `crypto/lz4k*.c`、`lib/lz4k*`、头文件整份拷入内核树，锚点式改 Kconfig/Makefile/zram，并在 `gki_defconfig` 内置 `CONFIG_CRYPTO_LZ4K/LZ4KD=y`。
2. 构建后用 `abi/check_abi.py` 对 `device_crc_reference.tsv` 的 304 条 RMX5010 原厂 CRC 逐条比对。
3. `build_driver.sh` 编译 HybridSwap/LZ4KDS zram 驱动，`fix_export_crc.py` 回填 5 个导出符号 CRC，`package_ksu_module.sh` 打 KSU 模块。

## 完美风驰 SCX（Ace 6）

为什么不直接 `patch -p1`：该补丁假定基线是 vanilla sched_ext、没有 `kernel/sched/hmbird/`；RMX5010 的 6.6.118 源码已经内置 hmbird，直接打会大量冲突。

`patch/fengchi/apply_ace6_hmbird.sh` 的做法：

- 用补丁里 14 个 new-file 的 post-image 整份替换现有 hmbird；每个文件有 SHA256SUMS 校验。
- `core.c` 删除旧的 `hmbird_fork(p)` 调用（Ace 6 版把逻辑并入 `hmbird_post_fork()`）。
- `tick-sched.c` 只在缺入口时补 shadow tick / nohz handler（本基线已有，则跳过）。
- `hmbird.c` 给 `select_task_rq_hmbird()` 加 `LZ4KDS_HMBIRD_SELECT_GUARD`：结果不在 `task_cpu_possible_mask(p) ∩ cpu_active_mask` 时收敛。
- 不自带 `FORCE_OGKI`，版本由 DTBO 提供。

## DTBO：HMBIRD_OGKI

```bash
python3 tools/dtbo/patch_hmbird_dtbo.py \
  --input  /storage/emulated/0/Download/111/dtbo.img \
  --output /storage/emulated/0/Download/111/dtbo_hmbird.img \
  --project-id 0x6018 \
  --type HMBIRD_OGKI
```

- 只改 `oplus,project-id = 0x6018` 的 entry（本机为 entry 0 与 4）。
- 每个目标 entry 追加 `fragment@154`：`target = <&soc>`，`oplus,hmbird/version_type/type = HMBIRD_OGKI`。
- 其余 entry 逐字节不变；原 `dtbo.img` 不动；重复运行幂等。
- 默认输出精确 `total_size` 镜像（7,348,484 字节）；需要整分区镜像时加 `--pad-to 25165824`。

### 已验证

- `dtc` 可解析；entry 0/4 各含 1 个 `HMBIRD_OGKI`；`__fixups__/soc` 含 `/fragment@154:target:0`。
- 用 `vendor_boot.img` 里的 Sun 基 DTB + `fdtoverlay` 叠加单 fragment 后，`/soc/oplus,hmbird/version_type` 存在。
- 当前产物：`/storage/emulated/0/Download/111/dtbo_hmbird.img`，sha256 `ac0f0ad2a8b9f3d7b38e2ef4a91a449e333932270a1d955d27e7ef87f74efa65`。

## 手动刷入（用户自行操作，本仓库不执行）

1. 备份当前 dtbo 与 boot/init_boot。
2. 确认 bootloader 已解锁、AVB 验证已关闭。
3. 刷入 `dtbo_hmbird.img`，再刷 AK3 内核包。
4. 开机后 `cat /proc/device-tree/soc/oplus,hmbird/version_type/type` 应输出 `HMBIRD_OGKI`；`/proc/hmbird_sched` 应出现。

## 与参考仓库的差异

- 只保留 realme_GT7pro / RMX5010，源码固定 SHA。
- 用 Ace 6 hmbird 整文件替换，而非 `SCHED_FILE=none` 跳过。
- 不复制 `hmbird_patch.c`（它会把 OGKI 改成 GKI）。
- 不复制 `apply_hmbird.sh` 的 `FORCE_OGKI` 回落；DTBO 是唯一版本声明。

## 致谢与许可

- LZ4KDS 实现、ABI 表、工作流骨架：LMQ00/build_oneplus_sm8750（GPL-3.0）
- 风驰 SCX 补丁：Numbersf/SCHED_PATCH
- 6.6.118 源码：cctv18 / OnePlusOSS
- 脚本与文档：GPL-3.0；内核代码：GPL-2.0
