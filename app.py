import datetime
import hashlib
import io
import os
import sqlite3
import pandas as pd
import plotly.express as px
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

st.set_page_config(
    page_title="Almoxarifado Inteligente Pro", 
    page_icon="📦", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

st.cache_data.clear()

DB_FILE = "almoxarifado.db"

def hash_senha(senha):
    return hashlib.sha256(str.encode(senha)).hexdigest()

def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS usuarios (username TEXT PRIMARY KEY, senha TEXT NOT NULL, perfil TEXT NOT NULL, status TEXT DEFAULT 'Ativo', pergunta_secreta TEXT, resposta_secreta TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS categorias (nome TEXT PRIMARY KEY)")
    c.execute("CREATE TABLE IF NOT EXISTS produtos (sku TEXT PRIMARY KEY, nome TEXT NOT NULL, categoria TEXT, qtd_estoque INTEGER DEFAULT 0, qtd_minima INTEGER DEFAULT 5, preco_unitario REAL DEFAULT 0.0)")
    c.execute("CREATE TABLE IF NOT EXISTS movimentacoes (id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT, tipo TEXT, quantidade INTEGER, descricao TEXT, data TEXT, usuario TEXT, status TEXT DEFAULT 'Concluido')")
    c.execute("CREATE TABLE IF NOT EXISTS solicitacoes_ajuste (id INTEGER PRIMARY KEY AUTOINCREMENT, movimentacao_id INTEGER, solicitante TEXT, destinatario TEXT, motivo TEXT, status TEXT DEFAULT 'Pendente', data_solicitacao TEXT, resposta_admin TEXT, avaliador TEXT, lido_gestor INTEGER DEFAULT 0, lido_operador INTEGER DEFAULT 0)")

    for col_sql in [
        "ALTER TABLE solicitacoes_ajuste ADD COLUMN resposta_admin TEXT",
        "ALTER TABLE solicitacoes_ajuste ADD COLUMN destinatario TEXT",
        "ALTER TABLE solicitacoes_ajuste ADD COLUMN avaliador TEXT",
        "ALTER TABLE solicitacoes_ajuste ADD COLUMN lido_gestor INTEGER DEFAULT 0",
        "ALTER TABLE solicitacoes_ajuste ADD COLUMN lido_operador INTEGER DEFAULT 0"
    ]:
        try:
            c.execute(col_sql)
        except sqlite3.OperationalError:
            pass

    c.execute("SELECT count(*) FROM categorias")
    if c.fetchone()[0] == 0:
        c.executemany("INSERT OR IGNORE INTO categorias VALUES (?)", [('Ferramentas',), ('EPIs',), ('Consumíveis',), ('Outros',), ('Escritório',), ('Limpeza',), ('Elétrica',), ('Hidráulica',)])

    c.execute("SELECT * FROM usuarios WHERE username = 'admin'")
    if not c.fetchone():
        c.execute("INSERT OR REPLACE INTO usuarios VALUES ('admin', ?, 'Admin', 'Ativo', 'Qual a cidade natal?', ?)", (hash_senha("admin123"), hash_senha("admin")))

    conn.commit()
    conn.close()

init_db()

def contar_solicitacoes_pendentes(perfil):
    conn = get_connection()
    c = conn.cursor()
    if perfil == "Admin":
        c.execute("SELECT COUNT(*) FROM solicitacoes_ajuste WHERE status = 'Pendente' AND lido_gestor = 0")
    else: 
        c.execute("SELECT COUNT(*) FROM solicitacoes_ajuste WHERE status = 'Pendente' AND (destinatario = 'Supervisor' OR destinatario IS NULL) AND lido_gestor = 0")
    total = c.fetchone()[0]
    conn.close()
    return total

def marcar_como_lido_gestor(perfil):
    conn = get_connection()
    c = conn.cursor()
    if perfil == "Admin":
        c.execute("UPDATE solicitacoes_ajuste SET lido_gestor = 1 WHERE status = 'Pendente'")
    else:
        c.execute("UPDATE solicitacoes_ajuste SET lido_gestor = 1 WHERE status = 'Pendente' AND (destinatario = 'Supervisor' OR destinatario IS NULL)")
    conn.commit()
    conn.close()

def contar_notificacoes_operador(usuario):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM solicitacoes_ajuste WHERE solicitante = ? AND status != 'Pendente' AND lido_operador = 0", (usuario,))
    total = c.fetchone()[0]
    conn.close()
    return total

def marcar_como_lido_operador(usuario):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE solicitacoes_ajuste SET lido_operador = 1 WHERE solicitante = ? AND status != 'Pendente'", (usuario,))
    conn.commit()
    conn.close()

def gerar_pdf_relatorio(df_produtos, titulo_relatorio):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=15, textColor=colors.HexColor('#0f172a'))
    story.append(Paragraph("Relatório Formal - " + str(titulo_relatorio), title_style))
    story.append(Paragraph("Emitido em: " + datetime.datetime.now().strftime('%d/%m/%Y %H:%M'), styles['Normal']))
    story.append(Spacer(1, 10))

    cell_style = ParagraphStyle('CellStyle', parent=styles['Normal'], fontSize=8, leading=10)
    header_style = ParagraphStyle('HeaderStyle', parent=styles['Normal'], fontSize=8, leading=10, textColor=colors.whitesmoke, fontName='Helvetica-Bold')

    headers = ["SKU", "Produto", "Categoria", "Qtd", "Mín", "Preço", "Status"]
    data_matrix = [[Paragraph(h, header_style) for h in headers]]

    for _, r in df_produtos.iterrows():
        is_critico = r['qtd_estoque'] <= r['qtd_minima']
        status = "CRITICO" if is_critico else "NORMAL"
        data_matrix.append([
            Paragraph(str(r['sku']), cell_style),
            Paragraph(str(r['nome']), cell_style),
            Paragraph(str(r['categoria']), cell_style),
            Paragraph(str(r['qtd_estoque']), cell_style),
            Paragraph(str(r['qtd_minima']), cell_style),
            Paragraph("R$" + f"{r['preco_unitario']:.2f}", cell_style),
            Paragraph(status, cell_style)
        ])

    tabela = Table(data_matrix, colWidths=[55, 160, 85, 35, 35, 60, 75])
    tabela.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(tabela)
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def gerar_pdf_movimentacoes_formal(df_mov, titulo_periodo, tipo_relatorio):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=14, textColor=colors.HexColor('#0f172a'))
    story.append(Paragraph("Relatório: " + str(tipo_relatorio), title_style))
    story.append(Paragraph("Período: " + str(titulo_periodo) + " | Emitido em: " + datetime.datetime.now().strftime('%d/%m/%Y %H:%M'), styles['Normal']))
    story.append(Spacer(1, 10))

    cell_style = ParagraphStyle('CellStyle', parent=styles['Normal'], fontSize=7.5, leading=9.5)
    header_style = ParagraphStyle('HeaderStyle', parent=styles['Normal'], fontSize=8, leading=10, textColor=colors.whitesmoke, fontName='Helvetica-Bold')

    colunas_df = df_mov.columns.tolist()
    headers = [Paragraph(str(c), header_style) for c in colunas_df]
    data_matrix = [headers]

    for _, r in df_mov.iterrows():
        row_cells = []
        for col in colunas_df:
            val = str(r[col]) if pd.notna(r[col]) else ""
            row_cells.append(Paragraph(val, cell_style))
        data_matrix.append(row_cells)

    num_cols = len(colunas_df)
    largura_util = 555
    col_widths = [largura_util / num_cols] * num_cols

    tabela = Table(data_matrix, colWidths=col_widths)
    tabela.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(tabela)
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

