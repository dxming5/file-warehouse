"""
个人文件仓库管理系统 - 本地文件管理工具
- 不移动源文件，仅记录路径
- 手动入库
- 集中存储(SQLite)
"""
import os
import sys
import json
import sqlite3
import subprocess
import platform
import hashlib
import threading
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, request, jsonify, g

# 处理 PyInstaller 打包后的路径
if getattr(sys, 'frozen', False):
    # 打包后：exe 所在目录可写（用于数据库），_MEIPASS 是模板等资源的临时目录
    BASE_DIR = os.path.dirname(sys.executable)
    TEMPLATE_DIR = os.path.join(sys._MEIPASS, 'templates')
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')

DB_PATH = os.path.join(BASE_DIR, 'file_warehouse.db')

app = Flask(__name__, template_folder=TEMPLATE_DIR)

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    """初始化数据库表结构"""
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            color TEXT DEFAULT '#4a90d9',
            icon TEXT DEFAULT '📁',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_ext TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            category_id INTEGER DEFAULT NULL,
            tags TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            rating INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            last_checked TEXT DEFAULT NULL,
            file_exists INTEGER DEFAULT 1,
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_files_category ON files(category_id);
        CREATE INDEX IF NOT EXISTS idx_files_title ON files(title);
        CREATE INDEX IF NOT EXISTS idx_files_tags ON files(tags);
        CREATE INDEX IF NOT EXISTS idx_files_file_exists ON files(file_exists);

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    # 清理旧的默认分类
    old_defaults = ['图书/文档', '代码/项目', '图片/素材', '音频/视频', '压缩包']
    for old_name in old_defaults:
        old_cat = db.execute("SELECT id FROM categories WHERE name = ?", (old_name,)).fetchone()
        if old_cat:
            cat_id = old_cat[0]
            db.execute("UPDATE files SET category_id = NULL WHERE category_id = ?", (cat_id,))
            db.execute("DELETE FROM categories WHERE id = ?", (cat_id,))

    db.commit()
    db.close()

# ---------- 工具函数 ----------

def get_file_info(file_path):
    """获取文件基本信息"""
    try:
        p = Path(file_path)
        if p.exists():
            stat = p.stat()
            return {
                'name': p.name,
                'ext': p.suffix.lower(),
                'size': stat.st_size,
                'size_fmt': format_file_size(stat.st_size),
                'exists': 1,
                'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
            }
    except Exception:
        pass
    return {
        'name': os.path.basename(file_path),
        'ext': Path(file_path).suffix.lower(),
        'size': 0,
        'size_fmt': '0 B',
        'exists': 0,
        'modified': '',
    }

def format_file_size(size_bytes):
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"

def open_file_with_default(file_path):
    """使用系统默认程序打开文件"""
    try:
        if platform.system() == 'Windows':
            os.startfile(file_path)
        elif platform.system() == 'Darwin':
            subprocess.run(['open', file_path])
        else:
            subprocess.run(['xdg-open', file_path])
        return True
    except Exception:
        return False

def open_folder(file_path):
    """在资源管理器中定位文件"""
    try:
        folder = os.path.dirname(file_path)
        if platform.system() == 'Windows':
            subprocess.run(['explorer', '/select,', file_path])
        elif platform.system() == 'Darwin':
            subprocess.run(['open', '-R', file_path])
        else:
            subprocess.run(['xdg-open', folder])
        return True
    except Exception:
        return False

def verify_files(db):
    """批量校验文件是否存在"""
    rows = db.execute("SELECT id, file_path FROM files WHERE file_exists = 1").fetchall()
    to_update = []
    for row in rows:
        if not os.path.exists(row['file_path']):
            to_update.append(row['id'])
    if to_update:
        placeholders = ','.join('?' * len(to_update))
        db.execute(
            f"UPDATE files SET file_exists = 0, last_checked = datetime('now','localtime') WHERE id IN ({placeholders})",
            to_update
        )
    db.commit()
    return len(to_update)

