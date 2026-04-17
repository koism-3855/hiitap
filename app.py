import os, io, base64, hashlib, json, qrcode, requests
from flask import (Flask, render_template, redirect, url_for,
                   request, jsonify, session, flash, Response)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta

# ── .env 読み込み ─────────────────────────────────────────────────
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    for _line in open(_env_path):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# ── Flask 設定 ────────────────────────────────────────────────────
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "hiitap-dev-2026")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///hiitap.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

def get_gmaps_key():
    return os.environ.get("GOOGLE_MAPS_API_KEY", "")
CACHE_TTL_HOURS  = 24          # 検索結果キャッシュの有効期間（時間）
PLACES_BASE      = "https://maps.googleapis.com/maps/api/place"

db           = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"


# ═══════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════

class User(db.Model):
    id                  = db.Column(db.Integer, primary_key=True)
    email               = db.Column(db.String(120), unique=True, nullable=False)
    display_name        = db.Column(db.String(80),  nullable=False)
    password_hash       = db.Column(db.String(256))
    status              = db.Column(db.String(20),  default="bronze")
    status_points       = db.Column(db.Integer,     default=0)
    hiitap_points       = db.Column(db.Integer,     default=0)
    ticket_count        = db.Column(db.Integer,     default=1)
    monthly_cheer_count = db.Column(db.Integer,     default=0)
    total_cheer_count   = db.Column(db.Integer,     default=0)
    last_daily_ticket   = db.Column(db.Date,        nullable=True)
    created_at          = db.Column(db.DateTime,    default=datetime.utcnow)
    cheers              = db.relationship("Cheer",    backref="user", lazy=True)
    list_items          = db.relationship("ListItem", backref="user", lazy=True)

    def set_password(self, pw):   self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)

    @property
    def is_authenticated(self): return True
    @property
    def is_active(self):        return True
    @property
    def is_anonymous(self):     return False
    def get_id(self):           return str(self.id)

    def rank_label(self):
        return {"bronze": "🥉 Bronze", "silver": "🥈 Silver",
                "gold":   "🥇 Gold",   "platinum": "💎 Platinum"}.get(self.status, "🥉 Bronze")

    def points_per_cheer(self):
        return {"bronze": 11, "silver": 16, "gold": 26, "platinum": 51}.get(self.status, 11)


class Store(db.Model):
    id            = db.Column(db.Integer,  primary_key=True)
    place_id      = db.Column(db.String(200), unique=True, nullable=True)
    name          = db.Column(db.String(120), nullable=False)
    address       = db.Column(db.String(300))
    category      = db.Column(db.String(80))
    lat           = db.Column(db.Float)
    lng           = db.Column(db.Float)
    photo_ref     = db.Column(db.String(400))
    google_rating = db.Column(db.Float)
    is_affiliated = db.Column(db.Boolean, default=False)
    description   = db.Column(db.Text)
    website       = db.Column(db.String(200))
    phone         = db.Column(db.String(50))
    opening_hours = db.Column(db.Text)       # JSON list of strings
    created_at    = db.Column(db.DateTime,   default=datetime.utcnow)
    staff         = db.relationship("Staff",    backref="store", lazy=True)
    cheers        = db.relationship("Cheer",    backref="store", lazy=True)

    def hiitap_rating(self):
        if not self.cheers: return None
        return round(sum(c.service_rating for c in self.cheers) / len(self.cheers), 1)

    def cheer_count(self):
        return len(self.cheers)

    def photo_url(self, maxwidth=400):
        if self.photo_ref and get_gmaps_key():
            return (f"{PLACES_BASE}/photo"
                    f"?maxwidth={maxwidth}&photo_reference={self.photo_ref}&key={get_gmaps_key()}")
        return None


