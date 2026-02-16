import os
import secrets
from datetime import datetime
from urllib.parse import urlparse
from flask import Flask, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# ---------------- CONFIG ----------------

load_dotenv()

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

database_url = os.getenv("DATABASE_URL")

# 🔥 Fix para Render (postgres:// -> postgresql://)
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

limiter = Limiter(get_remote_address, app=app)

# ---------------- MODELOS ----------------

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    plan = db.Column(db.String(20), default="free")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Link(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    original_url = db.Column(db.Text, nullable=False)
    clicks = db.Column(db.Integer, default=0)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Click(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    link_id = db.Column(db.Integer, db.ForeignKey("link.id"))
    ip = db.Column(db.String(50))
    user_agent = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# 🔥 CREAR TABLAS AUTOMÁTICAMENTE EN PRODUCCIÓN
@app.before_first_request
def create_tables():
    db.create_all()

# ---------------- LOGIN ----------------

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------------- UTILIDADES ----------------

def generar_codigo(longitud=6):
    caracteres = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return ''.join(secrets.choice(caracteres) for _ in range(longitud))

def url_valida(url):
    parsed = urlparse(url)
    return parsed.scheme in ["http", "https"] and parsed.netloc

# ---------------- RUTA HOME (EVITA 404 EN "/") ----------------

@app.route("/")
def home():
    return redirect(url_for("login"))

# ---------------- AUTH ----------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        password = generate_password_hash(request.form["password"])

        if User.query.filter_by(email=email).first():
            return "Usuario ya existe"

        user = User(email=email, password=password)
        db.session.add(user)
        db.session.commit()

        return redirect(url_for("login"))

    return """
    <h2>Registro</h2>
    <form method="POST">
        Email: <input name="email"><br>
        Password: <input name="password" type="password"><br>
        <button>Registrarse</button>
    </form>
    """

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for("dashboard"))

        return "Credenciales inválidas"

    return """
    <h2>Login</h2>
    <form method="POST">
        Email: <input name="email"><br>
        Password: <input name="password" type="password"><br>
        <button>Entrar</button>
    </form>
    """

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

# ---------------- DASHBOARD ----------------

@app.route("/dashboard", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per minute")
def dashboard():
    if request.method == "POST":
        original_url = request.form["url"]
        custom_code = request.form["code"]

        if not url_valida(original_url):
            return "URL inválida"

        if custom_code:
            if Link.query.filter_by(code=custom_code).first():
                return "Código ya existe"
            code = custom_code
        else:
            code = generar_codigo()
            while Link.query.filter_by(code=code).first():
                code = generar_codigo()

        link = Link(code=code, original_url=original_url, owner_id=current_user.id)
        db.session.add(link)
        db.session.commit()

    links = Link.query.filter_by(owner_id=current_user.id).all()

    html_links = ""
    for link in links:
        short_url = request.host_url + link.code
        html_links += f"""
        <div>
            <b>{short_url}</b><br>
            Clicks: {link.clicks}<br><br>
        </div>
        """

    return f"""
    <h2>Dashboard</h2>
    <form method="POST">
        URL: <input name="url"><br>
        Código personalizado: <input name="code"><br>
        <button>Crear Link</button>
    </form>
    <hr>
    {html_links}
    <br>
    <a href="/logout">Cerrar sesión</a>
    """

# ---------------- FAVICON ----------------

@app.route("/favicon.ico")
def favicon():
    return "", 204

# ---------------- REDIRECT ----------------

@app.route("/<string:code>")
def redirect_link(code):
    # evita conflictos con rutas reales
    if code in ["login", "register", "dashboard", "logout"]:
        return "Ruta no válida", 404

    link = Link.query.filter_by(code=code).first()

    if link:
        link.clicks += 1

        click = Click(
            link_id=link.id,
            ip=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )

        db.session.add(click)
        db.session.commit()

        return redirect(link.original_url)

    return "Link no encontrado", 404

# ---------------- RUN LOCAL ----------------

if __name__ == "__main__":
    app.run(debug=True)

