"""
个人文件仓库管理系统 - 本地文件管理工具
- 不移动源文件，仅记录路径
- 手动入库
- 集中存储(SQLite)
"""
import os
import sys
import sqlite3
import subprocess
import platform
import threading
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, g
import pypinyin
from natsort import natsort_keygen, ns

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
            parent_id INTEGER DEFAULT NULL,
            color TEXT DEFAULT '#4a90d9',
            icon TEXT DEFAULT '📁',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (parent_id) REFERENCES categories(id) ON DELETE SET NULL
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
            rating INTEGER DEFAULT 0,
            author TEXT DEFAULT '',
            year TEXT DEFAULT '',
            read_status TEXT DEFAULT 'unread',
            favorite INTEGER DEFAULT 0,
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
        CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id);
    """)
    # 确保 year 列存在（兼容已有数据库）
    try:
        db.execute("ALTER TABLE files ADD COLUMN year TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    # 确保 parent_id 列存在（兼容已有数据库）
    try:
        db.execute("ALTER TABLE categories ADD COLUMN parent_id INTEGER DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    # 确保 sort_order 列存在（兼容已有数据库）
    try:
        db.execute("ALTER TABLE categories ADD COLUMN sort_order INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    # 确保已有数据的 sort_order 用 id 填充（维持旧排序）
    db.execute("UPDATE categories SET sort_order = id WHERE sort_order = 0")
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
                'stem': p.stem,
                'ext': p.suffix.lower(),
                'size': stat.st_size,
                'exists': 1,
                'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
            }
    except Exception:
        pass
    p = Path(file_path)
    return {
        'name': p.name,
        'stem': p.stem,
        'ext': p.suffix.lower(),
        'size': 0,
        'exists': 0,
        'modified': '',
    }

def to_relative_path(abs_path):
    """将绝对路径转为相对于程序运行目录的路径"""
    try:
        return os.path.relpath(abs_path, BASE_DIR)
    except ValueError:
        # 跨驱动器时无法计算相对路径，返回原路径
        return abs_path

def to_absolute_path(rel_path):
    """将相对路径还原为绝对路径"""
    if os.path.isabs(rel_path):
        return rel_path
    return os.path.normpath(os.path.join(BASE_DIR, rel_path))

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
        if not os.path.exists(to_absolute_path(row['file_path'])):
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

# --- 分类辅助 ---

def get_or_create_folder_category(db, file_path):
    """根据文件所在父目录自动创建/匹配分类"""
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
        max_order = db.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM categories WHERE parent_id IS NULL"
        ).fetchone()[0]
        db.execute(
            "INSERT INTO categories(name, color, icon, sort_order) VALUES(?,?,?,?)",
            (parent, colors[idx], '📁', max_order + 1)
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
    sort_by = request.args.get('sort_by', 'title')
    sort_order = request.args.get('sort_order', 'asc')
    file_exists = request.args.get('file_exists', type=int)
    favorite = request.args.get('favorite', type=int)

    allowed_sorts = ['title', 'created_at', 'updated_at', 'file_name', 'file_ext', 'author', 'year', 'read_status']
    if sort_by not in allowed_sorts:
        sort_by = 'created_at'
    if sort_order not in ('asc', 'desc'):
        sort_order = 'desc'

    conditions = ["1=1"]
    params = []

    if search:
        conditions.append("(title LIKE ? OR file_name LIKE ? OR file_path LIKE ? OR tags LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if category_id:
        conditions.append("category_id = ?")
        params.append(category_id)

    if file_exists is not None:
        conditions.append("file_exists = ?")
        params.append(file_exists)

    if favorite is not None:
        conditions.append("favorite = ?")
        params.append(favorite)

    if request.args.get('uncategorized', type=int) == 1:
        conditions.append("category_id IS NULL")

    where = " AND ".join(conditions)

    offset = (page - 1) * per_page

    if sort_by == 'title':
        # 模拟 Windows 排序：英文/数字在前 → 中文在后（中文转拼音后自然排序）
        all_rows = db.execute(
            f"SELECT f.*, c.name as category_name, c.color as category_color "
            f"FROM files f LEFT JOIN categories c ON f.category_id = c.id "
            f"WHERE {where}",
            params
        ).fetchall()

        def _title_sort_key(r):
            t = (r['title'] or '')
            try:
                pinyin_str = ''.join(pypinyin.lazy_pinyin(t))
            except Exception:
                pinyin_str = t
            # 以中文开头 → 排到后面；英文/数字开头 → 排前面
            is_cjk_start = 1 if (t and '\u4e00' <= t[0] <= '\u9fff') else 0
            return _natsort_key((is_cjk_start, pinyin_str))

        _natsort_key = natsort_keygen(alg=ns.IGNORECASE)
        all_rows = sorted(all_rows, key=_title_sort_key, reverse=(sort_order == 'desc'))
        total = len(all_rows)
        rows = all_rows[offset:offset + per_page]
    else:
        total = db.execute(f"SELECT COUNT(*) FROM files WHERE {where}", params).fetchone()[0]
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
            'category_id': r['category_id'],
            'category_name': r['category_name'],
            'category_color': r['category_color'],
            'tags': r['tags'],
            'created_at': r['created_at'],
            'updated_at': r['updated_at'],
            'file_exists': r['file_exists'],
            'favorite': r['favorite'],
            'author': r['author'],
            'year': r['year'],
            'read_status': r['read_status'],
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

    # 规范化路径（绝对路径用于获取文件信息）
    abs_path = os.path.normpath(file_path)
    # 转为相对路径存储
    rel_path = to_relative_path(abs_path)

    # 检查是否已存在
    existing = db.execute("SELECT id FROM files WHERE file_path = ?", (rel_path,)).fetchone()
    if existing:
        return jsonify({'error': '该文件已在仓库中', 'id': existing['id']}), 409

    info = get_file_info(abs_path)
    title = data.get('title', '').strip() or info['stem']
    category_id = data.get('category_id') or None
    # 如果启用自动分类且未指定分类
    if data.get('auto_category') and not category_id:
        category_id = get_or_create_folder_category(db, abs_path)
    tags = data.get('tags', '').strip()
    author = data.get('author', '').strip()
    year = data.get('year', '').strip()

    db.execute("""
        INSERT INTO files (title, file_path, file_name, file_ext, file_size,
                          category_id, tags, author, year, file_exists, favorite)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (title, rel_path, info['name'], info['ext'], info['size'],
          category_id, tags, author, year, info['exists'], 0))
    db.commit()

    return jsonify({'message': '添加成功', 'id': db.execute("SELECT last_insert_rowid()").fetchone()[0]}), 201

