# Sistema de Senhas de Atendimento — Prefeitura de São João da Boa Vista
Projeto desenvolvido por Luana da Silva Araújo, estudante de Análise e Desenvolvimento de Sistemas (UNIFEOB).

Aplicação web (Flask + SQLite, Python 3.15) para organizar a fila de atendimento ao cidadão.

## Telas
| Tela | Endereço | Quem usa | Login |
|---|---|---|---|
| Retirar senha (totem) | `/totem` | cidadão | não |
| Acompanhar senha | `/senha/<id>` | cidadão (imprimir ou ver no celular) | não |
| Painel de chamadas (TV) | `/painel` | recepção, com aviso de voz | não |
| Atendimento | `/atendimento` | atendente: chamar, chamar novamente, finalizar, não compareceu | sim |
| Gestão | `/admin` | setores, resumo do dia, exportar CSV | sim |

## Regras do sistema
- Numeração por setor, reiniciada todo dia (ex.: `P-001`, `T-014`), no horário de São Paulo.
- Senhas **prioritárias** (60+, gestantes, lactantes, pessoas com deficiência, criança de colo) são chamadas antes das normais.
- **Não guarda dados pessoais** (nome, CPF etc.), apenas número, setor, horários e guichê.
- Painel atualiza sozinho a cada 3 segundos; clique em "Ativar som" na TV para o aviso de voz.

## Rodar no seu computador
```bash
pip install -r requirements.txt
pytest                 # 17 testes
python app.py          # http://127.0.0.1:5000  (admin / prefeitura123)
```
Para ver o painel funcionando: abra `/painel` em uma aba, `/totem` em outra e `/atendimento` em uma terceira.

## Publicar na nuvem (Render)
1. Envie o projeto para um repositório no GitHub.
2. Render → **New → Web Service** → escolha o repositório.
3. Build Command: `pip install -r requirements.txt` · Start Command: `gunicorn app:app` · Health Check Path: `/health`.
4. Variáveis de ambiente: `PYTHON_VERSION` = `3.15.2` (se falhar, use `3.14.3`), `SECRET_KEY`, `APP_USER`, `APP_PASSWORD`.
   Opcional: `ORGAO_NOME` (nome exibido) e `SEED_EXEMPLOS=0` (para não criar os setores de exemplo).
5. Cada `git push` na `main` roda os testes (GitHub Actions) e faz o deploy automático.

## Limitações (para uso real)
- No plano gratuito o banco SQLite é apagado a cada deploy. Em uso real, usar banco persistente (ex.: PostgreSQL) e backup.
- Um único login para atendentes e gestão. Em uso real, um login por pessoa.
- Qualquer pessoa com o link do `/totem` pode gerar senhas. Em uso real, restringir ao equipamento do local.
- Os setores de exemplo (Protocolo, Tributos, Assistência Social, Ouvidoria) devem ser ajustados pela Gestão.
