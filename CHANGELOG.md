# 变更记录

## [0.1.0] - 2026-11-19

首次公开发布（PyPI 分发名 `agentstore-oss`；import 名与 CLI 仍为 `agentstore`）。

### 包含

- **清单与不可变版本**：一次发布一个版本，版本号单调，覆盖写被拒。
- **权限闸**：`with_permission` / `needs_key` / `writes_file` / `pinned_version` 四类声明进权限审查表。
- **计量与分成**：按调用计费，平台抽成 20%；`run.py` quickstart 示例账单 $0.05（平台 $0.01 / 开发者 $0.04），cli demo 合计 $10.00。
- **`scripts/check_readme.py`**：9 例自检，包行数从 `agentstore/**/*.py` 重算（1377 行），示例账单真跑生成的 `run.py` 取数。
- **66 项测试**，零依赖。
