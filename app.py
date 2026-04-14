from flask import Flask, render_template, redirect, url_for, request, jsonify, session, flash, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
import os
import qrcode, io, base64

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'hiitap-dev-secret-2026')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///hiitap.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ── Models ────────────────────────────────────────────────────

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    display_name = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(256))
    status = db.Column(db.String(20), default='bronze')
    status_points = db.Column(db.Integer, default=0)
    hiitap_points = db.Column(db.Integer, default=0)
    ticket_count = db.Column(db.Integer, default=1)
    monthly_cheer_count = db.Column(db.Integer, default=0)
    total_cheer_count = db.Column(db.Integer, default=0)
    last_daily_ticket = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    cheers = db.relationship('Cheer', backref='user', lazy=True)
    list_items = db.relationship('ListItem', backref='user', lazy=True)

    def set_password(self, pw): self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)
    @property
    def is_authenticated(self): return True
    @property
    def is_active(self): return True
    @property
    def is_anonymous(self): return False
    def get_id(self): return str(self.id)
    def rank_label(self):
        return {'bronze':'🥉 ブロンズ','silver':'🥈 シルバー','gold':'🥇 ゴールド','platinum':'💎 プラチナ'}.get(self.status,'🥉 ブロンズ')
    def points_per_cheer(self):
        return {'bronze':11,'silver':16,'gold':26,'platinum':51}.get(self.status,11)

class Store(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(200))
    category = db.Column(db.String(80))
    is_affiliated = db.Column(db.Boolean, default=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    staff = db.relationship('Staff', backref='store', lazy=True)
    cheers = db.relationship('Cheer', backref='store', lazy=True)

class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    photo_url = db.Column(db.String(200), default='/avatar.svg')
    bio = db.Column(db.Text)
    hobbies = db.Column(db.String(200))
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    cheers = db.relationship('Cheer', backref='staff', lazy=True)

    def total_points(self):
        return sum(c.ticket_sent * 50 for c in self.cheers)
    def avg_service_rating(self):
        if not self.cheers: return 0
        return round(sum(c.service_rating for c in self.cheers) / len(self.cheers), 1)

class Cheer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=False)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    service_rating = db.Column(db.Integer, nullable=False)
    atmosphere_rating = db.Column(db.Integer, nullable=False)
    good_points = db.Column(db.String(300))
    comment = db.Column(db.Text)
    is_shared = db.Column(db.Boolean, default=True)
    ticket_sent = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    def good_points_list(self):
        return self.good_points.split(',') if self.good_points else []

class CheerLimit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    cheer_date = db.Column(db.Date, nullable=False)

class ListItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=False)
    tags = db.Column(db.String(200))
    memo = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    store = db.relationship('Store')

@login_manager.user_loader
def load_user(uid): return User.query.get(int(uid))

GOOD_POINT_OPTIONS = [
    "温かい挨拶", "気配り", "メニューの知識",
    "サービスのスピード", "フレンドリーさ", "問題解決力",
    "商品知識", "積極性", "コミュニケーション"
]

def generate_qr_b64(url):
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1E2A4A", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode()

def award_points_and_rank(user):
    pts = user.points_per_cheer()
    user.status_points += pts
    user.hiitap_points += pts
    user.total_cheer_count += 1
    user.monthly_cheer_count += 1
    if user.status == 'bronze' and user.total_cheer_count >= 5:
        user.status = 'silver'
    elif user.status == 'silver' and user.monthly_cheer_count >= 10:
        user.status = 'gold'
    elif user.status == 'gold' and user.monthly_cheer_count >= 20:
        user.status = 'platinum'