# ---------- API 路由 ----------

@app.route('/')
def index():
    return render_template('index.html')

# --- 文件夹分类辅助 ---

def get_or_create_folder_category(db, file_path):
    """根据文件所在父文件夹自动创建/匹配分类"""
    try:
        parent = os.path.basename(os.path.dirname(file_path))
        if not parent:
            return None
        # 查找是否已有同名分类
        row = db.execute("SELECT id FROM categories WHERE name = ?", (parent,)).fetchone()
        if row:
            return row['id']
        # 自动创建该分类
        colors = ['#4a90d9', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899',
                  '#06b6d4', '#84cc16', '#f97316', '#6366f1', '#14b8a6', '#e11d48']
        idx = (hash(parent) % len(colors) + len(colors)) % len(colors)
        db.execute(
            "INSERT INTO categories(name, color, icon) VALUES(?,?,?)",
            (parent, colors[idx], '📁')
        )
        db.commit()
        return db.execute("SELECT last_insert_rowid()").fetchone()[0]
    except Exception:
        return None

# --- 文件 CRUD ---

@app.route('/api/files', methods=['GET'])
def get_files():
    """获取文件列表，支持搜索、筛选、分页"""
    db = get_db()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    search = request.args.get('search', '').strip()
    category_id = request.args.get('category_id', type=int)
    sort_by = request.args.get('sort_by', 'created_at')
    sort_order = request.args.get('sort_order', 'desc')
    file_exists = request.args.get('file_exists', type=int)

    allowed_sorts = ['title', 'created_at', 'updated_at', 'file_size', 'rating', 'file_name', 'file_ext']
    if sort_by not in allowed_sorts:
        sort_by = 'created_at'
    if sort_order not in ('asc', 'desc'):
        sort_order = 'desc'

    conditions = ["1=1"]
    params = []

    if search:
        conditions.append("(title LIKE ? OR file_name LIKE ? OR file_path LIKE ? OR notes LIKE ? OR tags LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like, like, like])

    if category_id:
        conditions.append("category_id = ?")
        params.append(category_id)

    if file_exists is not None:
        conditions.append("file_exists = ?")
        params.append(file_exists)

    where = " AND ".join(conditions)

    total = db.execute(f"SELECT COUNT(*) FROM files WHERE {where}", params).fetchone()[0]
    offset = (page - 1) * per_page
    rows = db.execute(
        f"SELECT f.*, c.name as category_name, c.color as category_color "
        f"FROM files f LEFT JOIN categories c ON f.category_id = c.id "
        f"WHERE {where} ORDER BY {sort_by} {sort_order} LIMIT ? OFFSET ?",
        params + [per_page, offset]
    ).fetchall()

    files = []
    for r in rows:
        files.append({
            'id': r['id'],
            'title': r['title'],
            'file_path': r['file_path'],
            'file_name': r['file_name'],
            'file_ext': r['file_ext'],
            'file_size': r['file_size'],
            'file_size_fmt': format_file_size(r['file_size']),
            'category_id': r['category_id'],
            'category_name': r['category_name'],
            'category_color': r['category_color'],
            'tags': r['tags'],
            'notes': r['notes'],
            'rating': r['rating'],
            'created_at': r['created_at'],
            'updated_at': r['updated_at'],
            'file_exists': r['file_exists'],
        })

    return jsonify({
        'files': files,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': max(1, (total + per_page - 1) // per_page),
    })

@app.route('/api/files', methods=['POST'])
def add_file():
    """手动添加文件到仓库"""
    db = get_db()
    data = request.get_json()

    file_path = data.get('file_path', '').strip()
    if not file_path:
        return jsonify({'error': '文件路径不能为空'}), 400

    # 规范化路径
    file_path = os.path.normpath(file_path)

    # 检查是否已存在
    existing = db.execute("SELECT id FROM files WHERE file_path = ?", (file_path,)).fetchone()
    if existing:
        return jsonify({'error': '该文件已在仓库中', 'id': existing['id']}), 409

    info = get_file_info(file_path)
    title = data.get('title', '').strip() or info['name']
    category_id = data.get('category_id') or None
    # 如果启用自动文件夹分类且未指定分类
    if data.get('auto_category') and not category_id:
        category_id = get_or_create_folder_category(db, file_path)
    tags = data.get('tags', '').strip()
    notes = data.get('notes', '').strip()
    rating = data.get('rating', 0)

    db.execute("""
        INSERT INTO files (title, file_path, file_name, file_ext, file_size,
                          category_id, tags, notes, rating, file_exists)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (title, file_path, info['name'], info['ext'], info['size'],
          category_id, tags, notes, rating, info['exists']))
    db.commit()

    return jsonify({'message': '添加成功', 'id': db.execute("SELECT last_insert_rowid()").fetchone()[0]}), 201

@app.route('/api/files/batch-add', methods=['POST'])
def batch_add_files():
    """批量添加文件（支持拖拽入库 + 手动选择/自动按文件夹分类）"""
    db = get_db()
    data = request.get_json()
    file_paths = data.get('file_paths', [])
    auto_category = data.get('auto_category', False)
    category_id = data.get('category_id') or None  # 手动选择的文件夹
    base_tags = data.get('tags', '').strip()
    base_notes = data.get('notes', '').strip()

    if not file_paths:
        return jsonify({'error': '请提供文件路径列表'}), 400

    added = 0
    skipped = 0
    errors = []

    for file_path in file_paths:
        file_path = file_path.strip()
        if not file_path:
            continue
        file_path = os.path.normpath(file_path)

        # 检查是否已存在
        existing = db.execute("SELECT id FROM files WHERE file_path = ?", (file_path,)).fetchone()
        if existing:
            skipped += 1
            continue

        info = get_file_info(file_path)
        title = info['name']
        file_category_id = category_id  # 手动选择的优先
        if not file_category_id and auto_category:
            file_category_id = get_or_create_folder_category(db, file_path)

        db.execute("""
            INSERT INTO files (title, file_path, file_name, file_ext, file_size,
                              category_id, tags, notes, rating, file_exists)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, file_path, info['name'], info['ext'], info['size'],
              file_category_id, base_tags, base_notes, 0, info['exists']))
        added += 1

    db.commit()
    return jsonify({
        'message': f'添加完成：成功 {added}，跳过 {skipped}（已存在）',
        'added': added,
        'skipped': skipped,
    })

