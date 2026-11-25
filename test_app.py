import time
from datetime import datetime

import pytest

import app as appmod


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DB_PATH", str(tmp_path / "teste.db"))
    monkeypatch.setenv("SEED_EXEMPLOS", "0")
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def login(c):
    return c.post("/login", data={"usuario": appmod.APP_USER, "senha": appmod.APP_PASSWORD})


def novo_setor(c, nome="Protocolo", prefixo="P"):
    return c.post("/admin/servicos/add", data={"nome": nome, "prefixo": prefixo})


def retirar(c, sid=1, prioridade=0):
    return c.post("/totem/retirar", data={"servico_id": sid, "prioridade": prioridade})


def html(c, url):
    return c.get(url).get_data(as_text=True)


def atendente(c, guiche="2", sid=1):
    login(c)
    c.post("/atendimento/config", data={"guiche": guiche, "servico_id": sid})


def preparar(c):
    login(c)
    novo_setor(c)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.get_json()["status"] == "ok"


def test_paginas_publicas(client):
    for url in ["/", "/totem", "/painel", "/api/painel"]:
        assert client.get(url).status_code == 200


def test_areas_restritas_exigem_login(client):
    for url in ["/atendimento", "/admin", "/export.csv"]:
        r = client.get(url)
        assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_login_invalido(client):
    r = client.post("/login", data={"usuario": "x", "senha": "y"})
    assert "inválidos" in r.get_data(as_text=True)


def test_exemplos_criados_na_primeira_execucao(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DB_PATH", str(tmp_path / "novo.db"))
    monkeypatch.setenv("SEED_EXEMPLOS", "1")
    c = appmod.app.test_client()
    assert "Ouvidoria" in html(c, "/totem")


def test_cadastro_de_setor_e_validacoes(client):
    login(client)
    novo_setor(client)
    assert "Protocolo" in html(client, "/admin")
    novo_setor(client, "Outro", "p")
    assert "Já existe" in html(client, "/admin")
    novo_setor(client, "Inválido", "123")
    assert "prefixo de 1 a 3 letras" in html(client, "/admin")


def test_numeracao_sequencial(client):
    preparar(client)
    r1 = retirar(client)
    r2 = retirar(client)
    assert r1.status_code == 302
    assert "P-001" in html(client, r1.headers["Location"])
    assert "P-002" in html(client, r2.headers["Location"])


def test_numeracao_reinicia_no_dia_seguinte(client, monkeypatch):
    preparar(client)
    retirar(client)
    monkeypatch.setattr(appmod, "agora", lambda: datetime(2099, 1, 2, 9, 0))
    r = retirar(client)
    assert "P-001" in html(client, r.headers["Location"])


def test_setor_desativado_nao_gera_senha(client):
    preparar(client)
    client.post("/admin/servicos/1/alternar")
    assert "Protocolo" not in html(client, "/totem")
    assert "indisponível" in client.post("/totem/retirar", data={"servico_id": 1}, follow_redirects=True).get_data(as_text=True)


def test_prioritaria_e_chamada_primeiro(client):
    preparar(client)
    retirar(client, prioridade=0)   # P-001
    retirar(client, prioridade=1)   # P-002 prioritária
    atendente(client)
    client.post("/atendimento/chamar")
    assert client.get("/api/painel").get_json()["atual"]["codigo"] == "P-002"


def test_fluxo_completo_de_atendimento(client):
    preparar(client)
    r = retirar(client)
    atendente(client)
    client.post("/atendimento/chamar")
    api = client.get("/api/painel").get_json()
    assert api["atual"]["codigo"] == "P-001" and api["atual"]["guiche"] == "2"
    assert "Sua vez" in html(client, r.headers["Location"])
    client.post("/atendimento/finalizar")
    assert "concluído" in html(client, r.headers["Location"])


def test_nao_chama_outra_enquanto_ha_atual(client):
    preparar(client)
    retirar(client)
    retirar(client)
    atendente(client)
    client.post("/atendimento/chamar")
    client.post("/atendimento/chamar")
    assert "Finalize a senha atual" in html(client, "/atendimento")
    assert client.get("/api/painel").get_json()["atual"]["codigo"] == "P-001"


def test_chamar_sem_fila(client):
    preparar(client)
    atendente(client)
    client.post("/atendimento/chamar")
    assert "Não há senhas" in html(client, "/atendimento")


def test_rechamar_atualiza_a_chamada(client):
    preparar(client)
    retirar(client)
    atendente(client)
    client.post("/atendimento/chamar")
    antes = client.get("/api/painel").get_json()["atual"]["chamada_em"]
    time.sleep(0.01)
    client.post("/atendimento/rechamar")
    depois = client.get("/api/painel").get_json()["atual"]["chamada_em"]
    assert depois > antes


def test_nao_compareceu(client):
    preparar(client)
    r = retirar(client)
    atendente(client)
    client.post("/atendimento/chamar")
    client.post("/atendimento/ausente")
    assert "encerrada" in html(client, r.headers["Location"])


def test_resumo_do_dia(client):
    preparar(client)
    retirar(client)
    retirar(client)
    atendente(client)
    client.post("/atendimento/chamar")
    client.post("/atendimento/finalizar")
    pagina = html(client, "/admin")
    assert "Protocolo" in pagina and "min" in pagina


def test_exportar_csv(client):
    preparar(client)
    retirar(client)
    r = client.get("/export.csv")
    texto = r.get_data(as_text=True)
    assert r.mimetype == "text/csv" and "P-001" in texto and "Protocolo" in texto