# ── Auth ──────────────────────────────────────────────────────

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email','').strip()
        name  = request.form.get('display_name','').strip()
        pw    = request.form.get('password','')
        if User.query.filter_by(email=email).first():
            flash('このメールアドレスはすでに登録されています。', 'error')
            return redirect(url_for('register'))
        u = User(email=email, display_name=name)
        u.set_password(pw)
        db.session.add(u)
        db.session.commit()
        login_user(u)
        return redirect(url_for('home'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(email=request.form.get('email','')).first()
        if u and u.check_password(request.form.get('password','')):
            login_user(u)
            return redirect(url_for('home'))
        flash('メールアドレスまたはパスワードが正しくありません。', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ── Pages ─────────────────────────────────────────────────────

@app.route('/')
@login_required
def home():
    cheers = Cheer.query.filter_by(is_shared=True).order_by(Cheer.created_at.desc()).limit(30).all()
    return render_template('home.html', cheers=cheers)

@app.route('/search')
@login_required
def search():
    q = request.args.get('q','')
    category = request.args.get('category','')
    stores = []
    if q or category:
        query = Store.query
        if q: query = query.filter(Store.name.ilike(f'%{q}%'))
        if category: query = query.filter(Store.category == category)
        stores = query.all()
    categories = [c[0] for c in db.session.query(Store.category).distinct().all() if c[0]]
    return render_template('search.html', stores=stores, query=q, category=category, categories=categories)

@app.route('/store/<int:store_id>')
@login_required
def store_detail(store_id):
    store = Store.query.get_or_404(store_id)
    in_list = ListItem.query.filter_by(user_id=current_user.id, store_id=store_id).first()
    qr_b64 = generate_qr_b64(request.host_url + f'store/{store_id}')
    return render_template('store_detail.html', store=store, in_list=in_list, qr_b64=qr_b64)

# ── Cheer flow ────────────────────────────────────────────────

@app.route('/cheer/<int:store_id>/staff', methods=['GET','POST'])
@login_required
def cheer_staff(store_id):
    store = Store.query.get_or_404(store_id)
    if request.method == 'POST':
        session['cheer_store_id'] = store_id
        session['cheer_staff_id'] = int(request.form.get('staff_id'))
        return redirect(url_for('cheer_rating'))
    return render_template('cheer_staff.html', store=store)

@app.route('/cheer/rating', methods=['GET','POST'])
@login_required
def cheer_rating():
    if 'cheer_store_id' not in session: return redirect(url_for('home'))
    if request.method == 'POST':
        session['cheer_service_rating'] = int(request.form.get('service_rating',5))
        session['cheer_atmosphere_rating'] = int(request.form.get('atmosphere_rating',5))
        return redirect(url_for('cheer_goodpoints'))
    return render_template('cheer_rating.html', staff=Staff.query.get(session['cheer_staff_id']))

@app.route('/cheer/goodpoints', methods=['GET','POST'])
@login_required
def cheer_goodpoints():
    if 'cheer_store_id' not in session: return redirect(url_for('home'))
    if request.method == 'POST':
        session['cheer_good_points'] = ','.join(request.form.getlist('good_points'))
        session['cheer_comment'] = request.form.get('comment','')
        session['cheer_is_shared'] = request.form.get('is_shared') == 'yes'
        return redirect(url_for('cheer_send'))
    return render_template('cheer_goodpoints.html',
                           staff=Staff.query.get(session['cheer_staff_id']),
                           options=GOOD_POINT_OPTIONS)

@app.route('/cheer/send', methods=['GET','POST'])
@login_required
def cheer_send():
    if 'cheer_store_id' not in session: return redirect(url_for('home'))
    staff = Staff.query.get(session['cheer_staff_id'])
    store = Store.query.get(session['cheer_store_id'])
    today = date.today()
    already = CheerLimit.query.filter_by(
        user_id=current_user.id, staff_id=staff.id, cheer_date=today).first()
    if request.method == 'POST':
        if already:
            flash('You already sent appreciation to this staff today!', 'error')
            return redirect(url_for('home'))
        if current_user.ticket_count < 1:
            flash('You need a cheer ticket.', 'error')
            return redirect(url_for('mypage'))
        db.session.add(Cheer(
            user_id=current_user.id, store_id=session['cheer_store_id'],
            staff_id=session['cheer_staff_id'],
            service_rating=session.get('cheer_service_rating',5),
            atmosphere_rating=session.get('cheer_atmosphere_rating',5),
            good_points=session.get('cheer_good_points',''),
            comment=session.get('cheer_comment',''),
            is_shared=session.get('cheer_is_shared',True), ticket_sent=1))
        current_user.ticket_count -= 1
        award_points_and_rank(current_user)
        db.session.add(CheerLimit(user_id=current_user.id, staff_id=staff.id, cheer_date=today))
        db.session.commit()
        for k in ['cheer_store_id','cheer_staff_id','cheer_service_rating',
                  'cheer_atmosphere_rating','cheer_good_points','cheer_comment','cheer_is_shared']:
            session.pop(k, None)
        return redirect(url_for('cheer_complete'))
    return render_template('cheer_send.html', staff=staff, store=store,
                           already=already, tickets=current_user.ticket_count)

@app.route('/cheer/complete')
@login_required
def cheer_complete():
    return render_template('cheer_complete.html')

# ── My page ───────────────────────────────────────────────────

@app.route('/mypage')
@login_required
def mypage():
    cheers = Cheer.query.filter_by(user_id=current_user.id).order_by(Cheer.created_at.desc()).all()
    return render_template('mypage.html', cheers=cheers)

@app.route('/daily-ticket', methods=['POST'])
@login_required
def daily_ticket():
    today = date.today()
    if current_user.last_daily_ticket == today:
        return jsonify({'ok': False, 'msg': 'Already received today.'})
    current_user.ticket_count += 1
    current_user.last_daily_ticket = today
    db.session.commit()
    return jsonify({'ok': True, 'tickets': current_user.ticket_count})

@app.route('/redeem-points', methods=['POST'])
@login_required
def redeem_points():
    amount = int(request.form.get('amount', 0))
    if amount < 500 or current_user.hiitap_points < amount:
        flash('Minimum 500 points required.', 'error')
    else:
        current_user.hiitap_points -= amount
        db.session.commit()
        flash(f'Redemption request for {amount} pts submitted! 🎁', 'success')
    return redirect(url_for('mypage'))

# ── List ──────────────────────────────────────────────────────

@app.route('/list')
@login_required
def my_list():
    tag_filter = request.args.get('tag','')
    q = ListItem.query.filter_by(user_id=current_user.id)
    if tag_filter: q = q.filter(ListItem.tags.ilike(f'%{tag_filter}%'))
    items = q.order_by(ListItem.created_at.desc()).all()
    all_tags = sorted({t.strip() for item in ListItem.query.filter_by(user_id=current_user.id).all()
                       if item.tags for t in item.tags.split(',')})
    return render_template('list.html', items=items, all_tags=all_tags, tag_filter=tag_filter)

@app.route('/list/add/<int:store_id>', methods=['POST'])
@login_required
def list_add(store_id):
    if not ListItem.query.filter_by(user_id=current_user.id, store_id=store_id).first():
        db.session.add(ListItem(user_id=current_user.id, store_id=store_id,
                                tags=request.form.get('tags',''), memo=request.form.get('memo','')))
        db.session.commit()
    return redirect(request.referrer or url_for('my_list'))

@app.route('/list/remove/<int:item_id>', methods=['POST'])
@login_required
def list_remove(item_id):
    item = ListItem.query.get_or_404(item_id)
    if item.user_id == current_user.id:
        db.session.delete(item)
        db.session.commit()
    return redirect(url_for('my_list'))

@app.route('/qr/<int:store_id>')
def qr_scan(store_id):
    return redirect(url_for('store_detail', store_id=store_id))

@app.route('/avatar.svg')
def default_avatar():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="50" fill="#F5E6E0"/><circle cx="50" cy="38" r="18" fill="#E07050"/><ellipse cx="50" cy="85" rx="28" ry="20" fill="#E07050"/></svg>'
    return Response(svg, mimetype='image/svg+xml')

# ── Seed ──────────────────────────────────────────────────────

def seed():
    if Store.query.count() > 0: return
    stores = [
        dict(name='GATE CAFE', address='Narita Gateway Hotel, Chiba', category='Cafe', is_affiliated=True,
             description='A stylish cafe inside Narita Gateway Hotel, popular with international travelers.'),
        dict(name='Patagonia Shonan Terrace', address='Shonan Terrace Mall, Kanagawa', category='Retail', is_affiliated=True,
             description='Outdoor apparel store with passionate staff who love the outdoors.'),
        dict(name='Kyokinna Premium', address='Nagoya Station Towers Plaza', category='Restaurant', is_affiliated=True,
             description='Premium Japanese sweets cafe in Nagoya.'),
        dict(name='The Rooftop Bar', address='Shibuya, Tokyo', category='Bar', is_affiliated=False,
             description='Trendy rooftop bar with city views.'),
    ]
    staff_pool = [('Alex Kim','Loves coffee & travel'),('Maria Chen','Expert barista'),
                  ('James Park','Outdoor enthusiast'),('Yuki Tanaka','Hospitality pro')]
    for sd in stores:
        store = Store(**sd); db.session.add(store); db.session.flush()
        for sn, bio in staff_pool[:2]:
            db.session.add(Staff(store_id=store.id, name=sn, bio=bio))
    # demo user
    if not User.query.filter_by(email='demo@hiitap.com').first():
        u = User(email='demo@hiitap.com', display_name='Demo User',
                 ticket_count=5, status_points=120, hiitap_points=120)
        u.set_password('demo1234')
        db.session.add(u)
    db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed()
    app.run(debug=True, port=int(os.environ.get('PORT', 5000)))