if "logado" not in st.session_state:
    st.session_state["logado"] = False
    st.session_state["usuario"] = None
    st.session_state["perfil"] = None

if "modo_login" not in st.session_state:
    st.session_state["modo_login"] = "login"

def tela_login():
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.write("")
        st.write("")
        st.title("📦 Almoxarifado Inteligente")
        st.caption("Faça login para acessar o painel de controle")
        
        if st.session_state["modo_login"] == "login":
            with st.form("form_login"):
                usuario = st.text_input("Utilizador").strip()
                senha = st.text_input("Senha", type="password")
                btn_login = st.form_submit_button("Entrar no Sistema", use_container_width=True)

                if btn_login:
                    conn = get_connection()
                    c = conn.cursor()
                    c.execute("SELECT perfil, status FROM usuarios WHERE username = ? AND senha = ?", (usuario, hash_senha(senha)))
                    res = c.fetchone()
                    conn.close()

                    if res:
                        perfil, status = res
                        if status == "Bloqueado":
                            st.error("Utilizador bloqueado. Contate o Administrador.")
                        else:
                            st.session_state["logado"] = True
                            st.session_state["usuario"] = usuario
                            st.session_state["perfil"] = perfil
                            st.rerun()
                    else:
                        st.error("Utilizador ou senha incorretos. (Admin padrão: admin / admin123)")

            if st.button("Esqueci minha senha", use_container_width=True):
                st.session_state["modo_login"] = "recuperar"
                st.rerun()

        elif st.session_state["modo_login"] == "recuperar":
            st.subheader("🔑 Recuperação de Senha")
            usr_rec = st.text_input("Informe seu nome de Utilizador").strip()

            if usr_rec:
                conn = get_connection()
                c = conn.cursor()
                c.execute("SELECT pergunta_secreta FROM usuarios WHERE username = ?", (usr_rec,))
                res = c.fetchone()
                conn.close()

                if res and res[0]:
                    st.info("Pergunta Secreta: " + str(res[0]))
                    with st.form("form_recuperar"):
                        resp_digitada = st.text_input("Sua Resposta").strip().lower()
                        nova_senha = st.text_input("Nova Senha", type="password")
                        if st.form_submit_button("Redefinir Senha", use_container_width=True):
                            conn = get_connection()
                            c = conn.cursor()
                            c.execute("SELECT * FROM usuarios WHERE username = ? AND resposta_secreta = ?", (usr_rec, hash_senha(resp_digitada)))
                            if c.fetchone():
                                c.execute("UPDATE usuarios SET senha = ? WHERE username = ?", (hash_senha(nova_senha), usr_rec))
                                conn.commit()
                                st.success("Senha redefinida com sucesso! Faça login.")
                                st.session_state["modo_login"] = "login"
                                st.rerun()
                            else:
                                st.error("Resposta secreta incorreta.")
                            conn.close()
                elif res:
                    st.warning("Utilizador não possui pergunta de segurança cadastrada.")
                else:
                    st.error("Utilizador não encontrado.")

            if st.button("Voltar ao Login", use_container_width=True):
                st.session_state["modo_login"] = "login"
                st.rerun()