class Staff(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    store_id  = db.Column(db.Integer, db.ForeignKey("store.id"), nullable=False)
    name      = db.Column(db.String(80), nullable=False)
    photo_url = db.Column(db.String(200), default="/avatar.svg")
    bio       = db.Column(db.Text)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    cheers    = db.relationship("Cheer", backref="staff", lazy=True)

    def total_points(self):
        return sum(c.ticket_sent * 50 for c in self.cheers)

    def avg_rating(self):
        if not self.cheers: return 0
        return round(sum(c.service_rating for c in self.cheers) / len(self.cheers), 1)


class Cheer(db.Model):
    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey("user.id"),  nullable=False)
    store_id         = db.Column(db.Integer, db.ForeignKey("store.id"), nullable=False)
    staff_id         = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=True)
    service_rating   = db.Column(db.Integer, nullable=False)
    atmosphere_rating= db.Column(db.Integer, nullable=False)
    good_points      = db.Column(db.String(300))
    comment          = db.Column(db.Text)
    is_shared        = db.Column(db.Boolean, default=True)
    ticket_sent      = db.Column(db.Integer, default=1)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    def good_points_list(self):
        return [p for p in (self.good_points or "").split(",") if p]


class CheerLimit(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("user.id"),  nullable=False)
    store_id   = db.Column(db.Integer, db.ForeignKey("store.id"), nullable=False)
    staff_id   = db.Column(db.Integer, nullable=True)
    cheer_date = db.Column(db.Date, nullable=False)


class ListItem(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("user.id"),  nullable=False)
    store_id   = db.Column(db.Integer, db.ForeignKey("store.id"), nullable=False)
    tags       = db.Column(db.String(200))
    memo       = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    store      = db.relationship("Store")


class SearchCache(db.Model):
    """Google Places 検索結果キャッシュ（24時間有効）"""
    id         = db.Column(db.Integer,  primary_key=True)
    cache_key  = db.Column(db.String(64), unique=True, nullable=False, index=True)
    query      = db.Column(db.String(200))
    results    = db.Column(db.Text, nullable=False)   # JSON string
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)

    def is_valid(self):
        return datetime.utcnow() < self.expires_at

    @staticmethod
    def make_key(raw: str) -> str:
        normalized = " ".join(raw.lower().split())
        return hashlib.md5(normalized.encode()).hexdigest()


@login_manager.user_loader
def load_user(uid):
    return User.query.get(int(uid))


# ═══════════════════════════════════════════════════════════════════
# Google Places API helpers
# ═══════════════════════════════════════════════════════════════════

def _places_get(endpoint, params):
    """Places API への共通リクエスト。失敗時は空リストを返す。"""
    if not get_gmaps_key():
        return []
    try:
        r = requests.get(f"{PLACES_BASE}/{endpoint}", params={**params, "key": get_gmaps_key()}, timeout=5)
        return r.json().get("results", [])
    except Exception as e:
        app.logger.warning(f"Places API error ({endpoint}): {e}")
        return []


def places_text_search(query, language="ja"):
    return _places_get("textsearch/json", {
        "query": query, "language": language, "type": "establishment"
    })


def places_nearby_search(lat, lng, radius=800, keyword="", language="ja"):
    params = {"location": f"{lat},{lng}", "radius": radius, "language": language,
              "type": "establishment"}
    if keyword:
        params["keyword"] = keyword
    return _places_get("nearbysearch/json", params)


def places_detail(place_id, language="ja"):
    if not get_gmaps_key():
        return None
    try:
        fields = ("place_id,name,formatted_address,geometry,photo,rating,"
                  "opening_hours,website,formatted_phone_number,types,business_status")
        r = requests.get(f"{PLACES_BASE}/details/json", params={
            "place_id": place_id, "fields": fields,
            "key": get_gmaps_key(), "language": language
        }, timeout=5)
        return r.json().get("result")
    except Exception as e:
        app.logger.warning(f"Places detail error: {e}")
        return None


def _infer_category(types):
    mapping = {
        "restaurant": "Restaurant", "cafe": "Cafe", "bar": "Bar",
        "food": "Restaurant", "bakery": "Cafe", "meal_takeaway": "Restaurant",
        "lodging": "Hotel", "hotel": "Hotel",
        "clothing_store": "Retail", "store": "Retail", "shopping_mall": "Retail",
        "beauty_salon": "Beauty", "hair_care": "Beauty", "spa": "Beauty",
        "gym": "Fitness", "night_club": "Bar",
    }
    for t in (types or []):
        if t in mapping:
            return mapping[t]
    return "Other"


def place_result_to_dict(p):
    geom   = p.get("geometry", {}).get("location", {})
    photos = p.get("photos", [])
    return dict(
        place_id      = p.get("place_id"),
        name          = p.get("name", ""),
        address       = p.get("formatted_address") or p.get("vicinity", ""),
        lat           = geom.get("lat"),
        lng           = geom.get("lng"),
        photo_ref     = photos[0].get("photo_reference") if photos else None,
        google_rating = p.get("rating"),
        category      = _infer_category(p.get("types", [])),
    )


