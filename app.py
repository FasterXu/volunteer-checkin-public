import csv
import hmac
import io
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import qrcode
from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from openpyxl import load_workbook


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("SIGNIN_DATABASE", BASE_DIR / "data" / "signin.db"))


def now_text():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def csv_safe(value):
    """Prevent spreadsheet formula execution when exported CSV is opened."""
    text = str(value or "")
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


@contextmanager
def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                location TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                start_time TEXT,
                end_time TEXT,
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK(status IN ('draft', 'active', 'ended')),
                code TEXT NOT NULL UNIQUE,
                observer_token TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                identifier TEXT NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                position TEXT NOT NULL DEFAULT '',
                signed_in INTEGER NOT NULL DEFAULT 0 CHECK(signed_in IN (0, 1)),
                sign_time TEXT,
                source TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                UNIQUE(activity_id, identifier)
            );

            CREATE INDEX IF NOT EXISTS idx_participants_activity_signed
            ON participants(activity_id, signed_in);
            """
        )
        participant_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(participants)").fetchall()
        }
        if "position" not in participant_columns:
            db.execute(
                "ALTER TABLE participants ADD COLUMN position TEXT NOT NULL DEFAULT ''"
            )
        activity_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(activities)").fetchall()
        }
        if "observer_token" not in activity_columns:
            db.execute(
                "ALTER TABLE activities ADD COLUMN observer_token TEXT NOT NULL DEFAULT ''"
            )
        used_tokens = set()
        activities = db.execute(
            "SELECT id, observer_token FROM activities ORDER BY id"
        ).fetchall()
        for activity in activities:
            token = activity["observer_token"] or ""
            if not token or token in used_tokens:
                token = secrets.token_urlsafe(24)
                while token in used_tokens:
                    token = secrets.token_urlsafe(24)
                db.execute(
                    "UPDATE activities SET observer_token = ? WHERE id = ?",
                    (token, activity["id"]),
                )
            used_tokens.add(token)
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_activities_observer_token "
            "ON activities(observer_token)"
        )


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-change-me-" + secrets.token_hex(8))
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
init_db()


PUBLIC_ENDPOINTS = {
    "sign_page",
    "submit_sign",
    "observer_page",
    "observer_participants_api",
    "observer_export_results",
    "healthz",
    "static",
    "login",
}


@app.before_request
def require_admin_login():
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not password or request.endpoint in PUBLIC_ENDPOINTS or session.get("admin_authenticated"):
        return None
    if request.path.startswith(("/api/", "/participants/")):
        return jsonify({"ok": False, "message": "登录已过期，请刷新页面重新登录。"}), 401
    return redirect(url_for("login", next=request.full_path))


@app.context_processor
def auth_context():
    return {"auth_enabled": bool(os.environ.get("ADMIN_PASSWORD"))}


def get_activity(activity_id):
    with get_db() as db:
        activity = db.execute("SELECT * FROM activities WHERE id = ?", (activity_id,)).fetchone()
    if activity is None:
        abort(404)
    return activity


def get_observer_activity(token):
    with get_db() as db:
        activity = db.execute(
            "SELECT * FROM activities WHERE observer_token = ?", (token,)
        ).fetchone()
    if activity is None:
        abort(404)
    return activity


def roster_rows(upload):
    suffix = Path(upload.filename or "").suffix.lower()
    data = upload.read()
    if suffix == ".csv":
        decoded = None
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                decoded = data.decode(encoding)
                break
            except UnicodeDecodeError:
                pass
        if decoded is None:
            raise ValueError("CSV 编码无法识别，请使用 UTF-8 或 GB18030。")
        return list(csv.reader(io.StringIO(decoded)))
    if suffix == ".xlsx":
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sheet = workbook.active
        return [["" if cell is None else str(cell).strip() for cell in row] for row in sheet.iter_rows(values_only=True)]
    raise ValueError("仅支持 CSV 或 XLSX 文件。")


HEADER_ALIASES = {
    "name": {"姓名", "名字", "name"},
    "identifier": {"学号", "工号", "学号/工号", "编号", "id", "identifier"},
    "phone": {"手机号", "手机", "联系电话", "电话", "phone", "mobile"},
    "position": {"岗位", "职位", "职务", "position", "role"},
}


def parse_roster(upload):
    rows = roster_rows(upload)
    if not rows:
        raise ValueError("名单为空。")
    headers = [str(value).strip().lower().replace(" ", "") for value in rows[0]]
    indexes = {}
    for key, aliases in HEADER_ALIASES.items():
        aliases_lower = {item.lower().replace(" ", "") for item in aliases}
        for index, header in enumerate(headers):
            if header in aliases_lower:
                indexes[key] = index
                break
    if "name" not in indexes or "identifier" not in indexes:
        raise ValueError("缺少必填表头：姓名、学号/工号。")

    parsed = []
    for line_number, row in enumerate(rows[1:], start=2):
        values = [str(value).strip() for value in row]
        name = values[indexes["name"]] if indexes["name"] < len(values) else ""
        identifier = values[indexes["identifier"]] if indexes["identifier"] < len(values) else ""
        phone_index = indexes.get("phone")
        phone = values[phone_index] if phone_index is not None and phone_index < len(values) else ""
        position_index = indexes.get("position")
        position = (
            values[position_index]
            if position_index is not None and position_index < len(values)
            else ""
        )
        if not name and not identifier:
            continue
        if not name or not identifier:
            raise ValueError(f"第 {line_number} 行缺少姓名或学号/工号。")
        parsed.append((name, identifier, phone, position))
    if not parsed:
        raise ValueError("名单中没有有效数据。")
    return parsed


@app.template_filter("display_time")
def display_time(value):
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%m-%d %H:%M:%S")
    except ValueError:
        return value


@app.get("/")
def index():
    return redirect(url_for("admin"))


@app.route("/login", methods=["GET", "POST"])
def login():
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        return redirect(url_for("admin"))
    if request.method == "POST":
        supplied = request.form.get("password", "")
        if hmac.compare_digest(supplied, password):
            session.clear()
            session["admin_authenticated"] = True
            target = request.form.get("next", "")
            if not target.startswith("/") or target.startswith("//"):
                target = url_for("admin")
            return redirect(target)
        flash("管理员密码不正确。", "danger")
    return render_template("login.html", next=request.args.get("next", ""), public_page=True)


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/healthz")
def healthz():
    with get_db() as db:
        db.execute("SELECT 1").fetchone()
    return jsonify({"ok": True})


@app.get("/admin")
def admin():
    selected_id = request.args.get("activity_id", type=int)
    with get_db() as db:
        activities = db.execute(
            """
            SELECT a.*, COUNT(p.id) AS total,
                   SUM(CASE WHEN p.signed_in = 1 THEN 1 ELSE 0 END) AS signed
            FROM activities a LEFT JOIN participants p ON p.activity_id = a.id
            GROUP BY a.id ORDER BY a.created_at DESC
            """
        ).fetchall()
        if selected_id:
            activity = db.execute("SELECT * FROM activities WHERE id = ?", (selected_id,)).fetchone()
        else:
            activity = db.execute(
                "SELECT * FROM activities ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
    return render_template("admin.html", activities=activities, activity=activity)


@app.post("/activities")
def create_activity():
    name = request.form.get("name", "").strip()
    if not name:
        flash("请填写活动名称。", "danger")
        return redirect(url_for("admin"))
    code = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8].upper()
    observer_token = secrets.token_urlsafe(24)
    with get_db() as db:
        cursor = db.execute(
            """
            INSERT INTO activities(
                name, location, description, start_time, end_time, status,
                code, observer_token, created_at
            )
            VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?)
            """,
            (
                name,
                request.form.get("location", "").strip(),
                request.form.get("description", "").strip(),
                request.form.get("start_time") or None,
                request.form.get("end_time") or None,
                code,
                observer_token,
                now_text(),
            ),
        )
        activity_id = cursor.lastrowid
    flash("活动已创建，请上传名单并启动活动。", "success")
    return redirect(url_for("admin", activity_id=activity_id))


@app.post("/activities/<int:activity_id>/status")
def set_activity_status(activity_id):
    get_activity(activity_id)
    status = request.form.get("status")
    if status not in {"draft", "active", "ended"}:
        abort(400)
    with get_db() as db:
        db.execute("UPDATE activities SET status = ? WHERE id = ?", (status, activity_id))
    labels = {"draft": "准备中", "active": "进行中", "ended": "已结束"}
    flash(f"活动状态已更新为“{labels[status]}”。", "success")
    return redirect(url_for("admin", activity_id=activity_id))


@app.post("/activities/<int:activity_id>/edit")
def edit_activity(activity_id):
    get_activity(activity_id)
    name = request.form.get("name", "").strip()
    start_time = request.form.get("start_time") or None
    end_time = request.form.get("end_time") or None
    if not name:
        flash("活动名称不能为空。", "danger")
        return redirect(url_for("admin", activity_id=activity_id))
    try:
        if start_time:
            datetime.fromisoformat(start_time)
        if end_time:
            datetime.fromisoformat(end_time)
        if start_time and end_time and datetime.fromisoformat(end_time) < datetime.fromisoformat(start_time):
            raise ValueError("结束时间不能早于开始时间。")
    except ValueError as error:
        message = str(error) if str(error) == "结束时间不能早于开始时间。" else "活动时间格式不正确。"
        flash(message, "danger")
        return redirect(url_for("admin", activity_id=activity_id))
    with get_db() as db:
        db.execute(
            """
            UPDATE activities
            SET name = ?, location = ?, description = ?, start_time = ?, end_time = ?
            WHERE id = ?
            """,
            (
                name,
                request.form.get("location", "").strip(),
                request.form.get("description", "").strip(),
                start_time,
                end_time,
                activity_id,
            ),
        )
    flash("活动信息已更新。", "success")
    return redirect(url_for("admin", activity_id=activity_id))


@app.post("/activities/<int:activity_id>/upload")
def upload_roster(activity_id):
    get_activity(activity_id)
    upload = request.files.get("roster")
    if not upload or not upload.filename:
        flash("请选择 CSV 或 XLSX 名单。", "danger")
        return redirect(url_for("admin", activity_id=activity_id))
    try:
        rows = parse_roster(upload)
        with get_db() as db:
            for name, identifier, phone, position in rows:
                db.execute(
                    """
                    INSERT INTO participants(
                        activity_id, name, identifier, phone, position, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(activity_id, identifier) DO UPDATE SET
                        name = excluded.name,
                        phone = excluded.phone,
                        position = excluded.position,
                        updated_at = excluded.updated_at
                    """,
                    (activity_id, name, identifier, phone, position, now_text()),
                )
        flash(f"名单导入完成，共处理 {len(rows)} 人；重复编号已更新，签到状态予以保留。", "success")
    except (ValueError, OSError) as error:
        flash(str(error), "danger")
    return redirect(url_for("admin", activity_id=activity_id))


@app.get("/sign/<code>")
def sign_page(code):
    with get_db() as db:
        activity = db.execute("SELECT * FROM activities WHERE code = ?", (code.upper(),)).fetchone()
    if activity is None:
        abort(404)
    return render_template("sign.html", activity=activity, public_page=True)


@app.post("/sign/<code>")
def submit_sign(code):
    identifier = request.form.get("identifier", "").strip()
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    note = request.form.get("note", "").strip()[:200]
    with get_db() as db:
        activity = db.execute("SELECT * FROM activities WHERE code = ?", (code.upper(),)).fetchone()
        if activity is None:
            abort(404)
        if activity["status"] != "active":
            flash("当前活动尚未开始或已经结束，暂不能签到。", "danger")
            return redirect(url_for("sign_page", code=code))
        participant = db.execute(
            "SELECT * FROM participants WHERE activity_id = ? AND identifier = ?",
            (activity["id"], identifier),
        ).fetchone()
        if participant is None:
            flash("名单中未找到该学号/工号，请联系现场管理员。", "danger")
        elif participant["name"].strip().lower() != name.lower():
            flash("姓名与名单不匹配，请检查后重试。", "danger")
        elif participant["phone"] and phone and participant["phone"] != phone:
            flash("手机号与名单不匹配，请检查后重试。", "danger")
        else:
            cursor = db.execute(
                """
                UPDATE participants
                SET signed_in = 1, sign_time = ?, source = '扫码签到', note = ?, updated_at = ?
                WHERE id = ? AND signed_in = 0
                """,
                (now_text(), note, now_text(), participant["id"]),
            )
            if cursor.rowcount == 0:
                flash(f"{participant['name']} 已完成签到，无需重复操作。", "info")
            else:
                flash(f"签到成功，欢迎你，{participant['name']}！", "success")
    return redirect(url_for("sign_page", code=code))


@app.get("/activities/<int:activity_id>/qr.png")
def activity_qr(activity_id):
    activity = get_activity(activity_id)
    public_base = os.environ.get("PUBLIC_BASE_URL", request.url_root.rstrip("/"))
    sign_url = f"{public_base}/sign/{activity['code']}"
    qr = qrcode.QRCode(version=None, box_size=8, border=3)
    qr.add_data(sign_url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="#000000", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return send_file(buffer, mimetype="image/png", download_name=f"{activity['code']}.png")


@app.get("/api/activities/<int:activity_id>/participants")
def participants_api(activity_id):
    get_activity(activity_id)
    status = request.args.get("status", "all")
    search = request.args.get("q", "").strip()
    return jsonify(participant_payload(activity_id, status, search))


def participant_payload(activity_id, status="all", search=""):
    conditions = ["activity_id = ?"]
    params = [activity_id]
    if status == "signed":
        conditions.append("signed_in = 1")
    elif status == "unsigned":
        conditions.append("signed_in = 0")
    if search:
        conditions.append(
            "(name LIKE ? OR identifier LIKE ? OR phone LIKE ? OR position LIKE ?)"
        )
        term = f"%{search}%"
        params.extend([term, term, term, term])
    where = " AND ".join(conditions)
    with get_db() as db:
        counts = db.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN signed_in = 1 THEN 1 ELSE 0 END) AS signed
            FROM participants WHERE activity_id = ?
            """,
            (activity_id,),
        ).fetchone()
        rows = db.execute(
            f"SELECT * FROM participants WHERE {where} ORDER BY signed_in ASC, name COLLATE NOCASE ASC",
            params,
        ).fetchall()
    total = counts["total"] or 0
    signed = counts["signed"] or 0
    return {
        "summary": {
            "total": total,
            "signed": signed,
            "unsigned": total - signed,
            "rate": round(signed * 100 / total, 1) if total else 0,
        },
        "participants": [dict(row) for row in rows],
    }


