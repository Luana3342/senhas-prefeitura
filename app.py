import csv
import io
import os
import re
import sqlite3
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "troque-esta-chave")
DB_PATH = os.environ.get("DB_PATH", "senhas.db")
ORGAO = os.environ.get("ORGAO_NOME", "Prefeitura de São João da Boa Vista")
APP_USER = os.environ.get("APP_USER", "admin")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "prefeitura123")
TZ = ZoneInfo("America/Sao_Paulo")

# Setores de exemplo (cadastrados só na primeira execução; edite pela tela de Gestão).
EXEMPLOS = [("Protocolo e Atendimento Geral", "P"), ("Tributos e IPTU", "T"),
            ("Assistência Social", "A"), ("Ouvidoria", "O")]

SELECT_SENHA = ("SELECT s.*, v.nome AS servico, v.prefixo AS prefixo "
                "FROM senhas s JOIN servicos v ON v.id = s.servico_id ")


# ---------------------------------------------------------------- tempo
def agora():
    """Data e hora local de São Paulo (o servidor na nuvem roda em UTC)."""
    return datetime.now(TZ).replace(tzinfo=None)


def agora_iso():
    return agora().isoformat(timespec="microseconds")


def hoje():
    return agora().date().isoformat()


@app.template_filter("hora")
def filtro_hora(valor):
    return valor[11:16] if valor else ""