# ── キャッシュ付き検索 ─────────────────────────────────────────────

def _cache_get_or_fetch(cache_key_raw, fetch_fn):
    """汎用キャッシュ取得。キャッシュミス時は fetch_fn() を呼ぶ。"""
    key    = SearchCache.make_key(cache_key_raw)
    cached = db.session.query(SearchCache).filter_by(cache_key=key).first()

    if cached and cached.is_valid():
        return json.loads(cached.results)

    results  = fetch_fn()
    expires  = datetime.utcnow() + timedelta(hours=CACHE_TTL_HOURS)
    if cached:
        cached.results    = json.dumps(results, ensure_ascii=False)
        cached.expires_at = expires
        cached.created_at = datetime.utcnow()
        cached.query      = cache_key_raw
    else:
        db.session.add(SearchCache(
            cache_key  = key,
            query      = cache_key_raw,
            results    = json.dumps(results, ensure_ascii=False),
            expires_at = expires,
        ))
    db.session.commit()
    return results


def places_text_search_cached(query, language="ja"):
    return _cache_get_or_fetch(
        query,
        lambda: [place_result_to_dict(p) for p in places_text_search(query, language)[:12]]
    )


def places_nearby_search_cached(lat, lng, radius=800, keyword="", language="ja"):
    lat_r   = round(lat, 2)
    lng_r   = round(lng, 2)
    raw_key = f"nearby:{lat_r}:{lng_r}:{keyword.lower().strip()}"
    return _cache_get_or_fetch(
        raw_key,
        lambda: [place_result_to_dict(p)
                 for p in places_nearby_search(lat, lng, radius, keyword, language)[:10]]
    )


def get_or_create_store(place_id):
    """place_id でDB検索し、なければ Places API から取得してDB保存して返す。"""
    store = Store.query.filter_by(place_id=place_id).first()
    if store:
        return store
    detail = places_detail(place_id)
    if not detail:
        return None
    d  = place_result_to_dict(detail)
    oh = detail.get("opening_hours", {})
    store = Store(
        place_id      = d["place_id"],
        name          = d["name"],
        address       = d["address"],
        lat           = d["lat"],
        lng           = d["lng"],
        photo_ref     = d["photo_ref"],
        google_rating = d["google_rating"],
        category      = d["category"],
        website       = detail.get("website", ""),
        phone         = detail.get("formatted_phone_number", ""),
        opening_hours = json.dumps(oh.get("weekday_text", []), ensure_ascii=False),
        is_affiliated = False,
    )
    db.session.add(store)
    db.session.commit()
    return store


def purge_expired_cache():
    """期限切れのキャッシュを削除する（定期呼び出し用）。"""
    deleted = (db.session.query(SearchCache)
               .filter(SearchCache.expires_at < datetime.utcnow())
               .delete())
    db.session.commit()
    return deleted


# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

GOOD_POINT_OPTIONS = [
    "Warm Greeting", "Attentiveness", "Menu Knowledge",
    "Speed of Service", "Friendliness", "Problem Resolution",
    "Product Knowledge", "Proactiveness", "Communication",
]


def generate_qr_b64(url):
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1E2A4A", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def award_points_and_rank(user):
    pts = user.points_per_cheer()
    user.status_points       += pts
    user.hiitap_points       += pts
    user.total_cheer_count   += 1
    user.monthly_cheer_count += 1
    if user.status == "bronze"   and user.total_cheer_count   >= 5:  user.status = "silver"
    elif user.status == "silver" and user.monthly_cheer_count >= 10: user.status = "gold"
    elif user.status == "gold"   and user.monthly_cheer_count >= 20: user.status = "platinum"


@app.context_processor
def inject_globals():
    return {"gmaps_key": get_gmaps_key()}