@app.get("/observe/<token>")
def observer_page(token):
    activity = get_observer_activity(token)
    return render_template("observer.html", activity=activity, public_page=True)


@app.get("/observe/<token>/participants")
def observer_participants_api(token):
    activity = get_observer_activity(token)
    status = request.args.get("status", "all")
    search = request.args.get("q", "").strip()
    payload = participant_payload(activity["id"], status, search)
    visible_fields = (
        "name",
        "identifier",
        "phone",
        "position",
        "signed_in",
        "sign_time",
        "source",
        "note",
    )
    payload["participants"] = [
        {field: participant[field] for field in visible_fields}
        for participant in payload["participants"]
    ]
    return jsonify(payload)


@app.post("/participants/<int:participant_id>/toggle")
def toggle_participant(participant_id):
    payload = request.get_json(silent=True) or request.form
    signed = str(payload.get("signed", "")).lower() in {"1", "true", "yes"}
    note = str(payload.get("note", "")).strip()[:200]
    with get_db() as db:
        participant = db.execute("SELECT * FROM participants WHERE id = ?", (participant_id,)).fetchone()
        if participant is None:
            abort(404)
        if signed:
            db.execute(
                """
                UPDATE participants SET signed_in = 1, sign_time = ?, source = '管理员补签',
                       note = ?, updated_at = ? WHERE id = ?
                """,
                (now_text(), note, now_text(), participant_id),
            )
        else:
            db.execute(
                """
                UPDATE participants SET signed_in = 0, sign_time = NULL, source = '管理员取消',
                       note = ?, updated_at = ? WHERE id = ?
                """,
                (note, now_text(), participant_id),
            )
    return jsonify({"ok": True})


