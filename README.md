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
├── icon.ico               # 应用图标
├── 启动.pyw               # 一键启动（无控制台，推荐）
├── 启动.bat               # 带控制台启动（调试用）
├── 打包.bat               # PyInstaller 打包脚本
├── README.md              # 使用说明
├── 数据模型设计策略.md      # 数据模型设计文档
└── templates/
    └── index.html         # 前端单页面（原生 JS，无框架）
```

---

## 功能概览

| 模块 | 功能 |
|------|------|
| 📥 文件管理 | 添加、编辑、删除、打开/定位源文件 |
| 📁 分类管理 | 自定义分类（新建/编辑/删除），支持无限层级子分类，按分类筛选 |
| 🔍 搜索排序 | 关键词搜索 + 按标题/出版时间/格式/作者/阅读状态排序（点击表头切换） |
| ⭐ 收藏标记 | 文件收藏/取消收藏，快速标记重要文件 |
| 📖 阅读状态 | 未阅读/在阅读/已阅读，自定义下拉选择，与作者下拉互斥 |
| 🖱️ 点击高亮 | 点击文件项点亮标记，双击打开源文件，便于浏览定位 |
| 👤 元数据 | 支持作者（多值分号分隔，自定义下拉）、出版时间等扩展字段 |
| ✅ 文件校验 | 检测源文件是否仍然存在，丢失文件提醒 |
| 📊 统计面板 | 文件总数、现存/丢失统计、近期新增 |
| 🔄 拖拽排序 | 侧边栏分类支持拖拽移动和排序 |
| 📋 批量操作 | 批量添加文件、批量删除 |

---

## API 接口

### 文件

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/files` | 获取文件列表（分页、搜索、排序、筛选） |
| POST | `/api/files` | 添加单个文件 |
| POST | `/api/files/batch-add` | 批量添加文件 |
| PUT | `/api/files/<id>` | 更新文件记录 |
| DELETE | `/api/files/<id>` | 移除文件记录（不删除源文件） |
| POST | `/api/files/batch-delete` | 批量移除文件记录 |
| POST | `/api/files/<id>/open` | 打开源文件 |
| POST | `/api/files/<id>/locate` | 在资源管理器中定位 |
| POST | `/api/files/<id>/verify` | 校验单个文件 |
| POST | `/api/files/verify-all` | 批量校验所有文件 |
| POST | `/api/files/<id>/favorite` | 切换收藏状态 |
| PUT | `/api/files/<id>/read-status` | 更新阅读状态 |

### 分类

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/categories` | 获取分类列表（含文件计数） |
| POST | `/api/categories` | 新建分类（支持指定父分类） |
| PUT | `/api/categories/<id>` | 更新分类（防循环引用、防同级重名） |
| DELETE | `/api/categories/<id>` | 删除分类及所有子分类（递归删除关联文件） |
| PUT | `/api/categories/<id>/move` | 拖拽移动/排序分类（before/after/into） |

### 其他

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/stats` | 获取统计数据 |
| POST | `/api/browse-files` | 打开原生文件选择对话框 |

---

## 数据库字段

files 表核心字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| title | TEXT | 文件标题 |
| file_path | TEXT | 文件路径（相对路径存储） |
| file_name | TEXT | 文件名 |
| file_ext | TEXT | 文件后缀 |
| file_size | INTEGER | 文件大小（字节） |
| category_id | INTEGER | 所属分类（外键） |
| author | TEXT | 作者 |
| year | TEXT | 出版时间 |
| read_status | TEXT | 阅读状态：unread / reading / read |
| favorite | INTEGER | 收藏标记：0 或 1 |
| file_exists | INTEGER | 源文件是否仍存在 |

---

## 设计说明

- **零侵入**：不修改、不移动源文件，仅记录路径
- **纯本地**：无需网络连接，数据完全本地存储
- **SQLite**：单文件数据库（WAL 模式），备份只需复制 `file_warehouse.db`
- **无框架前端**：原生 HTML/CSS/JS，加载快、无依赖
- **桌面原生**：pywebview 创建独立窗口，无需浏览器
- **单文件分发**：支持 PyInstaller 打包为 exe，双击即用
- **原生文件选择**：通过 tkinter 获取文件真实绝对路径
- **相对路径存储**：文件路径以相对路径入库，方便整体迁移
- **列宽自适应**：表格各列宽度根据窗口大小通过 CSS grid 弹性自适应
- **自定义下拉**：作者、阅读状态使用自定义下拉组件，风格统一且不依赖原生控件