@app.route('/api/files/<int:file_id>', methods=['PUT'])
def update_file(file_id):
    """更新文件记录"""
    db = get_db()
    data = request.get_json()

    file = db.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if not file:
        return jsonify({'error': '记录不存在'}), 404

    title = data.get('title', file['title']).strip()
    tags = data.get('tags', file['tags']).strip()
    notes = data.get('notes', file['notes']).strip()
    rating = data.get('rating', file['rating'])
    category_id = data.get('category_id', file['category_id'])

    db.execute("""
        UPDATE files SET title=?, tags=?, notes=?, rating=?, category_id=?,
        updated_at=datetime('now','localtime')
        WHERE id=?
    """, (title, tags, notes, rating, category_id, file_id))
    db.commit()

    return jsonify({'message': '更新成功'})

@app.route('/api/files/<int:file_id>', methods=['DELETE'])
def delete_file(file_id):
    """从仓库中移除文件（不删除源文件）"""
    db = get_db()
    file = db.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if not file:
        return jsonify({'error': '记录不存在'}), 404

    db.execute("DELETE FROM files WHERE id = ?", (file_id,))
    db.commit()

    return jsonify({'message': '已从仓库移除（源文件未删除）'})

@app.route('/api/files/batch-delete', methods=['POST'])
def batch_delete_files():
    """批量删除"""
    db = get_db()
    data = request.get_json()
    ids = data.get('ids', [])
    if not ids:
        return jsonify({'error': '请选择要删除的记录'}), 400
    placeholders = ','.join('?' * len(ids))
    db.execute(f"DELETE FROM files WHERE id IN ({placeholders})", ids)
    db.commit()
    return jsonify({'message': f'已移除 {len(ids)} 条记录'})

