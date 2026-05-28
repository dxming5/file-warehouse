# 个人文件仓库管理系统

一个**不碰源文件、手工入库、集中管理**的本地文件管理工具。

> 你的文件散落在硬盘各处？这个工具帮你把它们"登记在册"，随时查找、打开、定位——不移动、不复制、不改动任何源文件。

---

## 快速开始

### 环境要求

- Python 3.8+
- Flask >= 3.0 + pywebview >= 5.0

### 启动

**方式一：一键启动（推荐）**

Windows 用户直接双击 `启动.pyw`，无命令行窗口，自动安装依赖。

**方式二：命令行**

```bash
# 1. 安装依赖
pip install flask pywebview

# 2. 运行
python app.py
```

应用会自动弹出原生桌面窗口。

> 需要查看后台日志时，可使用 `启动.bat`（会显示命令行窗口）。

### 打包为 EXE

双击 `打包.bat`，完成后在 `dist\个人文件仓库.exe` 处得到单个可执行文件，可拷贝至任意目录运行。

---

## 项目结构

```
file-warehouse/
├── app.py                 # Flask 后端 + pywebview 桌面窗口
├── file_warehouse.db      # SQLite 数据库（自动生成）
├── requirements.txt       # Python 依赖
├── 启动.pyw               # 一键启动（无控制台，推荐）
├── 启动.bat               # 带控制台启动（调试用）
├── 打包.bat               # PyInstaller 打包脚本
├── 个人仓库需求.md         # 需求文档
├── README.md              # 本文件
├── templates/
│   └── index.html         # 前端单页面（原生 JS，无框架）
```

---

## 功能概览

| 模块 | 功能 |
|------|------|
| 📥 文件管理 | 添加、编辑、删除、批量操作、打开/定位源文件 |
| 📁 文件夹分类 | 自定义分类（新建/编辑/删除），按分类筛选 |
| 🔍 搜索排序 | 关键词搜索 + 多种排序方式 |
| ✅ 文件校验 | 检测源文件是否仍然存在 |
| 📤 数据管理 | JSON 导出/导入，方便备份迁移 |
| 📊 统计面板 | 文件总数、总大小、近期新增 |

---

## API 接口

### 文件

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/files` | 获取文件列表（分页、搜索、排序、筛选） |
| POST | `/api/files` | 添加单个文件 |
| POST | `/api/files/batch-add` | 批量添加文件 |
| PUT | `/api/files/<id>` | 更新文件记录 |
| DELETE | `/api/files/<id>` | 移除文件记录 |
| POST | `/api/files/batch-delete` | 批量移除 |
| POST | `/api/files/<id>/open` | 打开源文件 |
| POST | `/api/files/<id>/locate` | 在资源管理器中定位 |
| POST | `/api/files/<id>/verify` | 校验单个文件 |
| POST | `/api/files/verify-all` | 批量校验所有文件 |

### 分类

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/categories` | 获取分类列表 |
| POST | `/api/categories` | 新建分类 |
| PUT | `/api/categories/<id>` | 更新分类 |
| DELETE | `/api/categories/<id>` | 删除分类 |

### 其他

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/stats` | 获取统计数据 |
| GET | `/api/export` | 导出 JSON |
| POST | `/api/import` | 导入 JSON |
| POST | `/api/browse-files` | 打开原生文件选择对话框 |

---

## 设计说明

- **零侵入**：不修改、不移动源文件，仅记录路径
- **纯本地**：无需网络连接，数据完全本地存储
- **SQLite**：单文件数据库，备份只需复制 `file_warehouse.db`
- **无框架前端**：原生 HTML/CSS/JS，加载快、无依赖
- **桌面原生**：pywebview 创建独立窗口，无需浏览器
- **单文件分发**：支持 PyInstaller 打包为 exe，双击即用
- **原生文件选择**：通过 tkinter 获取文件真实绝对路径
