"""
AnonForum - A single-file Flask forum with anonymous sign-in, ads placeholders, and a modern GUI.
Files: this single Python file runs the entire site (uses render_template_string for templates).

Requirements:
- Python 3.10+
- pip install flask

Run:
$ pip install flask
$ python anon_forum.py
Open http://127.0.0.1:5000

Notes:
- Ads are placeholders (divs). To integrate real ads, add the ad network JS snippet into the templates.
- This is a minimal example meant for learning/prototyping. For production, use migrations, proper auth, HTTPS, and sanitize inputs.
"""

from flask import Flask, request, g, redirect, url_for, session, jsonify, render_template_string
import sqlite3
import os
import secrets
from datetime import datetime

# ---------- Configuration ----------
DB_PATH = 'anonforum.db'
SECRET_KEY = os.environ.get('ANONFORUM_SECRET') or secrets.token_hex(32)
POSTS_PER_PAGE = 10

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SESSION_COOKIE_HTTPONLY'] = True

# ---------- Database helpers ----------

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    cur = db.cursor()
    cur.executescript('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        display_name TEXT NOT NULL,
        anon_id TEXT UNIQUE NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        score INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        user_id INTEGER,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(post_id) REFERENCES posts(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_anon TEXT NOT NULL,
        target_type TEXT NOT NULL, -- 'post' or 'comment'
        target_id INTEGER NOT NULL,
        value INTEGER NOT NULL,
        UNIQUE(user_anon, target_type, target_id)
    );
    ''')
    db.commit()

# Ensure DB exists
with app.app_context():
    init_db()

# ---------- Utilities ----------

def current_user():
    anon = session.get('anon_id')
    if not anon:
        return None
    db = get_db()
    cur = db.execute('SELECT * FROM users WHERE anon_id = ?', (anon,))
    return cur.fetchone()

# ---------- Routes & API ----------

BASE_HTML = '''
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AnonForum — anonymous, slick, fast</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root{--bg:#0f1724;--card:#0b1220;--muted:#9aa4b2;--accent:#6ee7b7;--glass: rgba(255,255,255,0.03)}
    *{box-sizing:border-box;font-family:Inter,system-ui,Segoe UI,Roboto,'Helvetica Neue',Arial}
    html,body{height:100%;margin:0;background:linear-gradient(180deg,var(--bg),#071227);color:#e6eef6}
    .container{max-width:1100px;margin:28px auto;padding:18px}
    header{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}
    .logo{display:flex;align-items:center;gap:12px}
    .logo .mark{width:44px;height:44px;border-radius:10px;display:grid;place-items:center;background:linear-gradient(135deg,#3ee7c8,#6b8dff);font-weight:800;color:#022}
    h1{margin:0;font-size:20px}
    nav{display:flex;gap:8px}
    button.btn{background:var(--glass);border:1px solid rgba(255,255,255,0.04);padding:8px 12px;border-radius:10px;color:var(--accent);cursor:pointer}

    .layout{display:grid;grid-template-columns:1fr 320px;gap:18px}
    .card{background:linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01));padding:14px;border-radius:12px;border:1px solid rgba(255,255,255,0.03)}

    .post-form textarea{width:100%;min-height:90px;background:transparent;border:1px dashed rgba(255,255,255,0.03);padding:10px;border-radius:8px;color:inherit}
    input[type=text]{width:100%;padding:10px;border-radius:8px;border:1px solid rgba(255,255,255,0.03);background:transparent;color:inherit}

    .post{display:flex;gap:12px;padding:12px;border-radius:10px;margin-bottom:12px}
    .score{width:56px;display:flex;flex-direction:column;align-items:center;justify-content:center;background:rgba(255,255,255,0.02);border-radius:8px}
    .post .body{flex:1}
    .post .title{font-weight:700;margin-bottom:6px}
    .muted{color:var(--muted);font-size:13px}

    .ads{background:linear-gradient(180deg, rgba(255,255,255,0.015), rgba(255,255,255,0.01));padding:10px;border-radius:10px;text-align:center;color:var(--muted);}
    .ad-pill{padding:8px;border-radius:8px;border:1px dashed rgba(255,255,255,0.03);display:inline-block;margin:8px 0}

    .comments{margin-top:8px}
    .comment{padding:8px;border-radius:8px;margin-bottom:6px;background:rgba(255,255,255,0.01)}

    footer{margin-top:18px;text-align:center;color:var(--muted);font-size:13px}

    @media (max-width:920px){.layout{grid-template-columns:1fr}.container{padding:8px}}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="logo">
        <div class="mark">AF</div>
        <div>
          <h1>AnonForum</h1>
          <div class="muted">Make posts. Stay anonymous. Clean UI.</div>
        </div>
      </div>
      <nav>
        {% if user %}
          <div class="muted" style="align-self:center">Signed in as <strong>{{ user['display_name'] }}</strong></div>
          <form method="post" action="/signout" style="display:inline">
            <button class="btn">Sign out</button>
          </form>
        {% else %}
          <button class="btn" onclick="showSignIn()">Anonymous sign in</button>
        {% endif %}
      </nav>
    </header>

    <div class="layout">
      <main>
        <div class="card post-form">
          <form id="postForm" onsubmit="return submitPost(event)">
            <input id="title" name="title" type="text" placeholder="Post title — be bold" required>
            <div style="height:8px"></div>
            <textarea id="body" name="body" placeholder="Write something interesting..." required></textarea>
            <div style="height:8px"></div>
            <div style="display:flex;gap:8px;justify-content:space-between;align-items:center">
              <div class="muted">Posting as: <span id="showAnon">{{ user['display_name'] if user else 'Guest' }}</span></div>
              <div>
                <button class="btn" type="submit">Post</button>
              </div>
            </div>
          </form>
        </div>

        <div id="postsArea"></div>

      </main>

      <aside>
        <div class="card ads">
          <div class="muted">Sponsored</div>
          <div class="ad-pill">Ad slot 1 — 300x250</div>
          <div class="ad-pill">Ad slot 2 — 300x100</div>
          <div class="muted" style="font-size:12px;margin-top:6px">To use live ads: replace these divs with your ad network script (e.g. Google AdSense).</div>
        </div>

        <div style="height:12px"></div>

        <div class="card">
          <div class="muted">About</div>
          <div style="margin-top:8px">AnonForum is a demo forum with anonymous sign in and an emphasis on a minimal, elegant interface. Built with Flask + SQLite in a single file for learning.</div>
        </div>
      </aside>
    </div>

    <footer>Built for prototyping — upgrade before public use.</footer>
  </div>

  <!-- Sign-in modal (simple) -->
  <div id="signinModal" style="display:none;position:fixed;inset:0;background:rgba(2,6,23,0.6);backdrop-filter:blur(4px);align-items:center;justify-content:center">
    <div style="width:420px;background:var(--card);padding:18px;border-radius:12px;margin:auto">
      <h3 style="margin:0 0 6px 0">Anonymous sign in</h3>
      <div class="muted" style="margin-bottom:12px">Pick a short display name — it won't be connected to you.</div>
      <form onsubmit="return doSignin(event)">
        <input id="display_name" type="text" placeholder="e.g. mysterious42" required>
        <div style="height:12px"></div>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button type="button" class="btn" onclick="hideSignIn()">Cancel</button>
          <button class="btn" type="submit">Sign in</button>
        </div>
      </form>
    </div>
  </div>

  <script>
    let currentUser = {{ 'true' if user else 'false' }};

    function showSignIn(){
      document.getElementById('signinModal').style.display='flex'
    }
    function hideSignIn(){
      document.getElementById('signinModal').style.display='none'
    }
    async function doSignin(e){
      e.preventDefault();
      const name = document.getElementById('display_name').value.trim();
      if(!name) return;
      const res = await fetch('/signin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({display_name:name})});
      if(res.ok){
        location.reload();
      }else{
        alert('Sign in failed')
      }
    }

    async function submitPost(e){
      e.preventDefault();
      const title = document.getElementById('title').value.trim();
      const body = document.getElementById('body').value.trim();
      if(!title || !body) return;
      const res = await fetch('/post',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,body})});
      if(res.ok){
        document.getElementById('title').value='';
        document.getElementById('body').value='';
        loadPosts();
      }else{
        alert('Failed to post')
      }
    }

    async function loadPosts(){
      const res = await fetch('/posts');
      const data = await res.json();
      const container = document.getElementById('postsArea');
      container.innerHTML = '';
      for(const p of data.posts){
        const el = document.createElement('div');
        el.className = 'card post';
        el.innerHTML = `
          <div class="score">
            <div style="font-weight:700">${p.score}</div>
            <div style="display:flex;gap:6px;margin-top:6px">
              <button onclick="vote('post',${p.id},1)" class="btn">▲</button>
              <button onclick="vote('post',${p.id},-1)" class="btn">▼</button>
            </div>
          </div>
          <div class="body">
            <div class="title">${escapeHtml(p.title)}</div>
            <div class="muted">by ${escapeHtml(p.display_name || 'Guest')} · ${p.created_at}</div>
            <div style="height:8px"></div>
            <div>${escapeHtml(p.body)}</div>
            <div class="comments"></div>
            <div style="height:8px"></div>
            <div style="display:flex;gap:8px;align-items:center">
              <input type="text" placeholder="Add a comment..." id="c_${p.id}" style="flex:1;padding:8px;border-radius:8px;background:transparent;border:1px solid rgba(255,255,255,0.03)" />
              <button class="btn" onclick="submitComment(${p.id})">Comment</button>
            </div>
          </div>
        `;
        container.appendChild(el);

        // inject ad after every 4 posts
        if(data.posts.indexOf(p) % 4 === 3){
          const ad = document.createElement('div');
          ad.className = 'card ads';
          ad.style.margin='12px 0';
          ad.innerHTML = '<div class="muted">Sponsored</div><div class="ad-pill">Inline Ad</div>';
          container.appendChild(ad);
        }

        // load comments
        const commentsDiv = el.querySelector('.comments');
        for(const c of p.comments){
          const ce = document.createElement('div');
          ce.className='comment';
          ce.innerHTML = `<div class="muted">${escapeHtml(c.display_name||'Guest')} · ${c.created_at}</div><div style="height:6px"></div><div>${escapeHtml(c.body)}</div>`;
          commentsDiv.appendChild(ce);
        }
      }
    }

    async function vote(target_type,target_id,value){
      const res = await fetch('/vote',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target_type,target_id,value})});
      if(res.ok) loadPosts(); else alert('Vote failed')
    }

    async function submitComment(post_id){
      const input = document.getElementById('c_'+post_id);
      const body = input.value.trim();
      if(!body) return;
      const res = await fetch('/comment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({post_id,body})});
      if(res.ok){
        input.value='';
        loadPosts();
      }else alert('Comment failed')
    }

    function escapeHtml(str){
      if(!str) return '';
      return str.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
    }

    // initial load
    loadPosts();
  </script>
</body>
</html>
'''

@app.route('/')
def index():
    user = current_user()
    return render_template_string(BASE_HTML, user=user)

# API: posts list
@app.route('/posts')
def posts_api():
    db = get_db()
    cur = db.execute('SELECT p.*, u.display_name FROM posts p LEFT JOIN users u ON p.user_id=u.id ORDER BY p.created_at DESC')
    posts = []
    for r in cur.fetchall():
        # load comments
        ccur = db.execute('SELECT c.*, u.display_name FROM comments c LEFT JOIN users u ON c.user_id=u.id WHERE c.post_id = ? ORDER BY c.created_at ASC', (r['id'],))
        comments = [dict(ci) for ci in ccur.fetchall()]
        posts.append({
            'id': r['id'],
            'title': r['title'],
            'body': r['body'],
            'score': r['score'],
            'created_at': r['created_at'],
            'display_name': r['display_name'],
            'comments': comments
        })
    return jsonify({'posts': posts})

@app.route('/signin', methods=['POST'])
def signin():
    data = request.get_json() or {}
    name = (data.get('display_name') or '').strip()[:30]
    if not name:
        return ('', 400)
    anon_id = secrets.token_urlsafe(12)
    now = datetime.utcnow().isoformat()
    db = get_db()
    cur = db.cursor()
    cur.execute('INSERT INTO users (display_name, anon_id, created_at) VALUES (?, ?, ?)', (name, anon_id, now))
    db.commit()
    session['anon_id'] = anon_id
    return ('', 204)

@app.route('/signout', methods=['POST'])
def signout():
    session.pop('anon_id', None)
    return redirect(url_for('index'))

@app.route('/post', methods=['POST'])
def create_post():
    user = current_user()
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()[:200]
    body = (data.get('body') or '').strip()[:4000]
    if not title or not body:
        return ('', 400)
    db = get_db()
    now = datetime.utcnow().isoformat()
    user_id = user['id'] if user else None
    db.execute('INSERT INTO posts (user_id, title, body, created_at) VALUES (?, ?, ?, ?)', (user_id, title, body, now))
    db.commit()
    return ('', 204)

@app.route('/comment', methods=['POST'])
def create_comment():
    user = current_user()
    data = request.get_json() or {}
    post_id = int(data.get('post_id') or 0)
    body = (data.get('body') or '').strip()[:1000]
    if not post_id or not body:
        return ('', 400)
    db = get_db()
    now = datetime.utcnow().isoformat()
    user_id = user['id'] if user else None
    db.execute('INSERT INTO comments (post_id, user_id, body, created_at) VALUES (?, ?, ?, ?)', (post_id, user_id, body, now))
    db.commit()
    return ('', 204)

@app.route('/vote', methods=['POST'])
def vote():
    anon = session.get('anon_id') or request.remote_addr or 'anonymous'
    data = request.get_json() or {}
    target_type = data.get('target_type')
    target_id = int(data.get('target_id') or 0)
    value = int(data.get('value') or 0)
    if target_type not in ('post','comment') or target_id<=0 or value not in (-1,1):
        return ('',400)
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute('INSERT OR REPLACE INTO votes (user_anon, target_type, target_id, value) VALUES (?, ?, ?, ?)', (anon, target_type, target_id, value))
        # update score on posts only
        if target_type == 'post':
            # recalc
            s = db.execute('SELECT SUM(value) as s FROM votes WHERE target_type=? AND target_id=?', (target_type, target_id)).fetchone()['s'] or 0
            cur.execute('UPDATE posts SET score = ? WHERE id = ?', (s, target_id))
        db.commit()
        return ('',204)
    except Exception as e:
        print('vote err',e)
        return ('',500)

if __name__ == '__main__':
    app.run(debug=True)