@app.patch("/participants/<int:participant_id>")
def edit_participant(participant_id):
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    identifier = str(payload.get("identifier", "")).strip()
    phone = str(payload.get("phone", "")).strip()
    position = str(payload.get("position", "")).strip()[:100]
    note = str(payload.get("note", "")).strip()[:200]
    if not name or not identifier:
        return jsonify({"ok": False, "message": "姓名和学号/工号不能为空。"}), 400
    with get_db() as db:
        participant = db.execute("SELECT * FROM participants WHERE id = ?", (participant_id,)).fetchone()
        if participant is None:
            abort(404)
        try:
            db.execute(
                """
                UPDATE participants
                SET name = ?, identifier = ?, phone = ?, position = ?, note = ?, updated_at = ?
                WHERE id = ?
                """,
                (name, identifier, phone, position, note, now_text(), participant_id),
            )
        except sqlite3.IntegrityError:
            return jsonify({"ok": False, "message": "该学号/工号已存在于本活动名单中。"}), 409
    return jsonify({"ok": True})


@app.delete("/participants/<int:participant_id>")
def delete_participant(participant_id):
    with get_db() as db:
        participant = db.execute("SELECT id FROM participants WHERE id = ?", (participant_id,)).fetchone()
        if participant is None:
            abort(404)
        db.execute("DELETE FROM participants WHERE id = ?", (participant_id,))
    return jsonify({"ok": True})