# --- 文件操作 ---

@app.route('/api/files/<int:file_id>/open', methods=['POST'])
def open_file(file_id):
    """打开文件"""
    db = get_db()
    file = db.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if not file:
        return jsonify({'error': '记录不存在'}), 404

    if not os.path.exists(file['file_path']):
        db.execute("UPDATE files SET file_exists=0 WHERE id=?", (file_id,))
        db.commit()
        return jsonify({'error': '文件不存在，可能已被移动或删除'}), 404

    success = open_file_with_default(file['file_path'])
    if success:
        return jsonify({'message': '已打开'})
    return jsonify({'error': '无法打开文件'}), 500

@app.route('/api/files/<int:file_id>/locate', methods=['POST'])
def locate_file(file_id):
    """在资源管理器中定位"""
    db = get_db()
    file = db.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if not file:
        return jsonify({'error': '记录不存在'}), 404

    success = open_folder(file['file_path'])
    if success:
        return jsonify({'message': '已定位'})
    return jsonify({'error': '无法定位'}), 500

@app.route('/api/files/<int:file_id>/verify', methods=['POST'])
def verify_file(file_id):
    """校验单个文件是否存在"""
    db = get_db()
    file = db.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if not file:
        return jsonify({'error': '记录不存在'}), 404

    exists = 1 if os.path.exists(file['file_path']) else 0
    db.execute("UPDATE files SET file_exists=?, last_checked=datetime('now','localtime') WHERE id=?",
               (exists, file_id))
    db.commit()
    return jsonify({'file_exists': exists})

@app.route('/api/files/verify-all', methods=['POST'])
def verify_all_files():
    """批量校验所有文件"""
    db = get_db()
    count = verify_files(db)
    return jsonify({'message': f'校验完成，{count} 个文件不存在', 'missing': count})

# --- 分类管理 ---

@app.route('/api/categories', methods=['GET'])
def get_categories():
    db = get_db()
    rows = db.execute(
        "SELECT c.*, COUNT(f.id) as file_count FROM categories c "
        "LEFT JOIN files f ON f.category_id = c.id GROUP BY c.id ORDER BY c.id"
    ).fetchall()
    return jsonify([{
        'id': r['id'], 'name': r['name'], 'color': r['color'],
        'icon': r['icon'], 'file_count': r['file_count']
    } for r in rows])

@app.route('/api/categories', methods=['POST'])
def add_category():
    db = get_db()
    data = request.get_json()
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': '分类名不能为空'}), 400
    color = data.get('color', '#6b7280')
    icon = data.get('icon', '📁')
    try:
        db.execute("INSERT INTO categories(name, color, icon) VALUES(?,?,?)", (name, color, icon))
        db.commit()
        return jsonify({'id': db.execute("SELECT last_insert_rowid()").fetchone()[0], 'message': '创建成功'}), 201
    except sqlite3.IntegrityError:
        return jsonify({'error': '分类名已存在'}), 409

@app.route('/api/categories/<int:cat_id>', methods=['PUT'])
def update_category(cat_id):
    db = get_db()
    data = request.get_json()
    name = data.get('name', '').strip()
    color = data.get('color', '#6b7280')
    icon = data.get('icon', '📁')
    db.execute("UPDATE categories SET name=?, color=?, icon=? WHERE id=?",
               (name, color, icon, cat_id))
    db.commit()
    return jsonify({'message': '更新成功'})

@app.route('/api/categories/<int:cat_id>', methods=['DELETE'])
def delete_category(cat_id):
    db = get_db()
    db.execute("UPDATE files SET category_id=NULL WHERE category_id=?", (cat_id,))
    db.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    db.commit()
    return jsonify({'message': '删除成功'})

# --- 统计 ---

