"""Flask app: RAG-augmented NCERT tutor.

Per browser session (signed cookie), the app keeps a short rolling chat
history in memory. Each turn: embed the question -> retrieve top NCERT
chunks from Qdrant -> stream a Gemini answer grounded in those chunks.
"""
import json
import logging
import uuid

import google.generativeai as genai
from flask import Flask, Response, render_template, request, session, stream_with_context, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from pymongo.errors import PyMongoError

from config import config
from rag.retriever import retrieve, format_context
from models import (
    AuthenticationConfigurationError,
    User,
    create_user,
    get_user_by_id,
    get_user_by_username,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ncert-tutor")

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY

# Setup Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # type: ignore

@login_manager.user_loader
def load_user(user_id):
    return get_user_by_id(user_id)


def _auth_storage_unavailable(template: str):
    log.exception("MongoDB authentication request failed")
    flash(
        "Account storage is unavailable. Check MONGODB_URI and MongoDB Atlas network access.",
        "error",
    )
    return render_template(template), 503


genai.configure(api_key=config.GEMINI_API_KEY)

SYSTEM_INSTRUCTION = """You are a patient, encouraging mentor for a higher-secondary (class 11-12) \
student studying Mathematics, Physics, and Chemistry from the NCERT curriculum.

You will usually be given "Textbook context" retrieved from the student's NCERT PDFs, numbered [1], [2], etc.
- Ground your explanation in that context whenever it's relevant, and cite it inline like [1] when you use it.
- If the context doesn't actually cover the question, say so plainly and then help using your general \
knowledge instead of pretending the textbook covered it.
- Never invent a citation number that wasn't given to you.
- Explain step by step, check the student's understanding, and keep an encouraging tone without being \
saccharine. Use worked examples where useful. Use $...$ for inline LaTeX and $$...$$ for block LaTeX.
"""

model = genai.GenerativeModel(
    model_name=config.GEMINI_CHAT_MODEL,
    system_instruction=SYSTEM_INSTRUCTION,
    safety_settings=[
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    ],
    generation_config={
        "temperature": 0.4,
        "top_p": 0.95,
        "max_output_tokens": 4096,
    },
)

# session_id -> list of {"role": "user"|"model", "text": str}
# In-memory and per-process: fine for a single-instance demo. For multi-worker
# production deployments, swap this dict for Redis (see README).
HISTORY: dict[str, list[dict]] = {}
MAX_TURNS_KEPT = 8  # user+model pairs kept per session, to bound prompt size


def get_session_id() -> str:
    if "sid" not in session:
        session["sid"] = str(uuid.uuid4())
    return session["sid"]


def build_contents(history: list[dict], context_block: str, question: str) -> list[dict]:
    contents = [{"role": h["role"], "parts": [h["text"]]} for h in history]
    if context_block:
        user_turn = f"Textbook context:\n{context_block}\n\nStudent question: {question}"
    else:
        user_turn = (
            f"(No matching textbook context was found for this question.)\n\nStudent question: {question}"
        )
    contents.append({"role": "user", "parts": [user_turn]})
    return contents


@app.route("/")
def home():
    if current_user.is_authenticated:
        return render_template("index.html", subjects=config.SUBJECTS, grades=config.GRADES)
    return redirect(url_for('login'))

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Please provide both username and password", "error")
            return render_template("login.html")

        try:
            user = get_user_by_username(username)
        except (AuthenticationConfigurationError, PyMongoError):
            return _auth_storage_unavailable("login.html")

        if user and user.check_password(password):
            session.clear()
            login_user(user)
            return redirect(url_for('home'))
        else:
            flash("Invalid username or password", "error")

    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or not password or not confirm_password:
            flash("Please fill in all fields", "error")
            return render_template("register.html")

        valid_username = (
            3 <= len(username) <= 32
            and username.isascii()
            and username.replace("_", "").isalnum()
        )
        if not valid_username:
            flash("Username must be 3–32 characters using letters, numbers, or underscores", "error")
            return render_template("register.html")

        if len(password) < 8:
            flash("Password must be at least 8 characters", "error")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match", "error")
            return render_template("register.html")

        try:
            user = create_user(username, password)
        except (AuthenticationConfigurationError, PyMongoError):
            return _auth_storage_unavailable("register.html")

        if user is None:
            flash("Username already exists", "error")
            return render_template("register.html")

        session.clear()
        login_user(user)
        return redirect(url_for('home'))

    return render_template("register.html")

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route("/api/chat", methods=["POST"])
@login_required
def chat():
    data = request.get_json(force=True, silent=True) or {}
    question = (data.get("message") or "").strip()
    subject = data.get("subject") or "all"
    grade = data.get("grade") or "all"

    if not question:
        return {"error": "No message provided"}, 400
    if not config.GEMINI_API_KEY:
        return {"error": "Server is missing GEMINI_API_KEY. See .env.example."}, 500

    sid = get_session_id()
    history = HISTORY.setdefault(sid, [])

    try:
        chunks = retrieve(question, subject=subject, grade=grade)
    except Exception as e:
        log.exception("retrieval failed")
        chunks = []
        retrieval_error = str(e)
    else:
        retrieval_error = None

    context_block = format_context(chunks)
    contents = build_contents(history, context_block, question)

    sources = [
        {
            "n": i + 1,
            "subject": c.subject,
            "grade": c.grade,
            "chapter": c.chapter,
            "page": c.page,
            "source_file": c.source_file,
            "score": round(c.score, 3),
            "images": c.images,  # list of image URLs
            "models": c.models,  # list of 3D model URLs
        }
        for i, c in enumerate(chunks)
    ]

    def generate():
        full_answer = []
        try:
            if retrieval_error:
                yield _sse("meta", {"warning": f"Retrieval unavailable ({retrieval_error}); "
                                                "answering from general knowledge only."})
            yield _sse("sources", {"sources": sources})

            response = model.generate_content(contents, stream=True)
            for chunk in response:
                if chunk.text:
                    full_answer.append(chunk.text)
                    yield _sse("token", {"text": chunk.text})
        except Exception as e:
            log.exception("generation failed")
            yield _sse("error", {"message": f"Generation failed: {e}"})
            return
        finally:
            answer_text = "".join(full_answer)
            if answer_text:
                history.append({"role": "user", "text": question})
                history.append({"role": "model", "text": answer_text})
                del history[: max(0, len(history) - MAX_TURNS_KEPT * 2)]
            yield _sse("done", {})

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/reset", methods=["POST"])
@login_required
def reset():
    sid = get_session_id()
    HISTORY.pop(sid, None)
    return {"ok": True}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


if __name__ == "__main__":
    missing = config.validate()
    if missing:
        log.warning("Missing required env vars: %s (see .env.example)", ", ".join(missing))
    app.run(debug=True, port=5000)