@app.get("/activities/<int:activity_id>/export.csv")
def export_results(activity_id):
    activity = get_activity(activity_id)
    status = request.args.get("status", "all")
    return export_response(activity, status)


@app.get("/observe/<token>/export.csv")
def observer_export_results(token):
    activity = get_observer_activity(token)
    status = request.args.get("status", "all")
    return export_response(activity, status)


def export_response(activity, status="all"):
    condition = " AND signed_in = 0" if status == "unsigned" else ""
    with get_db() as db:
        rows = db.execute(
            f"SELECT * FROM participants WHERE activity_id = ?{condition} ORDER BY name COLLATE NOCASE",
            (activity["id"],),
        ).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["姓名", "学号/工号", "手机号", "岗位", "签到状态", "签到时间", "来源", "备注"])
    for row in rows:
        writer.writerow(
            [
                csv_safe(row["name"]),
                csv_safe(row["identifier"]),
                csv_safe(row["phone"]),
                csv_safe(row["position"]),
                "已签到" if row["signed_in"] else "未签到",
                row["sign_time"] or "",
                csv_safe(row["source"]),
                csv_safe(row["note"]),
            ]
        )
    filename = f"{activity['name']}-签到结果.csv"
    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.errorhandler(413)
def too_large(_error):
    return "上传文件不能超过 8 MB。", 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("FLASK_DEBUG") == "1")