if not st.session_state["logado"]:
    tela_login()
    st.stop()

with st.sidebar:
    st.write("### 👤 " + str(st.session_state['usuario']))
    st.caption("Perfil: " + str(st.session_state['perfil']))
    st.divider()
    if st.button("🔄 Atualizar Dados", use_container_width=True):
        st.rerun()
    if st.button("🚪 Encerrar Sessão", use_container_width=True):
        st.session_state["logado"] = False
        st.session_state["usuario"] = None
        st.session_state["perfil"] = None
        st.rerun()

st.title("📦 Almoxarifado Inteligente")
perfil_atual = st.session_state["perfil"]

if perfil_atual == "Admin":
    num_pendentes = contar_solicitacoes_pendentes(perfil_atual)
    label_correcoes = "🛠️ Correções / Estornos (🔴 " + str(num_pendentes) + ")" if num_pendentes > 0 else "🛠️ Correções / Estornos"
    abas = st.tabs(["📊 Dashboard", "🔄 Lançar Entrada/Saída", "📈 Relatórios Avançados", label_correcoes, "📝 Produtos", "🏷️ Categorias", "👥 Gestão de Utilizadores"])
    aba_dash, aba_mov, aba_rel, aba_ajuste, aba_prod, aba_cat, aba_usr = abas
elif perfil_atual == "Supervisor":
    num_pendentes = contar_solicitacoes_pendentes(perfil_atual)
    label_correcoes = "🛠️ Aprovar Correções (🔴 " + str(num_pendentes) + ")" if num_pendentes > 0 else "🛠️ Aprovar Correções"
    abas = st.tabs(["📊 Dashboard", "🔄 Lançar Entrada/Saída", "📈 Relatórios Gerais", label_correcoes, "🏷️ Categorias"])
    aba_dash, aba_mov, aba_rel, aba_ajuste, aba_cat = abas
else:
    num_notif = contar_notificacoes_operador(st.session_state["usuario"])
    label_solic_op = "🛠️ Solicitar Correção (🔔 " + str(num_notif) + ")" if num_notif > 0 else "🛠️ Solicitar Correção"
    abas = st.tabs(["📊 Dashboard", "🔄 Lançar Entrada/Saída", "📈 Meus Relatórios", label_solic_op])
    aba_dash, aba_mov, aba_rel, aba_ajuste = abas

with aba_dash:
    col_dash_title, col_dash_btn = st.columns([4, 1])
    with col_dash_title:
        st.subheader("📊 Visão Geral do Estoque")
    with col_dash_btn:
        if st.button("🔄 Atualizar", key="btn_ref_dash", use_container_width=True):
            st.rerun()

    conn = get_connection()
    df_produtos = pd.read_sql_query("SELECT * FROM produtos", conn)
    conn.close()

    if not df_produtos.empty:
        df_produtos["status"] = df_produtos.apply(
            lambda x: "⚠️ CRÍTICO" if x["qtd_estoque"] <= x["qtd_minima"] else "✅ NORMAL", axis=1
        )

        col1, col2 = st.columns(2)
        col1.metric("Total de SKUs", len(df_produtos))
        col2.metric("Itens em Estoque Crítico", int((df_produtos["status"] == "⚠️ CRÍTICO").sum()))

        pdf_bytes = gerar_pdf_relatorio(df_produtos, "Estoque Geral Atual")
        
        col_dl1, col_dl2 = st.columns([3, 1])
        with col_dl1:
            btn_pdf = st.download_button(
                "📄 Baixar Relatório Geral em PDF", 
                data=pdf_bytes, 
                file_name="estoque_atual.pdf", 
                mime="application/pdf", 
                use_container_width=True
            )
        
        if btn_pdf:
            st.success("✅ Relatório gerado com sucesso!")

        fig_status = px.pie(df_produtos, names="status", color="status", color_discrete_map={"⚠️ CRÍTICO": "#FF4B4B", "✅ NORMAL": "#10B981"}, hole=0.5)
        fig_status.update_layout(margin=dict(t=20, b=20, l=20, r=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig_status, use_container_width=True)

        st.dataframe(df_produtos[['sku', 'nome', 'categoria', 'qtd_estoque', 'qtd_minima', 'status']], use_container_width=True)
    else:
        st.info("Nenhum produto cadastrado no sistema.")

with aba_mov:
    st.subheader("🔄 Lançamento de Entrada / Saída de Materiais")
    conn = get_connection()
    prods = pd.read_sql_query("SELECT sku, nome FROM produtos ORDER BY nome ASC", conn)
    conn.close()

    if not prods.empty:
        opcoes = {str(row['sku']) + " - " + str(row['nome']): row["sku"] for _, row in prods.iterrows()}
        with st.form("form_mov", clear_on_submit=True):
            item = st.selectbox("Selecione o Produto", list(opcoes.keys()))
            tipo = st.radio("Tipo de Operação", ["Entrada", "Saída"], horizontal=True)
            qtd = st.number_input("Quantidade", min_value=1, value=1, step=1)
            descricao = st.text_input("Descrição / Observação do Lançamento")

            if st.form_submit_button("Confirmar Lançamento", use_container_width=True):
                sku_sel = opcoes[item]
                fator = 1 if tipo == "Entrada" else -1

                conn = get_connection()
                c = conn.cursor()
                c.execute("SELECT qtd_estoque FROM produtos WHERE sku = ?", (sku_sel,))
                qtd_atual = c.fetchone()[0]

                if tipo == "Saída" and qtd_atual < qtd:
                    st.error("Estoque insuficiente! Estoque atual: " + str(qtd_atual))
                else:
                    c.execute("UPDATE produtos SET qtd_estoque = qtd_estoque + ? WHERE sku = ?", (int(qtd * fator), sku_sel))
                    c.execute(
                        "INSERT INTO movimentacoes (sku, tipo, quantidade, descricao, data, usuario, status) VALUES (?, ?, ?, ?, ?, ?, 'Concluido')",
                        (sku_sel, tipo, int(qtd), descricao, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), st.session_state["usuario"])
                    )
                    conn.commit()
                    st.success("Lançamento de " + tipo + " realizado com sucesso!")
                conn.close()
                st.rerun()
    else:
        st.warning("Nenhum produto cadastrado.")

