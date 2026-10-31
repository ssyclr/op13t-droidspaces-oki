# 一加 13T Droidspaces OKI 内核

为一加 13T 国行（PKX110，ColorOS 17）编译开启了 [Droidspaces](https://github.com/ravindu644/Droidspaces-OSS) 所需选项的内核，kABI 与原厂一致。只替换 boot 分区里的内核，root 继续由 init_boot 里的 KernelSU-Next LKM 提供。

| 项 | 值 |
|---|---|
| 原厂内核 | `6.6.118-android15-8-g9bc34d5b0c79-abogki537459655-4k` |
| 源码 | `OnePlusOSS/android_kernel_common_oneplus_sm8750` @ `4d611c32bedc`（16.0.9.400，原厂构建的提交未公开） |
| 工具链 | clang r510928 |

**状态：** 正在验证公开源码能否复现原厂 ABI。尚未产出可刷机的内核，请勿刷入。

方法模板是 [gt8pro-droidspaces-gki](https://github.com/ssyclr/gt8pro-droidspaces-gki)。
