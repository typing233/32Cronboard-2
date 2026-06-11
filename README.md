# Cronboard - 终端 Cron 任务管理面板

基于 [Textual](https://textual.textualize.io/) 框架的终端 TUI 工具，用于管理本地用户 crontab 的全生命周期。

## 功能特性

### 核心功能
- **无损解析**: 保留 crontab 中的注释、环境变量、空行和未知格式行
- **任务展示**: 命令、调度表达式、启用状态、上次/下次触发时间、是否正在运行
- **实时校验**: 编辑时实时校验 Cron 表达式并翻译为中文可读描述
- **CRUD**: 新建、编辑、删除 Cron 任务
- **暂停/恢复**: 单个或批量启停任务
- **搜索过滤**: 按命令或表达式实时过滤
- **Dry-Run Diff**: 写入前预览变更差异
- **导入/导出**: 导出当前 crontab 或从文件导入
- **撤销/重做**: 完整的 undo/redo 支持

### 安全特性
- **文件锁**: `fcntl.flock` 防止并发写入
- **原子替换**: 通过临时文件 + `crontab` 命令原子性写入
- **自动备份**: 每次写入前自动备份，支持回滚
- **并发检测**: 检测外部修改防止覆盖
- **权限处理**: 优雅处理权限不足的情况
- **终端自适应**: Textual 框架自动处理终端尺寸变化

### 设计边界
- 仅管理本地用户 crontab
- 不做远程 SSH 管理
- 不做日志分析

## 安装

```bash
# 安装依赖
pip install -e ".[dev]"

# 或手动安装
pip install textual croniter
```

## 运行

```bash
# 作为模块
python -m cronboard.app

# 或安装后使用入口点
cronboard
```

## 快捷键

| 按键 | 功能 |
|------|------|
| `N` | 新建任务 |
| `E` | 编辑任务 |
| `D` | 删除任务 |
| `P` | 暂停/恢复 |
| `B` | 批量启停 |
| `Space` | 选择/取消选择 |
| `A` | 全选 |
| `/` | 搜索 |
| `R` | 刷新 |
| `Ctrl+Z` | 撤销 |
| `Ctrl+Y` | 重做 |
| `Ctrl+D` | Diff 预览 |
| `Ctrl+E` | 导出 |
| `Ctrl+I` | 导入 |
| `Q` | 退出 |

## 测试

```bash
pytest tests/ -v
```

## 项目结构

```
cronboard/
├── __init__.py          # 包初始化
├── app.py               # Textual 主应用
├── models.py            # 数据模型
├── parser.py            # 无损 crontab 解析器
├── cron_expr.py         # Cron 表达式校验与翻译
├── manager.py           # crontab 管理器（锁、原子写、备份）
└── widgets/
    ├── __init__.py
    ├── job_table.py     # 任务列表表格组件
    └── edit_dialog.py   # 编辑对话框
tests/
├── __init__.py
├── test_parser.py       # 解析器测试
├── test_cron_expr.py    # 表达式校验测试
├── test_manager.py      # 管理器测试
└── test_models.py       # 模型测试
```

## 技术实现

### 无损解析
解析器逐行处理 crontab，识别五种行类型（CRON_JOB、COMMENT、ENV_VAR、BLANK、UNKNOWN），
每行保留原始文本，序列化时精确还原。禁用的任务通过 `#` 前缀表示，解析器能正确识别
「注释掉的 cron 行」和「普通注释」。

### 原子写入流程
1. 获取进程级文件锁 (`fcntl.flock`)
2. 检测外部并发修改（对比当前内容与上次已知内容）
3. 创建带时间戳的备份
4. 写入临时文件
5. 通过 `crontab <tmpfile>` 原子安装
6. 清理临时文件
7. 释放锁

### Cron 表达式翻译
支持标准五字段表达式和 `@special` 特殊调度，翻译为中文可读描述：
- `*/5 * * * *` → "每5分钟"
- `0 2 * * *` → "2:00"
- `0 9 * * 1-5` → "Monday到Friday 9:00"
- `@daily` → "每天 00:00"