with aba_rel:
    if perfil_atual in ["Admin", "Supervisor"]:
        st.subheader("📈 Relatórios Gerais Avançados e Formalização por Período")
        lista_modelos_rel = [
            "Relatório Geral de Movimentações (Entradas e Saídas)",
            "Relatório Analítico de Entradas",
            "Relatório Analítico de Saídas",
            "Relatório de Itens Críticos / Abaixo do Mínimo"
        ]
        if perfil_atual == "Admin":
            lista_modelos_rel.append("Relatório de Auditoria / Ações Gerais entre Utilizadores")
    else:
        st.subheader("📈 Meus Relatórios de Lançamentos (" + str(st.session_state['usuario']) + ")")
        lista_modelos_rel = [
            "Meus Lançamentos (Entradas e Saídas)",
            "Minhas Entradas",
            "Minhas Saídas"
        ]

    tipo_relatorio_op = st.selectbox("Selecione o Modelo de Relatório", lista_modelos_rel)

    st.markdown("---")
    col_f1, col_f2, col_f3 = st.columns([2, 2, 2])
    with col_f1:
        periodo = st.selectbox("Filtro de Período", ["Hoje (Dia)", "Última Semana (7 dias)", "Mês Atual", "Ano Atual", "Personalizado"])
    
    data_hoje = datetime.date.today()
    if periodo == "Hoje (Dia)":
        dt_inicio = data_hoje
        dt_fim = data_hoje
        label_periodo = "Dia " + data_hoje.strftime('%d/%m/%Y')
    elif periodo == "Última Semana (7 dias)":
        dt_inicio = data_hoje - datetime.timedelta(days=7)
        dt_fim = data_hoje
        label_periodo = "Últimos 7 Dias"
    elif periodo == "Mês Atual":
        dt_inicio = datetime.date(data_hoje.year, data_hoje.month, 1)
        dt_fim = data_hoje
        label_periodo = "Mês Atual (" + data_hoje.strftime('%m/%Y') + ")"
    elif periodo == "Ano Atual":
        dt_inicio = datetime.date(data_hoje.year, 1, 1)
        dt_fim = data_hoje
        label_periodo = "Ano de " + str(data_hoje.year)
    else:
        with col_f2:
            dt_inicio = st.date_input("Data Inicial", data_hoje - datetime.timedelta(days=30))
        with col_f3:
            dt_fim = st.date_input("Data Final", data_hoje)
        label_periodo = "Período de " + dt_inicio.strftime('%d/%m/%Y') + " até " + dt_fim.strftime('%d/%m/%Y')

    confirmar_periodo = st.button("🔍 Confirmar Período e Gerar Relatório", type="primary", use_container_width=True)

    str_inicio = dt_inicio.strftime('%Y-%m-%d') + " 00:00:00"
    str_fim = dt_fim.strftime('%Y-%m-%d') + " 23:59:59"

    conn = get_connection()
    base_query = "SELECT m.id as 'ID', m.data as 'Data', m.tipo as 'Tipo', m.sku as 'SKU', p.nome as 'Produto', m.quantidade as 'Qtd', m.usuario as 'Usuário', m.descricao as 'Descrição', m.status as 'Status' FROM movimentacoes m JOIN produtos p ON m.sku = p.sku"
    
    if perfil_atual == "Operador":
        usuario_atual = st.session_state["usuario"]
        if "Entradas" in tipo_relatorio_op:
            nome_arquivo_pdf = "meus_relatorios_entradas.pdf"
            q = base_query + " WHERE m.usuario = ? AND m.tipo = 'Entrada' AND m.data BETWEEN ? AND ? ORDER BY m.id DESC"
            df_m = pd.read_sql_query(q, conn, params=(usuario_atual, str_inicio, str_fim))
        elif "Saídas" in tipo_relatorio_op:
            nome_arquivo_pdf = "meus_relatorios_saidas.pdf"
            q = base_query + " WHERE m.usuario = ? AND m.tipo = 'Saída' AND m.data BETWEEN ? AND ? ORDER BY m.id DESC"
            df_m = pd.read_sql_query(q, conn, params=(usuario_atual, str_inicio, str_fim))
        else:
            nome_arquivo_pdf = "meus_relatorios_geral.pdf"
            q = base_query + " WHERE m.usuario = ? AND m.data BETWEEN ? AND ? ORDER BY m.id DESC"
            df_m = pd.read_sql_query(q, conn, params=(usuario_atual, str_inicio, str_fim))
    else:
        if "Auditoria" in tipo_relatorio_op:
            nome_arquivo_pdf = "relatorio_de_auditoria.pdf"
            q_audit = "SELECT s.id as 'ID Sol.', s.data_solicitacao as 'Data Solicitação', s.solicitante as 'Operador', s.destinatario as 'Destinado a', s.motivo as 'Motivo', s.status as 'Status', COALESCE(s.avaliador, 'Não avaliado') as 'Avaliador', COALESCE(s.resposta_admin, '-') as 'Resposta' FROM solicitacoes_ajuste s WHERE s.data_solicitacao BETWEEN ? AND ? ORDER BY s.id DESC"
            df_m = pd.read_sql_query(q_audit, conn, params=(str_inicio, str_fim))
        elif "Entradas" in tipo_relatorio_op:
            nome_arquivo_pdf = "relatorio_analitico_entradas.pdf"
            q = base_query + " WHERE m.tipo = 'Entrada' AND m.data BETWEEN ? AND ? ORDER BY m.id DESC"
            df_m = pd.read_sql_query(q, conn, params=(str_inicio, str_fim))
        elif "Saídas" in tipo_relatorio_op:
            nome_arquivo_pdf = "relatorio_analitico_saidas.pdf"
            q = base_query + " WHERE m.tipo = 'Saída' AND m.data BETWEEN ? AND ? ORDER BY m.id DESC"
            df_m = pd.read_sql_query(q, conn, params=(str_inicio, str_fim))
        elif "Críticos" in tipo_relatorio_op:
            nome_arquivo_pdf = "relatorio_itens_criticos.pdf"
            df_m = pd.read_sql_query("SELECT sku as 'SKU', nome as 'Produto', categoria as 'Categoria', qtd_estoque as 'Qtd Atual', qtd_minima as 'Qtd Mínima', preco_unitario as 'Preço' FROM produtos WHERE qtd_estoque <= qtd_minima", conn)
        else:
            nome_arquivo_pdf = "relatorio_geral_movimentacoes.pdf"
            q = base_query + " WHERE m.data BETWEEN ? AND ? ORDER BY m.id DESC"
            df_m = pd.read_sql_query(q, conn, params=(str_inicio, str_fim))
    
    conn.close()

    if not df_m.empty:
        st.subheader("Visualização: " + str(tipo_relatorio_op))
        st.caption("Período: " + label_periodo)
        st.dataframe(df_m, use_container_width=True)

        if "Críticos" in tipo_relatorio_op:
            pdf_bytes_rep = gerar_pdf_relatorio(df_m, tipo_relatorio_op)
        else:
            pdf_bytes_rep = gerar_pdf_movimentacoes_formal(df_m, label_periodo, tipo_relatorio_op)

        btn_dl_formal = st.download_button(
            "📥 Baixar Relatório Formal em PDF",
            data=pdf_bytes_rep,
            file_name=nome_arquivo_pdf,
            mime="application/pdf",
            use_container_width=True
        )
        if btn_dl_formal:
            st.success("✅ Relatório exportado com sucesso!")
    else:
        st.info("Nenhum registo encontrado para o período e modelo selecionados.")

