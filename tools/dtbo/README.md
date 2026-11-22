# DTBO HMBIRD_OGKI 注入工具

`patch_hmbird_dtbo.py` 把版本节点注入 DTBO 里 `oplus,project-id = 0x6018` 的 overlay。

## 本机 DTBO 结构

| entry | oplus,project-id | 说明 |
|---|---|---|
| 0 | 0x6018 | RMX5010（本机），会被修改 |
| 1 | 0x605f | 其他项目，不动 |
| 2 | 0x605e | 其他项目，不动 |
| 3 | 0x605e | 其他项目，不动 |
| 4 | 0x6018 | RMX5010（本机），会被修改 |
| 5 | 0x605f | 其他项目，不动 |

每个 entry 是一个 154 个 fragment 的 overlay，其中 41 个 `target = <&soc>`。

## 用法

```bash
python3 tools/dtbo/patch_hmbird_dtbo.py \
  --input  /storage/emulated/0/Download/111/dtbo.img \
  --output /storage/emulated/0/Download/111/dtbo_hmbird.img \
  --project-id 0x6018 \
  --type HMBIRD_OGKI
```

可选：

- `--fragment N`：强制 fragment 编号；默认取现有最大编号 +1。
- `--pad-to N`：补零到 N 字节，给要求整分区镜像的刷写工具。
- `--dtc PATH`：指定 dtc。

## 算法

1. 大端解析 DTBO header（magic/header_size/entry_size/entry_count/entries_offset）。
2. 解析每个 entry 的 FDT root 属性，取 `oplus,project-id`。
3. 目标 entry 用 `dtc` 反编译；先做一次未修改的 round-trip，要求 DTS 0 diff。
4. 在根节点收尾前插入：

   ```dts
   fragment@N+1 {
       target = <&soc>;
       __overlay__ {
           oplus,hmbird {
               version_type {
                   type = "HMBIRD_OGKI";
               };
           };
       };
   };
   ```

   用 `target = <&soc>` 而不是 `target-path`，与现有 41 个 fragment 保持一致；dtc 会把 `/fragment@N+1:target:0` 并进 `__fixups__/soc`。
5. `dtc -@` 重编译，再反编译断言：`HMBIRD_OGKI` 恰 1 处、fragment 集合只多一个新编号、`__fixups__/soc` 含新 fixup。
6. 重排 header + table + payload，更新 size/offset/total_size；原子写入输出。

## 幂等与安全

- 目标 entry 已含 `HMBIRD_OGKI` 或 `oplus,hmbird`：原样保留，输出仍可生成。
- 没有匹配的 project-id：退出码 2，不创建输出。
- 非目标 entry：逐字节比对，必须与输入相同。
- 原文件永不修改；输入输出相同路径会拒绝。

## AVB

原 dtbo 在 0x703000 有 AVB0 footer。改数据后签名失效，本工具不伪造、不重签。刷入前必须解锁并关闭验证，并备份原 dtbo。

## 验证

```bash
strings -a dtbo_hmbird.img | grep -c HMBIRD_OGKI   # 期望 2
python3 tools/dtbo/patch_hmbird_dtbo.py --input dtbo_hmbird.img --output tmp/again.img  # 幂等
```

也可以从 `vendor_boot.img` 取出 Sun 基 DTB，用 `fdtoverlay` 叠加单个 `target=<&soc>` fragment，反编译后应看到 `/soc/oplus,hmbird/version_type`。