# ═══════════════════════════════════════════════════════════════════
# Auth
# ═══════════════════════════════════════════════════════════════════

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        name  = request.form.get("display_name", "").strip()
        pw    = request.form.get("password", "")
        if User.query.filter_by(email=email).first():
            flash("Email already registered.", "error")
            return redirect(url_for("register"))
        u = User(email=email, display_name=name)
        u.set_password(pw)
        db.session.add(u)
        db.session.commit()
        login_user(u)
        return redirect(url_for("home"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = User.query.filter_by(email=request.form.get("email", "")).first()
        if u and u.check_password(request.form.get("password", "")):
            login_user(u)
            return redirect(url_for("home"))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ═══════════════════════════════════════════════════════════════════
# Feed
# ═══════════════════════════════════════════════════════════════════

@app.route("/")
@login_required
def home():
    cheers = (Cheer.query.filter_by(is_shared=True)
              .order_by(Cheer.created_at.desc()).limit(30).all())
    return render_template("home.html", cheers=cheers)


# ═══════════════════════════════════════════════════════════════════
# Search  (Google Maps + cache)
# ═══════════════════════════════════════════════════════════════════

@app.route("/search")
@login_required
def search():
    q         = request.args.get("q", "").strip()
    results   = []
    use_gmaps = bool(get_gmaps_key())

    if q:
        if use_gmaps:
            place_dicts = places_text_search_cached(q)
        else:
            stores      = Store.query.filter(Store.name.ilike(f"%{q}%")).all()
            place_dicts = [dict(place_id=s.place_id, name=s.name, address=s.address,
                                category=s.category, google_rating=s.google_rating,
                                lat=s.lat, lng=s.lng, photo_ref=s.photo_ref) for s in stores]

        for d in place_dicts:
            existing = Store.query.filter_by(place_id=d.get("place_id")).first()
            results.append({**d,
                            "hiitap_count":  existing.cheer_count()  if existing else 0,
                            "hiitap_rating": existing.hiitap_rating() if existing else None,
                            "is_affiliated": existing.is_affiliated   if existing else False,
                            "in_db":         existing is not None})

    return render_template("search.html", results=results, query=q,
                           use_gmaps=use_gmaps, gmaps_key=get_gmaps_key())


@app.route("/api/places/nearby")
@login_required
def api_places_nearby():
    lat     = request.args.get("lat", type=float)
    lng     = request.args.get("lng", type=float)
    keyword = request.args.get("kw", "")
    if not lat or not lng:
        return jsonify({"error": "lat/lng required"}), 400

    raw     = places_nearby_search_cached(lat, lng, radius=800, keyword=keyword)
    results = []
    for d in raw:
        existing = Store.query.filter_by(place_id=d.get("place_id")).first()
        results.append({**d,
                        "hiitap_count":  existing.cheer_count()  if existing else 0,
                        "is_affiliated": existing.is_affiliated   if existing else False})
    return jsonify({"results": results})


# ═══════════════════════════════════════════════════════════════════
# Store detail
# ═══════════════════════════════════════════════════════════════════

@app.route("/store/place/<place_id>")
@login_required
def store_by_place(place_id):
    store = get_or_create_store(place_id)
    if not store:
        flash("Store information could not be retrieved.", "error")
        return redirect(url_for("search"))
    return redirect(url_for("store_detail", store_id=store.id))


@app.route("/store/<int:store_id>")
@login_required
def store_detail(store_id):
    store         = Store.query.get_or_404(store_id)
    in_list       = ListItem.query.filter_by(user_id=current_user.id, store_id=store_id).first()
    qr_b64        = generate_qr_b64(request.host_url + f"store/{store_id}")
    recent_cheers = (Cheer.query.filter_by(store_id=store_id, is_shared=True)
                     .order_by(Cheer.created_at.desc()).limit(5).all())
    hours = []
    if store.opening_hours:
        try:
            hours = json.loads(store.opening_hours)
        except Exception:
            pass
    maps_embed_url = ""
    if store.lat and store.lng and get_gmaps_key():
        maps_embed_url = (f"https://www.google.com/maps/embed/v1/place"
                         f"?key={get_gmaps_key()}&q={store.lat},{store.lng}&zoom=16")
    return render_template("store_detail.html", store=store, in_list=in_list,
                           qr_b64=qr_b64, recent_cheers=recent_cheers,
                           hours=hours, maps_embed_url=maps_embed_url)


# ═══════════════════════════════════════════════════════════════════
# Cheer flow  (3 steps + send + complete)
# ═══════════════════════════════════════════════════════════════════

@app.route("/cheer/<int:store_id>/staff", methods=["GET", "POST"])
@login_required
def cheer_staff(store_id):
    store = Store.query.get_or_404(store_id)
    if request.method == "POST":
        staff_id = request.form.get("staff_id")
        session["cheer_store_id"] = store_id
        session["cheer_staff_id"] = int(staff_id) if staff_id else None
        return redirect(url_for("cheer_rating"))
    return render_template("cheer_staff.html", store=store)


@app.route("/cheer/rating", methods=["GET", "POST"])
@login_required
def cheer_rating():
    if "cheer_store_id" not in session:
        return redirect(url_for("home"))
    if request.method == "POST":
        session["cheer_service_rating"]   = int(request.form.get("service_rating", 5))
        session["cheer_atmosphere_rating"]= int(request.form.get("atmosphere_rating", 5))
        return redirect(url_for("cheer_goodpoints"))
    staff_id = session.get("cheer_staff_id")
    return render_template("cheer_rating.html",
                           staff=Staff.query.get(staff_id) if staff_id else None,
                           store=Store.query.get(session["cheer_store_id"]))


@app.route("/cheer/goodpoints", methods=["GET", "POST"])
@login_required
def cheer_goodpoints():
    if "cheer_store_id" not in session:
        return redirect(url_for("home"))
    if request.method == "POST":
        session["cheer_good_points"] = ",".join(request.form.getlist("good_points"))
        session["cheer_comment"]     = request.form.get("comment", "")
        session["cheer_is_shared"]   = request.form.get("is_shared") == "yes"
        return redirect(url_for("cheer_send"))
    staff_id = session.get("cheer_staff_id")
    return render_template("cheer_goodpoints.html",
                           staff=Staff.query.get(staff_id) if staff_id else None,
                           store=Store.query.get(session["cheer_store_id"]),
                           options=GOOD_POINT_OPTIONS)


@app.route("/cheer/send", methods=["GET", "POST"])
@login_required
def cheer_send():
    if "cheer_store_id" not in session:
        return redirect(url_for("home"))
    staff_id = session.get("cheer_staff_id")
    staff    = Staff.query.get(staff_id) if staff_id else None
    store    = Store.query.get(session["cheer_store_id"])
    today    = date.today()
    already  = CheerLimit.query.filter_by(
        user_id=current_user.id, store_id=store.id,
        staff_id=staff_id, cheer_date=today).first()

    if request.method == "POST":
        if already:
            flash("You already sent appreciation here today!", "error")
            return redirect(url_for("home"))
        if current_user.ticket_count < 1:
            flash("You need a cheer ticket.", "error")
            return redirect(url_for("mypage"))
        db.session.add(Cheer(
            user_id          = current_user.id,
            store_id         = store.id,
            staff_id         = staff_id,
            service_rating   = session.get("cheer_service_rating", 5),
            atmosphere_rating= session.get("cheer_atmosphere_rating", 5),
            good_points      = session.get("cheer_good_points", ""),
            comment          = session.get("cheer_comment", ""),
            is_shared        = session.get("cheer_is_shared", True),
            ticket_sent      = 1,
        ))
        current_user.ticket_count -= 1
        award_points_and_rank(current_user)
        db.session.add(CheerLimit(user_id=current_user.id, store_id=store.id,
                                  staff_id=staff_id, cheer_date=today))
        db.session.commit()
        for k in ["cheer_store_id", "cheer_staff_id", "cheer_service_rating",
                  "cheer_atmosphere_rating", "cheer_good_points",
                  "cheer_comment", "cheer_is_shared"]:
            session.pop(k, None)
        return redirect(url_for("cheer_complete"))

    return render_template("cheer_send.html", staff=staff, store=store,
                           already=already, tickets=current_user.ticket_count)


@app.route("/cheer/complete")
@login_required
def cheer_complete():
    return render_template("cheer_complete.html")


# ═══════════════════════════════════════════════════════════════════
# My page
# ═══════════════════════════════════════════════════════════════════

@app.route("/mypage")
@login_required
def mypage():
    cheers = (Cheer.query.filter_by(user_id=current_user.id)
              .order_by(Cheer.created_at.desc()).all())
    return render_template("mypage.html", cheers=cheers)


@app.route("/daily-ticket", methods=["POST"])
@login_required
def daily_ticket():
    today = date.today()
    if current_user.last_daily_ticket == today:
        return jsonify({"ok": False, "msg": "Already received today."})
    current_user.ticket_count      += 1
    current_user.last_daily_ticket  = today
    db.session.commit()
    return jsonify({"ok": True, "tickets": current_user.ticket_count})


@app.route("/redeem-points", methods=["POST"])
@login_required
def redeem_points():
    amount = int(request.form.get("amount", 0))
    if amount < 500 or current_user.hiitap_points < amount:
        flash("Minimum 500 points required.", "error")
    else:
        current_user.hiitap_points -= amount
        db.session.commit()
        flash(f"Redemption request for {amount} pts submitted!", "success")
    return redirect(url_for("mypage"))


# ═══════════════════════════════════════════════════════════════════
# List
# ═══════════════════════════════════════════════════════════════════

@app.route("/list")
@login_required
def my_list():
    tag_filter = request.args.get("tag", "")
    q          = ListItem.query.filter_by(user_id=current_user.id)
    if tag_filter:
        q = q.filter(ListItem.tags.ilike(f"%{tag_filter}%"))
    items    = q.order_by(ListItem.created_at.desc()).all()
    all_tags = sorted({t.strip() for item in
                       ListItem.query.filter_by(user_id=current_user.id).all()
                       if item.tags for t in item.tags.split(",")})
    return render_template("list.html", items=items,
                           all_tags=all_tags, tag_filter=tag_filter)


@app.route("/list/add/<int:store_id>", methods=["POST"])
@login_required
def list_add(store_id):
    if not ListItem.query.filter_by(user_id=current_user.id, store_id=store_id).first():
        db.session.add(ListItem(user_id=current_user.id, store_id=store_id,
                                tags=request.form.get("tags", ""),
                                memo=request.form.get("memo", "")))
        db.session.commit()
    return redirect(request.referrer or url_for("my_list"))


@app.route("/list/remove/<int:item_id>", methods=["POST"])
@login_required
def list_remove(item_id):
    item = ListItem.query.get_or_404(item_id)
    if item.user_id == current_user.id:
        db.session.delete(item)
        db.session.commit()
    return redirect(url_for("my_list"))


# ═══════════════════════════════════════════════════════════════════
# Misc
# ═══════════════════════════════════════════════════════════════════

@app.route("/qr/<int:store_id>")
def qr_scan(store_id):
    return redirect(url_for("store_detail", store_id=store_id))


@app.route("/avatar.svg")
def default_avatar():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
           '<circle cx="50" cy="50" r="50" fill="#F5E6E0"/>'
           '<circle cx="50" cy="38" r="18" fill="#E07050"/>'
           '<ellipse cx="50" cy="85" rx="28" ry="20" fill="#E07050"/></svg>')
    return Response(svg, mimetype="image/svg+xml")


# ═══════════════════════════════════════════════════════════════════
# Seed data
# ═══════════════════════════════════════════════════════════════════

def seed():
    if User.query.filter_by(email="demo@hiitap.com").first():
        return
    u = User(email="demo@hiitap.com", display_name="Demo User",
             ticket_count=5, status_points=120, hiitap_points=120)
    u.set_password("demo1234")
    db.session.add(u)

    demo_stores = [
        dict(name="GATE CAFE",           address="Narita Gateway Hotel, Chiba",
             category="Cafe",       is_affiliated=True,
             description="Stylish cafe inside Narita Gateway Hotel."),
        dict(name="Patagonia Shonan",     address="Shonan Terrace Mall, Kanagawa",
             category="Retail",     is_affiliated=True,
             description="Outdoor apparel with passionate staff."),
        dict(name="Kyokinna Premium",     address="Nagoya Station Towers Plaza",
             category="Restaurant", is_affiliated=True,
             description="Premium Japanese sweets cafe in Nagoya."),
    ]
    for sd in demo_stores:
        store = Store(**sd)
        db.session.add(store)
        db.session.flush()
        for name, bio in [("Alex Kim", "Coffee & travel lover"),
                          ("Maria Chen", "Expert barista")]:
            db.session.add(Staff(store_id=store.id, name=name, bio=bio))
    db.session.commit()


# ═══════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed()
        purge_expired_cache()
    app.run(debug=True, port=5000)
