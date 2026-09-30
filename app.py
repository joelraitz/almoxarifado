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

# Configuração responsiva para Celular/Desktop
st.set_page_config(page_title="Almoxarifado Pro", page_icon="📦", layout="wide", initial_sidebar_state="collapsed")

st.cache_data.clear()

# CSS para otimização mobile
st.markdown("""
    
""", unsafe_allow_html=True)

# --- BANCO DE DADOS E SEGURANÇA ROBUSTA ---
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
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            username TEXT PRIMARY KEY,
            senha TEXT NOT NULL,
            perfil TEXT NOT NULL,
            status TEXT DEFAULT 'Ativo',
            pergunta_secreta TEXT,
            resposta_secreta TEXT
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS categorias (
            nome TEXT PRIMARY KEY
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            sku TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            categoria TEXT,
            qtd_estoque INTEGER DEFAULT 0,
            qtd_minima INTEGER DEFAULT 5,
            preco_unitario REAL DEFAULT 0.0
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS movimentacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT,
            tipo TEXT,
            quantidade INTEGER,
            descricao TEXT,
            data TEXT,
            usuario TEXT,
            status TEXT DEFAULT 'Concluido'
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS solicitacoes_ajuste (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            movimentacao_id INTEGER,
            solicitante TEXT,
            motivo TEXT,
            status TEXT DEFAULT 'Pendente',
            data_solicitacao TEXT,
            resposta_admin TEXT
        )
    """)

    # Migração automática caso a tabela já exista sem a coluna resposta_admin
    try:
        c.execute("ALTER TABLE solicitacoes_ajuste ADD COLUMN resposta_admin TEXT")
    except sqlite3.OperationalError:
        pass

    c.execute("SELECT count(*) FROM categorias")
    if c.fetchone()[0] == 0:
        c.executemany("INSERT OR IGNORE INTO categorias VALUES (?)", [('Ferramentas',), ('EPIs',), ('Consumíveis',), ('Outros',), ('Escritório',), ('Limpeza',), ('Elétrica',), ('Hidráulica',)])

    c.execute("SELECT * FROM usuarios WHERE username = 'admin'")
    if not c.fetchone():
        c.execute("""
            INSERT OR REPLACE INTO usuarios VALUES ('admin', ?, 'Admin', 'Ativo', 'Qual a cidade natal?', ?)
        """, (hash_senha("admin123"), hash_senha("admin")))

    conn.commit()
    conn.close()

init_db()

def contar_solicitacoes_pendentes_admin():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM solicitacoes_ajuste WHERE status = 'Pendente'")
    total = c.fetchone()[0]
    conn.close()
    return total

def contar_notificacoes_operador(usuario):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM solicitacoes_ajuste WHERE solicitante = ? AND status != 'Pendente'", (usuario,))
    total = c.fetchone()[0]
    conn.close()
    return total

# --- GERADORES DE RELATÓRIO PDF FORMALIZADOS ---
def gerar_pdf_relatorio(df_produtos, titulo_relatorio):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=15, leftMargin=15, topMargin=15, bottomMargin=15)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#0f172a'))
    story.append(Paragraph(f"Relatório Formal - {titulo_relatorio}", title_style))
    story.append(Paragraph(f"Emitido em: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
    story.append(Spacer(1, 10))

    dados = [["SKU", "Produto", "Categoria", "Qtd", "Mín", "Preço", "Status"]]
    for _, r in df_produtos.iterrows():
        is_critico = r['qtd_estoque'] <= r['qtd_minima']
        status = "CRITICO" if is_critico else "NORMAL"
        dados.append([
            str(r['sku']), str(r['nome']), str(r['categoria']),
            str(r['qtd_estoque']), str(r['qtd_minima']),
            f"R${r['preco_unitario']:.2f}", status
        ])

    tabela = Table(dados, colWidths=[55, 150, 80, 35, 35, 55, 70])
    tabela.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
    ]))
    story.append(tabela)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def gerar_pdf_movimentacoes_formal(df_mov, titulo_periodo, tipo_relatorio):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=15, leftMargin=15, topMargin=15, bottomMargin=15)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#0f172a'))
    story.append(Paragraph(f"Relatório Formal de {tipo_relatorio}", title_style))
    story.append(Paragraph(f"Período: {titulo_periodo} | Emitido em: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
    story.append(Spacer(1, 10))

    dados = [["ID", "Data", "Tipo", "SKU/Produto", "Qtd", "Usuário", "Descrição"]]
    for _, r in df_mov.iterrows():
        desc = str(r['Descrição']) if pd.notna(r['Descrição']) else ""
        if len(desc) > 20:
            desc = desc[:17] + "..."
        
        p_prod = Paragraph(f"{r['SKU']} - {r['Produto']}", ParagraphStyle('Cell', fontSize=7, leading=8))
        dados.append([
            str(r['ID']), str(r['Data']), str(r['Tipo']),
            p_prod, str(r['Qtd']),
            str(r['Usuário']), desc
        ])

    tabela = Table(dados, colWidths=[25, 80, 45, 155, 30, 55, 90])
    tabela.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
    ]))
    story.append(tabela)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

# --- TELA DE LOGIN ---
if "logado" not in st.session_state:
    st.session_state["logado"] = False
    st.session_state["usuario"] = None
    st.session_state["perfil"] = None

if "modo_login" not in st.session_state:
    st.session_state["modo_login"] = "login"

def tela_login():
    st.title("🔑 Acesso ao Almoxarifado")
    
    if st.session_state["modo_login"] == "login":
        with st.form("form_login"):
            usuario = st.text_input("Utilizador").strip()
            senha = st.text_input("Senha", type="password")
            btn_login = st.form_submit_button("Entrar", use_container_width=True)

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

        if st.button("Esqueci minha senha"):
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
                st.info(f"**Pergunta Secreta:** {res[0]}")
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

        if st.button("Voltar ao Login"):
            st.session_state["modo_login"] = "login"
            st.rerun()

if not st.session_state["logado"]:
    tela_login()
    st.stop()

# --- BARRA LATERAL ---
st.sidebar.title(f"👤 {st.session_state['usuario']}")
st.sidebar.caption(f"Perfil: {st.session_state['perfil']}")

if st.sidebar.button("🔄 Atualizar / Recarregar Dados", use_container_width=True):
    st.rerun()

if st.sidebar.button("🚪 Sair / Logout", use_container_width=True):
    st.session_state["logado"] = False
    st.session_state["usuario"] = None
    st.session_state["perfil"] = None
    st.rerun()

# --- ESTRUTURA PRINCIPAL ---
st.title("📦 Almoxarifado Inteligente")

perfil_atual = st.session_state["perfil"]

if perfil_atual == "Admin":
    num_pendentes = contar_solicitacoes_pendentes_admin()
    label_correcoes = f"🛠️ Correções / Estornos (🔴 {num_pendentes})" if num_pendentes > 0 else "🛠️ Correções / Estornos"
    abas = st.tabs(["📊 Dashboard", "🔄 Lançar Entrada/Saída", "📈 Relatórios Avançados", label_correcoes, "📝 Produtos", "🏷️ Categorias", "👥 Gestão de Utilizadores"])
    aba_dash, aba_mov, aba_rel, aba_ajuste, aba_prod, aba_cat, aba_usr = abas
elif perfil_atual == "Supervisor":
    num_pendentes = contar_solicitacoes_pendentes_admin()
    label_correcoes = f"🛠️ Aprovar Correções (🔴 {num_pendentes})" if num_pendentes > 0 else "🛠️ Aprovar Correções"
    abas = st.tabs(["📊 Dashboard", "🔄 Lançar Entrada/Saída", "📈 Relatórios Gerais", label_correcoes, "🏷️ Categorias"])
    aba_dash, aba_mov, aba_rel, aba_ajuste, aba_cat = abas
else:
    num_notif = contar_notificacoes_operador(st.session_state["usuario"])
    label_solic_op = f"🛠️ Solicitar Correção (🔔 {num_notif})" if num_notif > 0 else "🛠️ Solicitar Correção"
    abas = st.tabs(["📊 Dashboard", "🔄 Lançar Entrada/Saída", "📈 Meus Relatórios", label_solic_op])
    aba_dash, aba_mov, aba_rel, aba_ajuste = abas

# --- ABA 1: DASHBOARD ---
with aba_dash:
    col_dash_title, col_dash_btn = st.columns([4, 1])
    with col_dash_title:
        st.subheader("📊 Visão Geral do Estoque")
    with col_dash_btn:
        if st.button("🔄 Atualizar Visão", key="btn_ref_dash", use_container_width=True):
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
        col2.metric("Itens em Estoque Crítico", (df_produtos["status"] == "⚠️ CRÍTICO").sum())

        pdf_bytes = gerar_pdf_relatorio(df_produtos, "Estoque Geral Atual")
        
        col_dl1, col_dl2 = st.columns([3, 1])
        with col_dl1:
            btn_pdf = st.download_button(
                "📄 Emitir e Baixar Relatório em PDF", 
                data=pdf_bytes, 
                file_name="estoque_atual.pdf", 
                mime="application/pdf", 
                use_container_width=True
            )
        
        if btn_pdf:
            st.success("✅ Relatório em PDF gerado com sucesso!")
            st.balloons()

        fig_status = px.pie(df_produtos, names="status", color="status", color_discrete_map={"⚠️ CRÍTICO": "#FF4B4B", "✅ NORMAL": "#00CC96"}, hole=0.4)
        st.plotly_chart(fig_status, use_container_width=True)

        st.dataframe(df_produtos[['sku', 'nome', 'categoria', 'qtd_estoque', 'qtd_minima', 'status']], use_container_width=True)
    else:
        st.info("Nenhum produto cadastrado no sistema.")

# --- ABA 2: LANÇAMENTO ---
with aba_mov:
    col_mov_title, col_mov_btn = st.columns([4, 1])
    with col_mov_title:
        st.subheader("🔄 Lançamento de Entrada / Saída de Materiais")
    with col_mov_btn:
        if st.button("🔄 Atualizar Lista", key="btn_ref_mov", use_container_width=True):
            st.rerun()

    conn = get_connection()
    prods = pd.read_sql_query("SELECT sku, nome FROM produtos ORDER BY nome ASC", conn)
    conn.close()

    if not prods.empty:
        opcoes = {f"{row['sku']} - {row['nome']}": row["sku"] for _, row in prods.iterrows()}
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
                    st.error(f"Estoque insuficiente! Estoque atual: {qtd_atual}")
                else:
                    c.execute("UPDATE produtos SET qtd_estoque = qtd_estoque + ? WHERE sku = ?", (qtd * fator, sku_sel))
                    c.execute("""
                        INSERT INTO movimentacoes (sku, tipo, quantidade, descricao, data, usuario, status) 
                        VALUES (?, ?, ?, ?, ?, ?, 'Concluido')
                    """, (sku_sel, tipo, qtd, descricao, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), st.session_state["usuario"]))
                    conn.commit()
                    st.success(f"Lançamento de {tipo} realizado com sucesso!")
                conn.close()
                st.rerun()
    else:
        st.warning("Nenhum produto cadastrado.")

# --- ABA RELATÓRIOS ---
with aba_rel:
    if perfil_atual in ["Admin", "Supervisor"]:
        st.subheader("📈 Relatórios Gerais Avançados e Formalização por Período")
    else:
        st.subheader(f"📈 Meus Relatórios de Lançamentos ({st.session_state['usuario']})")
    
    tipo_relatorio_op = st.selectbox(
        "Selecione o Modelo de Relatório Formal",
        [
            "Relatório Geral de Movimentações (Entradas e Saídas)",
            "Relatório Analítico de Entradas",
            "Relatório Analítico de Saídas",
            "Relatório de Itens Críticos / Abaixo do Mínimo"
        ]
    )

    st.markdown("---")
    st.subheader("📅 Confirmação de Período")
    
    col_f1, col_f2, col_f3 = st.columns([2, 2, 2])
    with col_f1:
        periodo = st.selectbox("Selecione o Filtro de Período", ["Hoje (Dia)", "Última Semana (7 dias)", "Mês Atual", "Ano Atual", "Personalizado"])
    
    data_hoje = datetime.date.today()
    if periodo == "Hoje (Dia)":
        dt_inicio = data_hoje
        dt_fim = data_hoje
        label_periodo = f"Dia {data_hoje.strftime('%d/%m/%Y')}"
    elif periodo == "Última Semana (7 dias)":
        dt_inicio = data_hoje - datetime.timedelta(days=7)
        dt_fim = data_hoje
        label_periodo = "Últimos 7 Dias"
    elif periodo == "Mês Atual":
        dt_inicio = datetime.date(data_hoje.year, data_hoje.month, 1)
        dt_fim = data_hoje
        label_periodo = f"Mês Atual ({data_hoje.strftime('%m/%Y')})"
    elif periodo == "Ano Atual":
        dt_inicio = datetime.date(data_hoje.year, 1, 1)
        dt_fim = data_hoje
        label_periodo = f"Ano de {data_hoje.year}"
    else:
        with col_f2:
            dt_inicio = st.date_input("Data Inicial", data_hoje - datetime.timedelta(days=30))
        with col_f3:
            dt_fim = st.date_input("Data Final", data_hoje)
        label_periodo = f"Período de {dt_inicio.strftime('%d/%m/%Y')} até {dt_fim.strftime('%d/%m/%Y')}"

    confirmar_periodo = st.button("🔍 Confirmar Período e Gerar Relatório", type="primary", use_container_width=True)

    if confirmar_periodo:
        st.success(f"✅ Período confirmado: **{label_periodo}** para o relatório: *{tipo_relatorio_op}*.")

    st.divider()
    str_inicio = f"{dt_inicio.strftime('%Y-%m-%d')} 00:00:00"
    str_fim = f"{dt_fim.strftime('%Y-%m-%d')} 23:59:59"

    conn = get_connection()
    base_query = """
        SELECT m.id as 'ID', m.data as 'Data', m.tipo as 'Tipo', m.sku as 'SKU', 
               p.nome as 'Produto', m.quantidade as 'Qtd', m.usuario as 'Usuário', 
               m.descricao as 'Descrição', m.status as 'Status' 
        FROM movimentacoes m 
        JOIN produtos p ON m.sku = p.sku 
    """
    
    if perfil_atual in ["Admin", "Supervisor"]:
        if "Entradas" in tipo_relatorio_op:
            q = base_query + " WHERE m.tipo = 'Entrada' AND m.data BETWEEN ? AND ? ORDER BY m.id DESC"
            df_m = pd.read_sql_query(q, conn, params=(str_inicio, str_fim))
        elif "Saídas" in tipo_relatorio_op:
            q = base_query + " WHERE m.tipo = 'Saída' AND m.data BETWEEN ? AND ? ORDER BY m.id DESC"
            df_m = pd.read_sql_query(q, conn, params=(str_inicio, str_fim))
        elif "Críticos" in tipo_relatorio_op:
            df_m = pd.read_sql_query("SELECT sku as 'SKU', nome as 'Produto', categoria as 'Categoria', qtd_estoque as 'Qtd Atual', qtd_minima as 'Qtd Mínima', preco_unitario as 'Preço' FROM produtos WHERE qtd_estoque <= qtd_minima", conn)
        else:
            q = base_query + " WHERE m.data BETWEEN ? AND ? ORDER BY m.id DESC"
            df_m = pd.read_sql_query(q, conn, params=(str_inicio, str_fim))
    else:
        q = base_query + " WHERE m.usuario = ? AND m.data BETWEEN ? AND ? ORDER BY m.id DESC"
        df_m = pd.read_sql_query(q, conn, params=(st.session_state["usuario"], str_inicio, str_fim))
    
    conn.close()

    if not df_m.empty:
        st.markdown(f"### Visualização Formal: *{tipo_relatorio_op}*")
        st.caption(f"Período validado: {label_periodo}")
        st.dataframe(df_m, use_container_width=True)

        if "Críticos" in tipo_relatorio_op:
            pdf_bytes_rep = gerar_pdf_relatorio(df_m, tipo_relatorio_op)
        else:
            pdf_bytes_rep = gerar_pdf_movimentacoes_formal(df_m, label_periodo, tipo_relatorio_op)

        btn_dl_formal = st.download_button(
            "📥 Baixar Relatório Formal em PDF",
            data=pdf_bytes_rep,
            file_name="relatorio_formal_almoxarifado.pdf",
            mime="application/pdf",
            use_container_width=True
        )
        if btn_dl_formal:
            st.success("✅ Relatório formal exportado com sucesso!")
            st.balloons()
    else:
        st.info("Nenhum registo encontrado para o período e modelo selecionados.")

# --- ABA CORREÇÃO / APROVAÇÃO E NOTIFICAÇÕES ---
with aba_ajuste:
    if perfil_atual in ["Admin", "Supervisor"]:
        st.subheader("⚠️ Gestão e Aprovação de Solicitações de Correção")
        
        conn = get_connection()
        df_sol = pd.read_sql_query("SELECT s.id as 'ID_Solicitacao', s.movimentacao_id as 'ID_Mov', m.sku, p.nome as 'Produto', m.tipo, m.quantidade, s.solicitante, s.motivo, s.status FROM solicitacoes_ajuste s JOIN movimentacoes m ON s.movimentacao_id = m.id JOIN produtos p ON m.sku = p.sku WHERE s.status = 'Pendente'", conn)
        conn.close()
        
        if not df_sol.empty:
            st.markdown("### 📋 Solicitações Pendentes de Operadores")
            st.dataframe(df_sol, use_container_width=True)
            
            with st.form("form_aprova_detalhado"):
                sid = st.selectbox("Selecione o ID da Solicitação para Avaliar", df_sol["ID_Solicitacao"].tolist())
                acao = st.radio("Decisão de Supervisão / Administração", ["Aprovar Correção", "Rejeitar Correção"], horizontal=True)
                resp_admin = st.text_area("Justificativa / Descrição (Enviada como notificação ao operador)")
                
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
                            c.execute("UPDATE produtos SET qtd_estoque = qtd_estoque + ? WHERE sku = ?", (qtd_m * f, sku_m))
                        
                        c.execute("UPDATE solicitacoes_ajuste SET status = ?, resposta_admin = ? WHERE id = ?", (novo_status_sol, resp_admin, sid))
                        conn.commit()
                        st.success(f"✅ Solicitação processada com sucesso! O operador foi notificado.")
                        st.balloons()
                    conn.close()
                    st.rerun()
        else:
            st.info("Não existem solicitações pendentes de operadores no momento.")
    else:
        # Painel do Operador para solicitar e acompanhar notificações de resposta
        st.subheader("🛠️ Minhas Solicitações e Notificações de Correção")
        st.caption("Aqui pode acompanhar o status das suas solicitações de correção avaliadas pela supervisão/administração.")
        
        conn = get_connection()
        df_notif = pd.read_sql_query("""
            SELECT s.id as 'ID', m.data as 'Data Mov.', m.tipo as 'Tipo', p.nome as 'Produto', 
                   s.motivo as 'Meu Motivo', s.status as 'Status', 
                   COALESCE(s.resposta_admin, 'Aguardando análise') as 'Resposta da Administração' 
            FROM solicitacoes_ajuste s 
            JOIN movimentacoes m ON s.movimentacao_id = m.id 
            JOIN produtos p ON m.sku = p.sku 
            WHERE s.solicitante = ? 
            ORDER BY s.id DESC
        """, conn, params=(st.session_state["usuario"],))
        conn.close()

        if not df_notif.empty:
            st.dataframe(df_notif, use_container_width=True)
        else:
            st.info("Ainda não possui solicitações registadas.")

        st.divider()
        st.markdown("### 📝 Nova Solicitação de Correção / Estorno")
        
        conn = get_connection()
        df_minhas_mov = pd.read_sql_query("SELECT m.id as 'ID', m.data as 'Data', m.tipo as 'Tipo', p.nome as 'Produto', m.quantidade as 'Qtd', m.descricao as 'Descrição' FROM movimentacoes m JOIN produtos p ON m.sku = p.sku WHERE m.usuario = ? ORDER BY m.id DESC LIMIT 30", conn, params=(st.session_state["usuario"],))
        conn.close()

        if not df_minhas_mov.empty:
            with st.form("form_pedir_correcão", clear_on_submit=True):
                mov_id_sel = st.selectbox("Selecione o ID do Lançamento para Solicitar Correção", df_minhas_mov["ID"].tolist())
                motivo_solic = st.text_area("Motivo detalhado da solicitação (ex: Quantidade lançada incorretamente)")
                
                if st.form_submit_button("📨 Enviar Solicitação aos Administradores/Supervisores", use_container_width=True):
                    if motivo_solic.strip():
                        conn = get_connection()
                        c = conn.cursor()
                        c.execute("""
                            INSERT INTO solicitacoes_ajuste (movimentacao_id, solicitante, motivo, status, data_solicitacao, resposta_admin)
                            VALUES (?, ?, ?, 'Pendente', ?, 'Aguardando avaliação')
                        """, (mov_id_sel, st.session_state["usuario"], motivo_solic, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                        conn.commit()
                        conn.close()
                        st.success("✅ Solicitação enviada com sucesso!")
                        st.balloons()
                        st.rerun()
                    else:
                        st.warning("Por favor, preencha o motivo da solicitação.")

# --- ABA CATEGORIAS (SUPERVISOR) ---
if perfil_atual == "Supervisor":
    with aba_cat:
        st.subheader("🏷️️ Categorias de Produtos")
        conn = get_connection()
        st.dataframe(pd.read_sql_query("SELECT nome FROM categorias", conn), use_container_width=True)
        conn.close()

# --- GESTÃO DE PRODUTOS E UTILIZADORES (ADMIN) ---
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
                        c.execute("INSERT OR REPLACE INTO produtos VALUES (?, ?, ?, 0, ?, ?)", (sku, nome, cat, qmin, preco))
                        conn.commit()
                        conn.close()
                        st.success("Cadastrado com sucesso!")
                        st.rerun()

        with tab_p4:
            st.subheader("🗑️ Zerar Estoque")
            conn = get_connection()
            df_z = pd.read_sql_query("SELECT sku, nome, qtd_estoque FROM produtos", conn)
            conn.close()

            if not df_z.empty:
                op_z = {f"{r['sku']} - {r['nome']} (Qtd: {r['qtd_estoque']})": r['sku'] for _, r in df_z.iterrows()}
                sel_z = st.selectbox("Produto para Zerar", list(op_z.keys()))
                sku_z = op_z[sel_z]

                if st.button("Zerar Este Produto Agora", type="primary"):
                    conn = get_connection()
                    c = conn.cursor()
                    c.execute("UPDATE produtos SET qtd_estoque = 0 WHERE sku = ?", (sku_z,))
                    conn.commit()
                    conn.close()
                    st.success(f"✅ Confirmação: O estoque do produto SKU {sku_z} foi totalmente zerado com sucesso!")
                    st.balloons()
                    st.rerun()

                st.divider()
                if st.button("⚠️ ZERAR TODO O ESTOQUE DO SISTEMA", type="primary"):
                    conn = get_connection()
                    c = conn.cursor()
                    c.execute("UPDATE produtos SET qtd_estoque = 0")
                    conn.commit()
                    conn.close()
                    st.success("✅ Confirmação: Todo o estoque do sistema foi zerado com sucesso!")
                    st.balloons()
                    st.rerun()
            else:
                st.info("Nenhum produto cadastrado.")

        with tab_p5:
            st.subheader("📥 Importação em Lote por Planilha (Padrão exato: sku, nome, categoria, minimo, preco, quantidade)")
            
            df_mod = pd.DataFrame([
                {"sku": "ALM-001", "nome": "Papel Sulfite A4 75g", "categoria": "Consumíveis", "minimo": 10, "preco": 25.5, "quantidade": 200},
                {"sku": "ALM-002", "nome": "Caneta Esferográfica Azul", "categoria": "Escritório", "minimo": 20, "preco": 1.56, "quantidade": 200}
            ])
            st.download_button("Baixar Modelo CSV Exato", data=df_mod.to_csv(index=False, sep=';', encoding='utf-8-sig').encode('utf-8-sig'), file_name="modelo_almoxarifado.csv", mime="text/csv")

            if "up_key" not in st.session_state:
                st.session_state["up_key"] = 0

            up_file = st.file_uploader("Enviar Planilha CSV ou Excel", type=["csv", "xlsx", "txt"], key=f"up_{st.session_state['up_key']}")

            if up_file is not None:
                try:
                    if up_file.name.endswith(".csv") or up_file.name.endswith(".txt"):
                        content_bytes = up_file.getvalue()
                        try:
                            df_imp = pd.read_csv(io.BytesIO(content_bytes), sep=';')
                            if len(df_imp.columns) <= 1:
                                df_imp = pd.read_csv(io.BytesIO(content_bytes), sep=',')
                        except:
                            df_imp = pd.read_csv(io.BytesIO(content_bytes), sep=',')
                    else:
                        df_imp = pd.read_excel(up_file)

                    df_imp.columns = [str(c).strip().replace('\ufeff', '').lower() for c in df_imp.columns]
                    st.dataframe(df_imp.head(10), use_container_width=True)

                    if st.button("Executar Importação e Atualizar Estoque", type="primary"):
                        conn = get_connection()
                        c = conn.cursor()
                        count = 0
                        
                        for _, row in df_imp.iterrows():
                            s = str(row.get("sku", row.get("código", row.get("codigo", "")))).strip()
                            n = str(row.get("nome", row.get("nome do produto", row.get("produto", "Produto")))).strip()
                            cat = str(row.get("categoria", "Geral")).strip()
                            qmin = int(row.get("minimo", row.get("mínimo", row.get("estoque mínimo", row.get("estoque minimo", 5)))))
                            preco = float(row.get("preco", row.get("preço", row.get("preço unitário", row.get("preco unitario", 0.0)))))
                            qtd = int(row.get("quantidade", row.get("qtd", row.get("quantidade inicial", row.get("quantidade inicial", 0)))))

                            if s and s != "nan":
                                c.execute("SELECT qtd_estoque FROM produtos WHERE sku = ?", (s,))
                                exists = c.fetchone()
                                if exists:
                                    c.execute("UPDATE produtos SET nome = ?, categoria = ?, qtd_estoque = qtd_estoque + ?, qtd_minima = ?, preco_unitario = ? WHERE sku = ?", (n, cat, qtd, qmin, preco, s))
                                else:
                                    c.execute("INSERT INTO produtos VALUES (?, ?, ?, ?, ?, ?)", (s, n, cat, qtd, qmin, preco))
                                
                                if qtd > 0:
                                    c.execute("INSERT INTO movimentacoes (sku, tipo, quantidade, descricao, data, usuario, status) VALUES (?, 'Entrada', ?, 'Importação em lote', ?, ?, 'Concluido')", (s, qtd, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), st.session_state["usuario"]))
                                count += 1

                        conn.commit()
                        conn.close()
                        st.success(f"✅ Confirmação: Importação concluída! {count} itens processados e estoque atualizado no Dashboard.")
                        st.session_state["up_key"] += 1
                        st.rerun()
                except Exception as e:
                    st.error(f"Erro ao processar arquivo: {e}")

    with aba_cat:
        st.subheader("🏷️ Categorias")
        conn = get_connection()
        st.dataframe(pd.read_sql_query("SELECT nome FROM categorias", conn), use_container_width=True)
        conn.close()

    with aba_usr:
        st.subheader("👥 Gestão de Utilizadores (Incluir, Bloquear e Remover)")
        
        tab_u1, tab_u2 = st.tabs(["➕ Incluir Novo Utilizador", "⚙️️ Gerir / Bloquear / Remover Utilizadores"])
        
        with tab_u1:
            with st.form("form_novo_user", clear_on_submit=True):
                novo_user = st.text_input("Nome de Utilizador (Login)").strip()
                nova_senha_user = st.text_input("Senha", type="password")
                # Incluindo a opção 'Supervisor' no cadastro de novos utilizadores
                perfil_user = st.selectbox("Perfil de Acesso", ["Operador", "Supervisor", "Admin"])
                pergunta_sec = st.text_input("Pergunta Secreta (ex: Qual a cidade natal?)", value="Qual a cidade natal?")
                resposta_sec = st.text_input("Resposta Secreta", type="password")
                
                if st.form_submit_button("Cadastrar Utilizador", type="primary"):
                    if novo_user and nova_senha_user and resposta_sec:
                        try:
                            conn = get_connection()
                            c = conn.cursor()
                            c.execute("""
                                INSERT INTO usuarios (username, senha, perfil, status, pergunta_secreta, resposta_secreta)
                                VALUES (?, ?, ?, 'Ativo', ?, ?)
                            """, (novo_user, hash_senha(nova_senha_user), perfil_user, pergunta_sec, hash_senha(resposta_sec)))
                            conn.commit()
                            conn.close()
                            st.success(f"✅ Utilizador '{novo_user}' ({perfil_user}) cadastrado com sucesso!")
                        except sqlite3.IntegrityError:
                            st.error("Erro: Este nome de utilizador já existe no sistema.")
                    else:
                        st.warning("Preencha todos os campos obrigatórios.")

        with tab_u2:
            conn = get_connection()
            df_usuarios = pd.read_sql_query("SELECT username, perfil, status FROM usuarios", conn)
            conn.close()

            if not df_usuarios.empty:
                st.dataframe(df_usuarios, use_container_width=True)
                
                st.divider()
                st.subheader("⚙️ Ações sobre Utilizadores")
                
                lista_usuarios_sistema = df_usuarios["username"].tolist()
                user_selecionado = st.selectbox("Selecione o Utilizador", lista_usuarios_sistema)
                
                col_acao1, col_acao2 = st.columns(2)
                
                with col_acao1:
                    novo_status_acao = st.radio("Alterar Status / Bloqueio", ["Ativo", "Bloqueado"], horizontal=True)
                    if st.button("Atualizar Status do Utilizador", use_container_width=True):
                        if user_selecionado == "admin" and novo_status_acao == "Bloqueado":
                            st.error("Não é permitido bloquear o administrador principal ('admin').")
                        else:
                            conn = get_connection()
                            c = conn.cursor()
                            c.execute("UPDATE usuarios SET status = ? WHERE username = ?", (novo_status_acao, user_selecionado))
                            conn.commit()
                            conn.close()
                            st.success(f"Status do utilizador '{user_selecionado}' alterado para: {novo_status_acao}")
                            st.rerun()

                with col_acao2:
                    st.write("🗑️️ **Remover Utilizador**")
                    if st.button("Excluir Utilizador Definitivamente", type="primary", use_container_width=True):
                        if user_selecionado == "admin":
                            st.error("Não é permitido excluir o utilizador administrador principal ('admin').")
                        elif user_selecionado == st.session_state["usuario"]:
                            st.error("Not pode excluir a sua própria conta enquanto está conectado.")
                        else:
                            conn = get_connection()
                            c = conn.cursor()
                            c.execute("DELETE FROM usuarios WHERE username = ?", (user_selecionado,))
                            conn.commit()
                            conn.close()
                            st.success(f"Utilizador '{user_selecionado}' removido com sucesso!")
                            st.rerun()
            else:
                st.info("Nenhum utilizador registado.")