@app.route('/api/stats', methods=['GET'])
def get_stats():
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    exists = db.execute("SELECT COUNT(*) FROM files WHERE file_exists=1").fetchone()[0]
    missing = total - exists
    cats = db.execute(
        "SELECT c.name, c.color, COUNT(f.id) as cnt FROM categories c "
        "LEFT JOIN files f ON f.category_id = c.id GROUP BY c.id ORDER BY c.id"
    ).fetchall()
    total_size = db.execute("SELECT COALESCE(SUM(file_size),0) FROM files").fetchone()[0]
    recent = db.execute(
        "SELECT COUNT(*) FROM files WHERE created_at >= datetime('now','localtime','-7 days')"
    ).fetchone()[0]

    return jsonify({
        'total': total,
        'exists': exists,
        'missing': missing,
        'total_size': format_file_size(total_size),
        'recent_7d': recent,
        'categories': [{'name': c['name'], 'color': c['color'], 'count': c['cnt']} for c in cats],
    })

# --- 导出/导入 ---

@app.route('/api/export', methods=['GET'])
def export_data():
    db = get_db()
    files = db.execute(
        "SELECT f.*, c.name as category_name FROM files f "
        "LEFT JOIN categories c ON f.category_id = c.id ORDER BY f.id"
    ).fetchall()
    categories = db.execute("SELECT * FROM categories ORDER BY id").fetchall()

    data = {
        'export_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'version': '1.0',
        'categories': [dict(c) for c in categories],
        'files': [dict(f) for f in files],
    }
    return jsonify(data)

@app.route('/api/import', methods=['POST'])
def import_data():
    db = get_db()
    data = request.get_json()
    imported = {'files': 0, 'categories': 0}

    # 导入分类
    for cat in data.get('categories', []):
        try:
            db.execute(
                "INSERT OR IGNORE INTO categories(id, name, color, icon) VALUES(?,?,?,?)",
                (cat['id'], cat['name'], cat.get('color', '#6b7280'), cat.get('icon', '📁'))
            )
            imported['categories'] += 1
        except Exception:
            pass

    # 导入文件
    for f in data.get('files', []):
        try:
            db.execute("""
                INSERT OR IGNORE INTO files
                (title, file_path, file_name, file_ext, file_size, category_id,
                 tags, notes, rating, created_at, updated_at, file_exists)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                f['title'], f['file_path'], f['file_name'], f.get('file_ext', ''),
                f.get('file_size', 0), f.get('category_id'), f.get('tags', ''),
                f.get('notes', ''), f.get('rating', 0),
                f.get('created_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                f.get('updated_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                f.get('file_exists', 1),
            ))
            imported['files'] += 1
        except Exception:
            pass

    db.commit()
    return jsonify({'message': f"导入完成：{imported['files']} 个文件，{imported['categories']} 个分类", 'imported': imported})


# --- 原生文件/文件夹选择器（通过 tkinter 获取真实路径）---

@app.route('/api/browse-files', methods=['POST'])
def browse_files():
    """打开原生文件选择对话框（多选），返回选中文件的真实路径"""
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    file_paths = filedialog.askopenfilenames(title='选择要添加的文件')
    root.destroy()
    result = []
    for fp in file_paths:
        info = get_file_info(fp)
        result.append({'path': fp, 'name': info['name'], 'size_fmt': info['size_fmt'], 'ext': info['ext']})
    return jsonify({'files': result})





if __name__ == '__main__':
    import time
    import webview

    # 初始化数据库
    init_db()

    # 在后台线程启动 Flask
    def run_flask():
        app.run(host='127.0.0.1', port=5000, debug=False)

    t = threading.Thread(target=run_flask, daemon=True)
    t.start()

    # 等待 Flask 就绪
    time.sleep(0.5)

    # 创建原生桌面窗口
    webview.create_window(
        title='个人文件仓库管理系统 - dxm',
        url='http://127.0.0.1:5000',
        width=1280,
        height=800,
        min_size=(900, 600),
        text_select=True,
    )
    webview.start()