# ---------------------------------------------------------------- banco
def iniciar_banco(db):
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS servicos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE COLLATE NOCASE,
            prefixo TEXT NOT NULL UNIQUE,
            ativo INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS senhas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            servico_id INTEGER NOT NULL REFERENCES servicos(id),
            dia TEXT NOT NULL,
            numero INTEGER NOT NULL,
            prioridade INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'aguardando',
            guiche TEXT,
            criada_em TEXT NOT NULL,
            primeira_chamada_em TEXT,
            chamada_em TEXT,
            finalizada_em TEXT,
            UNIQUE (servico_id, dia, numero));
        CREATE INDEX IF NOT EXISTS ix_senhas_dia_status ON senhas(dia, status);
        """
    )
    if os.environ.get("SEED_EXEMPLOS", "1") == "1":
        if db.execute("SELECT COUNT(*) FROM servicos").fetchone()[0] == 0:
            db.executemany("INSERT INTO servicos (nome, prefixo) VALUES (?, ?)", EXEMPLOS)
            db.commit()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        iniciar_banco(g.db)
    return g.db


@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ---------------------------------------------------------------- utilidades
@app.context_processor
def contexto():
    return {"orgao": ORGAO, "logado": bool(session.get("logado"))}


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logado"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


def enriquecer(r):
    d = dict(r)
    d["codigo"] = f"{r['prefixo']}-{r['numero']:03d}"
    d["tipo"] = "Prioritária" if r["prioridade"] else "Normal"
    d["fala"] = f"Senha {r['prefixo']} {r['numero']}, guichê {r['guiche']}" if r["guiche"] else ""
    return d


def senha_atual(db, guiche):
    return db.execute(SELECT_SENHA + "WHERE s.dia=? AND s.status='chamada' AND s.guiche=? "
                      "ORDER BY s.chamada_em DESC LIMIT 1", (hoje(), guiche)).fetchone()


def pessoas_na_frente(db, s):
    if s["status"] != "aguardando":
        return 0
    if s["prioridade"]:
        sql = ("SELECT COUNT(*) FROM senhas WHERE servico_id=? AND dia=? AND status='aguardando' "
               "AND prioridade=1 AND id < ?")
    else:
        sql = ("SELECT COUNT(*) FROM senhas WHERE servico_id=? AND dia=? AND status='aguardando' "
               "AND (prioridade=1 OR id < ?)")
    return db.execute(sql, (s["servico_id"], s["dia"], s["id"])).fetchone()[0]


def minutos(inicio, fim):
    if not inicio or not fim:
        return None
    return (datetime.fromisoformat(fim) - datetime.fromisoformat(inicio)).total_seconds() / 60


def media(valores):
    valores = [v for v in valores if v is not None]
    return round(sum(valores) / len(valores), 1) if valores else None


def resumo_do_dia(db):
    servicos = db.execute("SELECT * FROM servicos ORDER BY nome").fetchall()
    senhas = db.execute("SELECT * FROM senhas WHERE dia=?", (hoje(),)).fetchall()
    linhas = []
    for sv in servicos:
        ss = [s for s in senhas if s["servico_id"] == sv["id"]]
        linhas.append({
            "nome": sv["nome"], "prefixo": sv["prefixo"],
            "emitidas": len(ss),
            "aguardando": sum(s["status"] == "aguardando" for s in ss),
            "finalizadas": sum(s["status"] == "finalizada" for s in ss),
            "ausentes": sum(s["status"] == "ausente" for s in ss),
            "espera": media([minutos(s["criada_em"], s["primeira_chamada_em"]) for s in ss]),
            "atendimento": media([minutos(s["primeira_chamada_em"], s["finalizada_em"])
                                  for s in ss if s["status"] == "finalizada"]),
        })
    return linhas


# ---------------------------------------------------------------- sistema
@app.route("/health")
def health():
    """Endpoint usado pelo monitoramento da nuvem."""
    try:
        get_db().execute("SELECT 1")
        return jsonify(status="ok"), 200
    except Exception:
        return jsonify(status="erro"), 500


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if (request.form.get("usuario") == APP_USER
                and request.form.get("senha") == APP_PASSWORD):
            session["logado"] = True
            destino = request.args.get("next", "")
            if not destino.startswith("/") or destino.startswith("//"):
                destino = url_for("atendimento")
            return redirect(destino)
        flash("Usuário ou senha inválidos.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/")
def home():
    return render_template("home.html")


# ---------------------------------------------------------------- cidadão (público)
@app.route("/totem")
def totem():
    servicos = get_db().execute("SELECT * FROM servicos WHERE ativo=1 ORDER BY nome").fetchall()
    return render_template("totem.html", servicos=servicos)


@app.route("/totem/retirar", methods=["POST"])
def retirar():
    db = get_db()
    servico = db.execute("SELECT * FROM servicos WHERE id=? AND ativo=1",
                         (request.form.get("servico_id", type=int),)).fetchone()
    if servico is None:
        flash("Setor indisponível. Escolha outro.")
        return redirect(url_for("totem"))
    prioridade = 1 if request.form.get("prioridade") == "1" else 0
    for _ in range(5):
        numero = db.execute("SELECT COALESCE(MAX(numero), 0) + 1 FROM senhas WHERE servico_id=? AND dia=?",
                            (servico["id"], hoje())).fetchone()[0]
        try:
            cur = db.execute(
                "INSERT INTO senhas (servico_id, dia, numero, prioridade, criada_em) VALUES (?,?,?,?,?)",
                (servico["id"], hoje(), numero, prioridade, agora_iso()))
            db.commit()
            return redirect(url_for("ver_senha", sid=cur.lastrowid))
        except sqlite3.IntegrityError:  # duas pessoas pegaram ao mesmo tempo: tenta de novo
            db.rollback()
    flash("Não foi possível gerar a senha. Tente novamente.")
    return redirect(url_for("totem"))


@app.route("/senha/<int:sid>")
def ver_senha(sid):
    db = get_db()
    row = db.execute(SELECT_SENHA + "WHERE s.id=?", (sid,)).fetchone()
    if row is None:
        abort(404)
    return render_template("senha.html", s=enriquecer(row), na_frente=pessoas_na_frente(db, row))


@app.route("/painel")
def painel():
    return render_template("painel.html")


@app.route("/api/painel")
def api_painel():
    db = get_db()
    rows = db.execute(SELECT_SENHA + "WHERE s.dia=? AND s.chamada_em IS NOT NULL "
                      "ORDER BY s.chamada_em DESC LIMIT 6", (hoje(),)).fetchall()
    chamadas = [enriquecer(r) for r in rows]
    aguardando = db.execute("SELECT COUNT(*) FROM senhas WHERE dia=? AND status='aguardando'",
                            (hoje(),)).fetchone()[0]
    return jsonify(atual=chamadas[0] if chamadas else None, ultimas=chamadas[1:], aguardando=aguardando)


# ---------------------------------------------------------------- atendente
@app.route("/atendimento")
@login_required
def atendimento():
    db = get_db()
    guiche, sid = session.get("guiche"), session.get("servico_id")
    servicos = db.execute("SELECT * FROM servicos WHERE ativo=1 ORDER BY nome").fetchall()
    servico = db.execute("SELECT * FROM servicos WHERE id=?", (sid,)).fetchone() if sid else None
    if not guiche or servico is None:
        return render_template("atendimento.html", configurado=False, servicos=servicos)
    atual = senha_atual(db, guiche)
    fila = db.execute(SELECT_SENHA + "WHERE s.servico_id=? AND s.dia=? AND s.status='aguardando' "
                      "ORDER BY s.prioridade DESC, s.id", (servico["id"], hoje())).fetchall()
    return render_template("atendimento.html", configurado=True, guiche=guiche, servico=servico,
                           atual=enriquecer(atual) if atual else None,
                           fila=[enriquecer(r) for r in fila[:12]], total=len(fila))


@app.route("/atendimento/config", methods=["POST"])
@login_required
def atendimento_config():
    guiche = " ".join(request.form.get("guiche", "").split())[:20]
    servico = get_db().execute("SELECT id FROM servicos WHERE id=? AND ativo=1",
                               (request.form.get("servico_id", type=int),)).fetchone()
    if not guiche or servico is None:
        flash("Informe o guichê e escolha o setor.")
    else:
        session["guiche"], session["servico_id"] = guiche, servico["id"]
    return redirect(url_for("atendimento"))


@app.route("/atendimento/trocar", methods=["POST"])
@login_required
def atendimento_trocar():
    session.pop("guiche", None)
    session.pop("servico_id", None)
    return redirect(url_for("atendimento"))


@app.route("/atendimento/chamar", methods=["POST"])
@login_required
def atendimento_chamar():
    db = get_db()
    guiche, sid = session.get("guiche"), session.get("servico_id")
    if not guiche or not sid:
        return redirect(url_for("atendimento"))
    if senha_atual(db, guiche):
        flash("Finalize a senha atual antes de chamar a próxima.")
        return redirect(url_for("atendimento"))
    for _ in range(3):
        prox = db.execute("SELECT id FROM senhas WHERE servico_id=? AND dia=? AND status='aguardando' "
                          "ORDER BY prioridade DESC, id LIMIT 1", (sid, hoje())).fetchone()
        if prox is None:
            flash("Não há senhas aguardando.")
            break
        agora_ = agora_iso()
        cur = db.execute("UPDATE senhas SET status='chamada', guiche=?, chamada_em=?, "
                         "primeira_chamada_em=? WHERE id=? AND status='aguardando'",
                         (guiche, agora_, agora_, prox["id"]))
        db.commit()
        if cur.rowcount:
            break
    return redirect(url_for("atendimento"))


def _acao_na_atual(acao):
    db = get_db()
    guiche = session.get("guiche")
    atual = senha_atual(db, guiche) if guiche else None
    if atual is not None:
        if acao == "rechamar":
            db.execute("UPDATE senhas SET chamada_em=? WHERE id=?", (agora_iso(), atual["id"]))
        else:
            novo = "finalizada" if acao == "finalizar" else "ausente"
            db.execute("UPDATE senhas SET status=?, finalizada_em=? WHERE id=?",
                       (novo, agora_iso(), atual["id"]))
        db.commit()
    return redirect(url_for("atendimento"))


@app.route("/atendimento/rechamar", methods=["POST"])
@login_required
def atendimento_rechamar():
    return _acao_na_atual("rechamar")


@app.route("/atendimento/finalizar", methods=["POST"])
@login_required
def atendimento_finalizar():
    return _acao_na_atual("finalizar")


@app.route("/atendimento/ausente", methods=["POST"])
@login_required
def atendimento_ausente():
    return _acao_na_atual("ausente")


# ---------------------------------------------------------------- gestão
@app.route("/admin")
@login_required
def admin():
    db = get_db()
    servicos = db.execute("SELECT * FROM servicos ORDER BY nome").fetchall()
    return render_template("admin.html", servicos=servicos, resumo=resumo_do_dia(db), dia=hoje())


@app.route("/admin/servicos/add", methods=["POST"])
@login_required
def servico_add():
    nome = " ".join(request.form.get("nome", "").split())
    prefixo = request.form.get("prefixo", "").strip().upper()
    if not nome or not re.fullmatch(r"[A-Z]{1,3}", prefixo):
        flash("Informe o nome do setor e um prefixo de 1 a 3 letras (ex.: P).")
        return redirect(url_for("admin"))
    try:
        db = get_db()
        db.execute("INSERT INTO servicos (nome, prefixo) VALUES (?, ?)", (nome, prefixo))
        db.commit()
    except sqlite3.IntegrityError:
        flash("Já existe um setor com esse nome ou prefixo.")
    return redirect(url_for("admin"))


@app.route("/admin/servicos/<int:sid>/alternar", methods=["POST"])
@login_required
def servico_alternar(sid):
    db = get_db()
    db.execute("UPDATE servicos SET ativo = 1 - ativo WHERE id=?", (sid,))
    db.commit()
    return redirect(url_for("admin"))


@app.route("/export.csv")
@login_required
def export():
    sql = SELECT_SENHA
    args = ()
    if request.args.get("dia") != "todos":
        sql += "WHERE s.dia=? "
        args = (hoje(),)
    rows = get_db().execute(sql + "ORDER BY s.dia, s.id", args).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Dia", "Setor", "Senha", "Tipo", "Status", "Guichê", "Retirada", "Chamada", "Finalizada"])
    for r in rows:
        d = enriquecer(r)
        w.writerow([d["dia"], d["servico"], d["codigo"], d["tipo"], d["status"], d["guiche"] or "",
                    filtro_hora(d["criada_em"]), filtro_hora(d["primeira_chamada_em"]),
                    filtro_hora(d["finalizada_em"])])
    return Response("\ufeff" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=senhas.csv"})


if __name__ == "__main__":
    app.run(debug=True)
