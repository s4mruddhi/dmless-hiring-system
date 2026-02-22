import os
import uuid
import sqlite3
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, send_file, g
)

# -------------------------------
# App Configuration
# -------------------------------
app = Flask(__name__)
app.debug = False   # ⭐ ADDED FOR VERCEL

app.secret_key = 'your-secret-key-change-in-production'
app.config['UPLOAD_FOLDER'] = 'uploads'
DATABASE = 'database.db'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# -------------------------------
# Database helpers
# -------------------------------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS recruiters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recruiter_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                description TEXT NOT NULL,
                link_id TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (recruiter_id) REFERENCES recruiters (id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                option1 TEXT NOT NULL,
                option2 TEXT NOT NULL,
                option3 TEXT NOT NULL,
                option4 TEXT NOT NULL,
                correct_option INTEGER NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs (id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                status TEXT NOT NULL,
                resume_path TEXT,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs (id)
            )
        ''')

        db.commit()

init_db()

# -------------------------------
# Helper Functions
# -------------------------------
def recruiter_required(f):
    def wrapper(*args, **kwargs):
        if 'recruiter_id' not in session:
            flash('Please log in first.')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# -------------------------------
# Routes
# -------------------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        db = get_db()
        cursor = db.cursor()

        cursor.execute('SELECT id FROM recruiters WHERE email = ?', (email,))
        if cursor.fetchone():
            flash('Email already registered.')
            return redirect(url_for('signup'))

        cursor.execute(
            'INSERT INTO recruiters (name, email, password) VALUES (?, ?, ?)',
            (name, email, password)
        )
        db.commit()

        recruiter_id = cursor.lastrowid
        session['recruiter_id'] = recruiter_id
        session['recruiter_name'] = name
        return redirect(url_for('dashboard'))

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        db = get_db()
        cursor = db.cursor()

        cursor.execute(
            'SELECT id, name FROM recruiters WHERE email = ? AND password = ?',
            (email, password)
        )
        recruiter = cursor.fetchone()

        if recruiter:
            session['recruiter_id'] = recruiter['id']
            session['recruiter_name'] = recruiter['name']
            return redirect(url_for('dashboard'))

        flash('Invalid email or password.')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
@recruiter_required
def dashboard():
    recruiter_id = session['recruiter_id']
    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
        SELECT * FROM jobs WHERE recruiter_id = ? ORDER BY created_at DESC
    ''', (recruiter_id,))
    jobs_rows = cursor.fetchall()

    jobs = []
    total_applicants = 0
    knocked_out = 0
    shortlisted = 0

    for job_row in jobs_rows:
        job = dict(job_row)
        job['created_at'] = datetime.strptime(job['created_at'], '%Y-%m-%d %H:%M:%S')

        cursor.execute('SELECT * FROM candidates WHERE job_id = ?', (job['id'],))
        candidates = [dict(row) for row in cursor.fetchall()]
        job['candidates'] = candidates

        cursor.execute('SELECT * FROM questions WHERE job_id = ?', (job['id'],))
        questions = [dict(row) for row in cursor.fetchall()]
        job['questions'] = questions

        jobs.append(job)

        total_applicants += len(candidates)
        knocked_out += sum(1 for c in candidates if c['status'] == 'knocked_out')
        shortlisted += sum(1 for c in candidates if c['status'] == 'shortlisted')

    return render_template('dashboard.html',
                           jobs=jobs,
                           total_applicants=total_applicants,
                           knocked_out=knocked_out,
                           shortlisted=shortlisted)

@app.route('/create_job', methods=['GET', 'POST'])
@recruiter_required
def create_job():
    if request.method == 'POST':
        role = request.form['role']
        description = request.form['description']
        link_id = uuid.uuid4().hex
        recruiter_id = session['recruiter_id']

        db = get_db()
        cursor = db.cursor()

        cursor.execute('''
            INSERT INTO jobs (recruiter_id, role, description, link_id)
            VALUES (?, ?, ?, ?)
        ''', (recruiter_id, role, description, link_id))

        job_id = cursor.lastrowid

        for i in range(1, 6):
            text = request.form[f'q{i}']
            opt1 = request.form[f'q{i}opt1']
            opt2 = request.form[f'q{i}opt2']
            opt3 = request.form[f'q{i}opt3']
            opt4 = request.form[f'q{i}opt4']
            correct = int(request.form[f'q{i}correct'])

            cursor.execute('''
                INSERT INTO questions (job_id, text, option1, option2, option3, option4, correct_option)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (job_id, text, opt1, opt2, opt3, opt4, correct))

        db.commit()
        return redirect(url_for('dashboard'))

    return render_template('create_job.html')

@app.route('/apply/<link_id>', methods=['GET', 'POST'])
def apply(link_id):
    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT * FROM jobs WHERE link_id = ?', (link_id,))
    job_row = cursor.fetchone()

    if not job_row:
        flash('Invalid hiring link.')
        return redirect(url_for('index'))

    job = dict(job_row)

    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']

        cursor.execute('''
            INSERT INTO candidates (job_id, name, email, status)
            VALUES (?, ?, ?, ?)
        ''', (job['id'], name, email, 'pending'))

        candidate_id = cursor.lastrowid
        db.commit()

        cursor.execute('SELECT * FROM questions WHERE job_id = ?', (job['id'],))
        questions = [dict(row) for row in cursor.fetchall()]

        all_correct = True
        for q in questions:
            submitted = int(request.form.get(f'q{q["id"]}'))
            if submitted != q['correct_option']:
                all_correct = False
                break

        if all_correct:
            return redirect(url_for('upload_resume', candidate_id=candidate_id))
        else:
            cursor.execute('UPDATE candidates SET status = ? WHERE id = ?', ('knocked_out', candidate_id))
            db.commit()
            return redirect(url_for('result', status='rejected'))

    cursor.execute('SELECT * FROM questions WHERE job_id = ?', (job['id'],))
    questions = [dict(row) for row in cursor.fetchall()]
    job['questions'] = questions

    return render_template('apply.html', job=job)

@app.route('/upload_resume/<int:candidate_id>', methods=['GET', 'POST'])
def upload_resume(candidate_id):
    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT * FROM candidates WHERE id = ?', (candidate_id,))
    candidate_row = cursor.fetchone()

    if not candidate_row:
        flash('Candidate not found.')
        return redirect(url_for('index'))

    candidate = dict(candidate_row)

    if request.method == 'POST':
        if 'resume' not in request.files:
            flash('No file uploaded.')
            return redirect(request.url)

        file = request.files['resume']
        if file.filename == '':
            flash('No file selected.')
            return redirect(request.url)

        filename = secure_filename(f"{candidate_id}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        cursor.execute('''
            UPDATE candidates SET resume_path = ?, status = ? WHERE id = ?
        ''', (filename, 'shortlisted', candidate_id))
        db.commit()

        return redirect(url_for('result', status='selected'))

    return render_template('upload_resume.html', candidate=candidate)

@app.route('/result')
def result():
    status = request.args.get('status', 'unknown')
    return render_template('result.html', status=status)

@app.route('/resume/<filename>')
def download_resume(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename))

@app.route('/candidate-info')
def candidate_info():
    return render_template('candidate_info.html')

# ⭐ UPDATED FOR VERCEL DEPLOYMENT
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)