@app.route('/api/files/batch-add', methods=['POST'])
def batch_add_files():
    """批量添加文件（支持拖拽入库 + 手动选择/自动按分类归类）"""
    db = get_db()
    data = request.get_json()
    file_paths = data.get('file_paths', [])
    auto_category = data.get('auto_category', False)
    category_id = data.get('category_id') or None  # 手动选择的分类
    base_tags = data.get('tags', '').strip()
    base_author = data.get('author', '').strip()
    base_year = data.get('year', '').strip()

    if not file_paths:
        return jsonify({'error': '请提供文件路径列表'}), 400

    added = 0
    skipped = 0
    errors = []

    for file_path in file_paths:
        file_path = file_path.strip()
        if not file_path:
            continue
        abs_path = os.path.normpath(file_path)
        rel_path = to_relative_path(abs_path)

        # 检查是否已存在
        existing = db.execute("SELECT id FROM files WHERE file_path = ?", (rel_path,)).fetchone()
        if existing:
            skipped += 1
            continue

        info = get_file_info(abs_path)
        title = info['stem']
        file_category_id = category_id  # 手动选择的优先
        if not file_category_id and auto_category:
            file_category_id = get_or_create_folder_category(db, abs_path)

        db.execute("""
            INSERT INTO files (title, file_path, file_name, file_ext, file_size,
                              category_id, tags, author, year, file_exists, favorite)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, rel_path, info['name'], info['ext'], info['size'],
              file_category_id, base_tags, base_author, base_year, info['exists'], 0))
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
    author = data.get('author', file['author']).strip()
    year = data.get('year', file['year']).strip()
    category_id = data.get('category_id', file['category_id'])

    # 支持修改文件路径（与添加逻辑保持一致的规范化处理）
    new_path = data.get('file_path', file['file_path']).strip()
    if new_path and new_path != file['file_path']:
        abs_path = os.path.normpath(new_path)
        rel_path = to_relative_path(abs_path)
        info = get_file_info(abs_path)
        db.execute("""
            UPDATE files SET title=?, file_path=?, file_name=?, file_ext=?, file_size=?,
            tags=?, author=?, year=?, category_id=?, file_exists=?,
            updated_at=datetime('now','localtime')
            WHERE id=?
        """, (title, rel_path, info['name'], info['ext'], info['size'],
              tags, author, year, category_id, info['exists'], file_id))
    else:
        db.execute("""
            UPDATE files SET title=?, tags=?, author=?, year=?, category_id=?,
            updated_at=datetime('now','localtime')
            WHERE id=?
        """, (title, tags, author, year, category_id, file_id))
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

@app.route('/api/files/<int:file_id>/read-status', methods=['PUT'])
def update_read_status(file_id):
    """更新阅读状态"""
    db = get_db()
    file = db.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if not file:
        return jsonify({'error': '记录不存在'}), 404

    data = request.get_json()
    status = data.get('read_status', 'unread')
    if status not in ('unread', 'reading', 'read'):
        return jsonify({'error': '无效状态'}), 400

    db.execute("UPDATE files SET read_status=?, updated_at=datetime('now','localtime') WHERE id=?", (status, file_id))
    db.commit()
    return jsonify({'message': '更新成功'})

# --- 文件操作 ---

@app.route('/api/files/<int:file_id>/open', methods=['POST'])
def open_file(file_id):
    """打开文件"""
    db = get_db()
    file = db.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if not file:
        return jsonify({'error': '记录不存在'}), 404

    abs_path = to_absolute_path(file['file_path'])
    if not os.path.exists(abs_path):
        db.execute("UPDATE files SET file_exists=0 WHERE id=?", (file_id,))
        db.commit()
        return jsonify({'error': '文件不存在，可能已被移动或删除'}), 404

    success = open_file_with_default(abs_path)
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

    abs_path = to_absolute_path(file['file_path'])
    success = open_folder(abs_path)
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

    abs_path = to_absolute_path(file['file_path'])
    exists = 1 if os.path.exists(abs_path) else 0
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

@app.route('/api/files/<int:file_id>/favorite', methods=['POST'])
def toggle_favorite(file_id):
    """切换文件收藏状态"""
    db = get_db()
    file = db.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if not file:
        return jsonify({'error': '记录不存在'}), 404

    new_val = 0 if file['favorite'] else 1
    db.execute("UPDATE files SET favorite = ?, updated_at = datetime('now','localtime') WHERE id = ?",
               (new_val, file_id))
    db.commit()
    return jsonify({'favorite': new_val})

# --- 分类管理 ---

@app.route('/api/categories', methods=['GET'])
def get_categories():
    db = get_db()
    rows = db.execute(
        "SELECT c.*, COUNT(f.id) as file_count FROM categories c "
        "LEFT JOIN files f ON f.category_id = c.id GROUP BY c.id ORDER BY c.parent_id, c.sort_order, c.id"
    ).fetchall()
    return jsonify([{
        'id': r['id'], 'name': r['name'], 'parent_id': r['parent_id'], 'color': r['color'],
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
    parent_id = data.get('parent_id')
    
    # 验证父分类是否存在
    if parent_id:
        parent = db.execute("SELECT id FROM categories WHERE id = ?", (parent_id,)).fetchone()
        if not parent:
            return jsonify({'error': '父分类不存在'}), 404
    
    try:
        # 计算 sort_order：同级最大值 + 1
        if parent_id:
            max_order = db.execute(
                "SELECT COALESCE(MAX(sort_order), -1) FROM categories WHERE parent_id = ?", (parent_id,)
            ).fetchone()[0]
        else:
            max_order = db.execute(
                "SELECT COALESCE(MAX(sort_order), -1) FROM categories WHERE parent_id IS NULL"
            ).fetchone()[0]
        sort_order = max_order + 1
        
        db.execute("INSERT INTO categories(name, parent_id, color, icon, sort_order) VALUES(?,?,?,?,?)", 
                   (name, parent_id, color, icon, sort_order))
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
    parent_id = data.get('parent_id')
    
    # 检查同级分类下是否存在同名分类
    if parent_id is not None:
        sibling = db.execute(
            "SELECT id FROM categories WHERE name = ? AND parent_id = ? AND id != ?",
            (name, parent_id, cat_id)
        ).fetchone()
    else:
        sibling = db.execute(
            "SELECT id FROM categories WHERE name = ? AND parent_id IS NULL AND id != ?",
            (name, cat_id)
        ).fetchone()
    
    if sibling:
        return jsonify({'error': '同级分类下已存在同名分类，请修改名称'}), 409
    
    # 防循环引用检查
    if parent_id and parent_id != cat_id:
        if _is_descendant(db, cat_id, parent_id):
            return jsonify({'error': '不能将分类设为自己或子分类的子分类'}), 400
    
    db.execute("UPDATE categories SET name=?, parent_id=?, color=?, icon=? WHERE id=?",
               (name, parent_id, color, icon, cat_id))
    db.commit()
    return jsonify({'message': '更新成功'})

def _get_all_descendants(db, cat_id):
    """递归获取所有子分类ID"""
    descendants = []
    children = db.execute("SELECT id FROM categories WHERE parent_id = ?", (cat_id,)).fetchall()
    for child in children:
        descendants.append(child['id'])
        descendants.extend(_get_all_descendants(db, child['id']))
    return descendants

def _is_descendant(db, ancestor_id, target_id):
    """检查 target_id 是否是 ancestor_id 的后代"""
    if ancestor_id == target_id:
        return True
    descendants = _get_all_descendants(db, ancestor_id)
    return target_id in descendants

@app.route('/api/categories/<int:cat_id>', methods=['DELETE'])
def delete_category(cat_id):
    db = get_db()
    
    # 获取所有子分类ID
    all_descendants = _get_all_descendants(db, cat_id)
    all_cat_ids = [cat_id] + all_descendants
    
    # 删除这些分类下的所有文件
    if all_cat_ids:
        placeholders = ','.join('?' * len(all_cat_ids))
        db.execute(f"DELETE FROM files WHERE category_id IN ({placeholders})", all_cat_ids)
    
    # 删除分类本身及所有子分类
    db.execute(f"DELETE FROM categories WHERE id IN ({placeholders})", all_cat_ids)
    db.commit()
    
    deleted_cats = len(all_cat_ids)
    return jsonify({'message': f'已删除 {deleted_cats} 个分类及其所有文件'})

# --- 分类移动 / 排序 ---

@app.route('/api/categories/<int:cat_id>/move', methods=['PUT'])
def move_category(cat_id):
    """拖动移动分类：跨父级移动 或 同级排序
    请求体: { target_id: int, position: 'before'|'after'|'into' }
      - target_id: 拖动到哪个分类上
      - position: before=插到目标前面, after=插到目标后面, into=移入目标作为子分类
    """
    db = get_db()
    data = request.get_json()
    target_id = data.get('target_id')
    position = data.get('position', 'into')
    
    if position not in ('before', 'after', 'into'):
        return jsonify({'error': '无效的 position'}), 400
    
    # 获取当前分类
    cat = db.execute("SELECT * FROM categories WHERE id = ?", (cat_id,)).fetchone()
    if not cat:
        return jsonify({'error': '分类不存在'}), 404
    
    # 获取目标分类
    target = db.execute("SELECT * FROM categories WHERE id = ?", (target_id,)).fetchone()
    if not target:
        return jsonify({'error': '目标分类不存在'}), 404
    
    # 防循环引用
    if position == 'into':
        if target_id == cat_id or _is_descendant(db, cat_id, target_id):
            return jsonify({'error': '不能将分类移到自己的子分类下'}), 400
    elif target_id == cat_id:
        return jsonify({'error': '不能移到自身'}), 400
    
    # 计算新的 parent_id 和 after_id
    if position == 'into':
        new_parent_id = target_id
        # 插入到目标子分类末尾
        last_child = db.execute(
            "SELECT id FROM categories WHERE parent_id = ? ORDER BY sort_order DESC LIMIT 1",
            (target_id,)
        ).fetchone()
        new_after_id = last_child['id'] if last_child else None
    elif position == 'before':
        new_parent_id = target['parent_id']
        # 找目标的前一个兄弟
        if target['parent_id'] is not None:
            prev = db.execute(
                "SELECT id FROM categories WHERE parent_id = ? AND sort_order < ? ORDER BY sort_order DESC LIMIT 1",
                (target['parent_id'], target['sort_order'])
            ).fetchone()
        else:
            prev = db.execute(
                "SELECT id FROM categories WHERE parent_id IS NULL AND sort_order < ? ORDER BY sort_order DESC LIMIT 1",
                (target['sort_order'],)
            ).fetchone()
        new_after_id = prev['id'] if prev else None
    else:  # 'after'
        new_parent_id = target['parent_id']
        new_after_id = target_id
    
    # 防循环引用（跨父级移动）
    if new_parent_id is not None:
        if new_parent_id == cat_id or _is_descendant(db, cat_id, new_parent_id):
            return jsonify({'error': '不能将分类移到自己的子分类下'}), 400
    
    old_parent_id = cat['parent_id']
    
    # 如果位置没变，直接返回
    if new_parent_id == old_parent_id and new_after_id is None and position == 'into':
        pass  # 可能需要插入到列表末尾，继续处理
    if new_parent_id == old_parent_id and new_after_id == cat_id:
        return jsonify({'message': '位置未变化'})
    
    # 获取目标父级下所有兄弟（排除当前分类本身）
    if new_parent_id is not None:
        siblings = db.execute(
            "SELECT id FROM categories WHERE parent_id = ? AND id != ? ORDER BY sort_order",
            (new_parent_id, cat_id)
        ).fetchall()
    else:
        siblings = db.execute(
            "SELECT id FROM categories WHERE parent_id IS NULL AND id != ? ORDER BY sort_order",
            (cat_id,)
        ).fetchall()
    
    # 构建新的顺序列表
    new_order_ids = []
    inserted = False
    
    if new_after_id is None:
        # 插入最前面
        new_order_ids.append(cat_id)
        for s in siblings:
            new_order_ids.append(s['id'])
    else:
        for s in siblings:
            new_order_ids.append(s['id'])
            if s['id'] == new_after_id:
                new_order_ids.append(cat_id)
                inserted = True
        if not inserted:
            new_order_ids.append(cat_id)
    
    # 更新 parent_id
    if new_parent_id != old_parent_id:
        db.execute("UPDATE categories SET parent_id = ? WHERE id = ?",
                   (new_parent_id, cat_id))
    
    # 批量更新 sort_order
    for i, cid in enumerate(new_order_ids):
        db.execute("UPDATE categories SET sort_order = ? WHERE id = ?", (i, cid))
    
    db.commit()
    return jsonify({'message': '移动成功'})

# --- 统计 ---

@app.route('/api/stats', methods=['GET'])
def get_stats():
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    exists = db.execute("SELECT COUNT(*) FROM files WHERE file_exists=1").fetchone()[0]
    missing = total - exists
    favorites = db.execute("SELECT COUNT(*) FROM files WHERE favorite=1").fetchone()[0]
    uncategorized = db.execute("SELECT COUNT(*) FROM files WHERE category_id IS NULL").fetchone()[0]
    cats = db.execute(
        "SELECT c.name, c.color, COUNT(f.id) as cnt FROM categories c "
        "LEFT JOIN files f ON f.category_id = c.id GROUP BY c.id ORDER BY c.id"
    ).fetchall()
    recent = db.execute(
        "SELECT COUNT(*) FROM files WHERE created_at >= datetime('now','localtime','-7 days')"
    ).fetchone()[0]

    return jsonify({
        'total': total,
        'exists': exists,
        'missing': missing,
        'favorites': favorites,
        'uncategorized': uncategorized,
        'recent_7d': recent,
        'categories': [{'name': c['name'], 'color': c['color'], 'count': c['cnt']} for c in cats],
    })




# --- 原生文件/文件夹选择器（通过 tkinter 获取真实路径）---

@app.route('/api/browse-files', methods=['POST'])
def browse_files():
    """打开原生文件选择对话框（多选），返回选中文件的真实路径"""
    try:
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
            result.append({
                'path': to_relative_path(fp), 
                'name': info['name'], 
                'size': info['size'], 
                'ext': info['ext']
            })
        return jsonify({'files': result})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'文件选择失败: {str(e)}'}), 500





if __name__ == '__main__':
    import time
    import socket
    import webview

    # 初始化数据库
    init_db()

    # 自动寻找可用端口，避免冲突
    def find_available_port(start=5000, max_attempts=100):
        for port in range(start, start + max_attempts):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(('127.0.0.1', port)) != 0:
                    return port
        raise RuntimeError(f'未能在 {start}~{start + max_attempts - 1} 中找到可用端口')

    PORT = find_available_port()

    # 在后台线程启动 Flask
    def run_flask():
        app.run(host='127.0.0.1', port=PORT, debug=False)

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # 等待 Flask 就绪（轮询直到连接成功）
    for _ in range(30):
        time.sleep(0.1)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', PORT)) == 0:
                break

    # 创建原生桌面窗口
    webview.create_window(
        title='个人文件仓库管理系统 - dxm',
        url=f'http://127.0.0.1:{PORT}',
        width=1280,
        height=800,
        min_size=(900, 600),
        text_select=True,
    )
    webview.start()