with aba_ajuste:
    if perfil_atual in ["Admin", "Supervisor"]:
        marcar_como_lido_gestor(perfil_atual)
        st.subheader("⚠️ Gestão e Aprovação de Solicitações de Correção")
        
        conn = get_connection()
        if perfil_atual == "Admin":
            df_sol = pd.read_sql_query("SELECT s.id as 'ID_Solicitacao', s.movimentacao_id as 'ID_Mov', m.sku, p.nome as 'Produto', m.tipo, m.quantidade, s.solicitante, s.destinatario, s.motivo, s.status FROM solicitacoes_ajuste s JOIN movimentacoes m ON s.movimentacao_id = m.id JOIN produtos p ON m.sku = p.sku WHERE s.status = 'Pendente'", conn)
        else:
            df_sol = pd.read_sql_query("SELECT s.id as 'ID_Solicitacao', s.movimentacao_id as 'ID_Mov', m.sku, p.nome as 'Produto', m.tipo, m.quantidade, s.solicitante, s.destinatario, s.motivo, s.status FROM solicitacoes_ajuste s JOIN movimentacoes m ON s.movimentacao_id = m.id JOIN produtos p ON m.sku = p.sku WHERE s.status = 'Pendente' AND (s.destinatario = 'Supervisor' OR s.destinatario IS NULL)", conn)
        conn.close()
        
        if not df_sol.empty:
            st.dataframe(df_sol, use_container_width=True)
            with st.form("form_aprova_detalhado"):
                sid = st.selectbox("Selecione o ID da Solicitação para Avaliar", df_sol["ID_Solicitacao"].tolist())
                acao = st.radio("Decisão", ["Aprovar Correção", "Rejeitar Correção"], horizontal=True)
                resp_admin = st.text_area("Justificativa / Descrição do Gestor")
                
                if st.form_submit_button("💾 Processar e Notificar Operador", use_container_width=True):
                    conn = get_connection()
                    c = conn.cursor()
                    c.execute("SELECT m.sku, m.tipo, m.quantidade FROM solicitacoes_ajuste s JOIN movimentacoes m ON s.movimentacao_id = m.id WHERE s.id = ?", (sid,))
                    res_mov = c.fetchone()
                    
                    if res_mov:
                        sku_m, tipo_m, qtd_m = res_mov
                        novo_status_sol = "Aprovado" if "Aprovar" in acao else "Rejeitado"
                        
                        if "Aprovar" in acao:
                            f = -1 if tipo_m == "Entrada" else 1
                            c.execute("UPDATE produtos SET qtd_estoque = qtd_estoque + ? WHERE sku = ?", (int(qtd_m * f), sku_m))
                        
                        c.execute("UPDATE solicitacoes_ajuste SET status = ?, resposta_admin = ?, avaliador = ?, lido_operador = 0 WHERE id = ?", (novo_status_sol, resp_admin, st.session_state["usuario"], sid))
                        conn.commit()
                        st.success("✅ Solicitação avaliada por " + str(st.session_state['usuario']) + "!")
                    conn.close()
                    st.rerun()
        else:
            st.info("Não existem solicitações pendentes no momento.")
    else:
        marcar_como_lido_operador(st.session_state["usuario"])
        st.subheader("🛠️ Minhas Solicitações e Notificações de Correção")
        
        conn = get_connection()
        df_notif = pd.read_sql_query(
            "SELECT s.id as 'ID', m.data as 'Data Mov.', m.tipo as 'Tipo', p.nome as 'Produto', s.destinatario as 'Enviado para', s.motivo as 'Meu Motivo', s.status as 'Status', COALESCE(s.avaliador, 'Aguardando') as 'Avaliador', COALESCE(s.resposta_admin, 'Aguardando análise') as 'Resposta da Administração' FROM solicitacoes_ajuste s JOIN movimentacoes m ON s.movimentacao_id = m.id JOIN produtos p ON m.sku = p.sku WHERE s.solicitante = ? ORDER BY s.id DESC",
            conn, params=(st.session_state["usuario"],)
        )
        conn.close()

        if not df_notif.empty:
            st.dataframe(df_notif, use_container_width=True)
        else:
            st.info("Ainda não possui solicitações registadas.")

        st.divider()
        st.subheader("📝 Nova Solicitação de Correção / Estorno")
        
        conn = get_connection()
        df_minhas_mov = pd.read_sql_query("SELECT m.id as 'ID', m.data as 'Data', m.tipo as 'Tipo', p.nome as 'Produto', m.quantidade as 'Qtd', m.descricao as 'Descrição' FROM movimentacoes m JOIN produtos p ON m.sku = p.sku WHERE m.usuario = ? ORDER BY m.id DESC LIMIT 30", conn, params=(st.session_state["usuario"],))
        conn.close()

        if not df_minhas_mov.empty:
            with st.form("form_pedir_correcao", clear_on_submit=True):
                mov_id_sel = st.selectbox("Selecione o ID do Lançamento", df_minhas_mov["ID"].tolist())
                destinatario_escolha = st.selectbox("Enviar Solicitação para:", ["Administrador", "Supervisor"])
                motivo_solic = st.text_area("Motivo detalhado da solicitação")
                
                if st.form_submit_button("📨 Enviar Solicitação", use_container_width=True):
                    if motivo_solic.strip():
                        conn = get_connection()
                        c = conn.cursor()
                        c.execute(
                            "INSERT INTO solicitacoes_ajuste (movimentacao_id, solicitante, destinatario, motivo, status, data_solicitacao, resposta_admin, avaliador, lido_gestor, lido_operador) VALUES (?, ?, ?, ?, 'Pendente', ?, 'Aguardando avaliação', NULL, 0, 1)",
                            (mov_id_sel, st.session_state["usuario"], destinatario_escolha, motivo_solic, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                        )
                        conn.commit()
                        conn.close()
                        st.success("✅ Solicitação enviada para o " + destinatario_escolha + "!")
                        st.rerun()
                    else:
                        st.warning("Por favor, preencha o motivo.")

if perfil_atual == "Supervisor":
    with aba_cat:
        st.subheader("🏷️ Categorias de Produtos")
        conn = get_connection()
        st.dataframe(pd.read_sql_query("SELECT nome FROM categorias", conn), use_container_width=True)
        conn.close()

if perfil_atual == "Admin":
    with aba_prod:
        st.subheader("📝 Gestão e Cadastro de Produtos")
        tab_p1, tab_p2, tab_p3, tab_p4, tab_p5 = st.tabs([
            "Cadastrar", "✏️ Editar", "❌ Excluir", "🗑️ Zerar Estoques", "📥 Importar Planilha"
        ])
        
        with tab_p1:
            with st.form("cad_p", clear_on_submit=True):
                sku = st.text_input("SKU").strip()
                nome = st.text_input("Nome").strip()
                cat = st.selectbox("Categoria", ["Geral", "Consumíveis", "Ferramentas", "Escritório", "EPIs"])
                qmin = st.number_input("Mínimo", value=5, step=1)
                preco = st.number_input("Preço", value=0.0, step=0.5)
                if st.form_submit_button("Salvar"):
                    if sku and nome:
                        conn = get_connection()
                        c = conn.cursor()
                        c.execute("INSERT OR REPLACE INTO produtos VALUES (?, ?, ?, 0, ?, ?)", (sku, nome, cat, int(qmin), float(preco)))
                        conn.commit()
                        conn.close()
                        st.success("Cadastrado com sucesso!")
                        st.rerun()

        with tab_p4:
            st.subheader("🗑️ Opções de Zerar Estoque")
            modo_zerar = st.radio("Escolha o modo de zeragem:", ["Zeramento Individual (Por Produto)", "Zerar por Categoria / Grupo", "Zerar Todo o Estoque (Lote Geral)"], horizontal=True)

            conn = get_connection()
            if modo_zerar == "Zeramento Individual (Por Produto)":
                df_z = pd.read_sql_query("SELECT sku, nome, qtd_estoque FROM produtos", conn)
                conn.close()

                if not df_z.empty:
                    op_z = {str(r['sku']) + " - " + str(r['nome']) + " (Qtd: " + str(r['qtd_estoque']) + ")": r['sku'] for _, r in df_z.iterrows()}
                    sel_z = st.selectbox("Produto para Zerar", list(op_z.keys()))
                    sku_z = op_z[sel_z]

                    if st.button("Zerar Este Produto Agora", type="primary"):
                        conn = get_connection()
                        c = conn.cursor()
                        c.execute("UPDATE produtos SET qtd_estoque = 0 WHERE sku = ?", (sku_z,))
                        conn.commit()
                        conn.close()
                        st.success("✅ Estoque do SKU " + sku_z + " zerado!")
                        st.rerun()
                else:
                    st.info("Nenhum produto cadastrado.")

            elif modo_zerar == "Zerar por Categoria / Grupo":
                df_cat = pd.read_sql_query("SELECT nome FROM categorias", conn)
                conn.close()

                if not df_cat.empty:
                    cat_sel = st.selectbox("Selecione a Categoria / Grupo", df_cat["nome"].tolist())
                    if st.button("Zerar Todos os Produtos desta Categoria", type="primary"):
                        conn = get_connection()
                        c = conn.cursor()
                        c.execute("UPDATE produtos SET qtd_estoque = 0 WHERE categoria = ?", (cat_sel,))
                        conn.commit()
                        conn.close()
                        st.success("✅ Estoque da categoria '" + cat_sel + "' zerado com sucesso!")
                        st.rerun()
                else:
                    st.info("Nenhuma categoria cadastrada.")

            else:
                conn.close()
                st.warning("⚠️ Atenção: Esta ação vai zerar o estoque de **todos** os produtos cadastrados no sistema.")
                if st.button("Zeragem Geral em Lote (Todos os Produtos)", type="primary"):
                    conn = get_connection()
                    c = conn.cursor()
                    c.execute("UPDATE produtos SET qtd_estoque = 0")
                    conn.commit()
                    conn.close()
                    st.success("✅ Estoque geral zerado com sucesso!")
                    st.rerun()

        with tab_p5:
            st.subheader("📥 Importação e Atualização em Lote por Planilha")
            df_mod = pd.DataFrame([
                {"sku": "ALM-001", "nome": "Papel Sulfite A4 75g", "categoria": "Consumíveis", "minimo": 10, "preco": 25.5, "quantidade": 200},
                {"sku": "ALM-002", "nome": "Caneta Esferográfica Azul", "categoria": "Escritório", "minimo": 20, "preco": 1.56, "quantidade": 200}
            ])
            st.download_button("Baixar Modelo CSV Exato", data=df_mod.to_csv(index=False, sep=';', encoding='utf-8-sig').encode('utf-8-sig'), file_name="modelo_almoxarifado.csv", mime="text/csv")
            
            st.divider()
            uploaded_file = st.file_uploader("Carregar arquivo de inventário (CSV ou Excel)", type=["csv", "xlsx", "xls"])
            if uploaded_file is not None:
                try:
                    if uploaded_file.name.endswith('.csv'):
                        df_upload = pd.read_csv(uploaded_file, sep=None, engine='python')
                    else:
                        df_upload = pd.read_excel(uploaded_file)
                    
                    st.write("Pré-visualização dos dados carregados:")
                    st.dataframe(df_upload.head(), use_container_width=True)

                    if st.button("📥 Processar e Inserir no Almoxarifado", type="primary"):
                        conn = get_connection()
                        c = conn.cursor()
                        sucessos = 0
                        
                        # Normaliza os nomes das colunas do dataframe para minúsculas para evitar erros de leitura
                        df_upload.columns = [str(c).strip().lower() for c in df_upload.columns]
                        
                        for _, row in df_upload.iterrows():
                            sku = str(row.get('sku', '')).strip()
                            nome = str(row.get('nome', '')).strip()
                            cat = str(row.get('categoria', 'Geral')).strip()
                            
                            # Tenta ler a quantidade de colunas comuns
                            qtd_upload = 0
                            for col_q in ['quantidade', 'qtd', 'estoque', 'quant']:
                                if col_q in row and pd.notna(row[col_q]):
                                    try:
                                        qtd_upload = int(float(str(row[col_q])))
                                        break
                                    except:
                                        pass

                            # Tenta ler o preço e mínimo
                            minimo = 5
                            for col_m in ['minimo', 'qtd_minima', 'min']:
                                if col_m in row and pd.notna(row[col_m]):
                                    try:
                                        minimo = int(float(str(row[col_m])))
                                        break
                                    except:
                                        pass

                            preco = 0.0
                            for col_p in ['preco', 'preço', 'valor', 'unitario']:
                                if col_p in row and pd.notna(row[col_p]):
                                    try:
                                        preco = float(str(row[col_p]).replace('R$', '').replace(',', '.'))
                                        break
                                    except:
                                        pass

                            if sku and nome:
                                # Verifica se o produto já existe para somar corretamente
                                c.execute("SELECT qtd_estoque FROM produtos WHERE sku = ?", (sku,))
                                res_prod = c.fetchone()
                                
                                if res_prod:
                                    qtd_existente = int(res_prod[0])
                                    nova_qtd = qtd_existente + qtd_upload
                                    c.execute("""
                                        UPDATE produtos 
                                        SET nome = ?, categoria = ?, qtd_estoque = ?, qtd_minima = ?, preco_unitario = ? 
                                        WHERE sku = ?
                                    """, (nome, cat, nova_qtd, minimo, preco, sku))
                                else:
                                    c.execute("""
                                        INSERT INTO produtos (sku, nome, categoria, qtd_estoque, qtd_minima, preco_unitario)
                                        VALUES (?, ?, ?, ?, ?, ?)
                                    """, (sku, nome, cat, qtd_upload, minimo, preco))
                                
                                # Regista a movimentação formal de entrada
                                if qtd_upload > 0:
                                    c.execute("""
                                        INSERT INTO movimentacoes (sku, tipo, quantidade, descricao, data, usuario, status) 
                                        VALUES (?, 'Entrada', ?, 'Importação em lote via planilha', ?, ?, 'Concluido')
                                    """, (sku, qtd_upload, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), st.session_state["usuario"]))
                                
                                sucessos += 1

                        conn.commit()
                        conn.close()
                        st.success(f"✅ {sucessos} produtos importados e somados ao estoque atual com sucesso! A página está pronta para novos uploads.")
                        st.rerun()
                except Exception as e:
                    st.error(f"Erro ao ler o ficheiro: {e}")

    with aba_cat:
        st.subheader("🏷️ Categorias")
        conn = get_connection()
        st.dataframe(pd.read_sql_query("SELECT nome FROM categorias", conn), use_container_width=True)
        conn.close()

    with aba_usr:
        st.subheader("👥 Gestão de Utilizadores")
        tab_u1, tab_u2 = st.tabs(["➕ Incluir", "⚙️ Gerir / Bloquear"])
        
        with tab_u1:
            with st.form("form_novo_user", clear_on_submit=True):
                novo_user = st.text_input("Nome de Utilizador (Login)").strip()
                nova_senha_user = st.text_input("Senha", type="password")
                perfil_user = st.selectbox("Perfil de Acesso", ["Operador", "Supervisor", "Admin"])
                pergunta_sec = st.text_input("Pergunta Secreta", value="Qual a cidade natal?")
                resposta_sec = st.text_input("Resposta Secreta", type="password")
                
                if st.form_submit_button("Cadastrar Utilizador", type="primary"):
                    if novo_user and nova_senha_user and resposta_sec:
                        try:
                            conn = get_connection()
                            c = conn.cursor()
                            c.execute(
                                "INSERT INTO usuarios (username, senha, perfil, status, pergunta_secreta, resposta_secreta) VALUES (?, ?, ?, 'Ativo', ?, ?)",
                                (novo_user, hash_senha(nova_senha_user), perfil_user, pergunta_sec, hash_senha(resposta_sec))
                            )
                            conn.commit()
                            conn.close()
                            st.success("✅ Utilizador '" + novo_user + "' cadastrado!")
                        except sqlite3.IntegrityError:
                            st.error("Erro: Este nome de utilizador já existe.")
                    else:
                        st.warning("Preencha todos os campos.")

        with tab_u2:
            conn = get_connection()
            df_usuarios = pd.read_sql_query("SELECT username, perfil, status FROM usuarios", conn)
            conn.close()

            if not df_usuarios.empty:
                st.dataframe(df_usuarios, use_container_width=True)
