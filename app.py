import datetime
import hashlib
import io
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

# CSS para otimização mobile
st.markdown("""
    <style>
        @media (max-width: 768px) {
            .stMetric { background-color: #f8fafc; padding: 10px; border-radius: 8px; margin-bottom: 10px; }
            .stButton>button { width: 100%; margin-top: 5px; }
        }
    </style>
""", unsafe_allow_html=True)

# --- BANCO DE DADOS E SEGURANÇA ---
def hash_senha(senha):
    return hashlib.sha256(str.encode(senha)).hexdigest()

def get_connection():
    return sqlite3.connect("almoxarifado.db", check_same_thread=False)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    # Tabela de Usuários
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

    colunas_usuario = [col[1] for col in c.execute("PRAGMA table_info(usuarios)").fetchall()]
    if 'status' not in colunas_usuario:
        c.execute("ALTER TABLE usuarios ADD COLUMN status TEXT DEFAULT 'Ativo'")
    if 'pergunta_secreta' not in colunas_usuario:
        c.execute("ALTER TABLE usuarios ADD COLUMN pergunta_secreta TEXT")
    if 'resposta_secreta' not in colunas_usuario:
        c.execute("ALTER TABLE usuarios ADD COLUMN resposta_secreta TEXT")
    
    # Tabela de Categorias
    c.execute("""
        CREATE TABLE IF NOT EXISTS categorias (
            nome TEXT PRIMARY KEY
        )
    """)
    
    # Tabela de Produtos
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
    
    # Tabela de Movimentações
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

    colunas_mov = [col[1] for col in c.execute("PRAGMA table_info(movimentacoes)").fetchall()]
    if 'status' not in colunas_mov:
        c.execute("ALTER TABLE movimentacoes ADD COLUMN status TEXT DEFAULT 'Concluido'")
    if 'descricao' not in colunas_mov:
        c.execute("ALTER TABLE movimentacoes ADD COLUMN descricao TEXT")
    
    # Tabela de Solicitações de Ajuste / Estorno
    c.execute("""
        CREATE TABLE IF NOT EXISTS solicitacoes_ajuste (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            movimentacao_id INTEGER,
            solicitante TEXT,
            motivo TEXT,
            status TEXT DEFAULT 'Pendente',
            data_solicitacao TEXT
        )
    """)

    # Categorias padrão
    c.execute("SELECT count(*) FROM categorias")
    if c.fetchone()[0] == 0:
        c.executemany("INSERT INTO categorias VALUES (?)", [('Ferramentas',), ('EPIs',), ('Consumíveis',), ('Outros',)])

    # Usuário admin padrão
    c.execute("SELECT * FROM usuarios WHERE username = 'admin'")
    if not c.fetchone():
        c.execute("""
            INSERT INTO usuarios VALUES ('admin', ?, 'Admin', 'Ativo', 'Qual a cidade natal?', ?)
        """, (hash_senha("admin123"), hash_senha("admin")))
    else:
        c.execute("""
            UPDATE usuarios 
            SET pergunta_secreta = 'Qual a cidade natal?', resposta_secreta = ?
            WHERE username = 'admin' AND (pergunta_secreta IS NULL OR pergunta_secreta = '')
        """, (hash_senha("admin"),))

    conn.commit()
    conn.close()

def contar_solicitacoes_pendentes_admin():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM solicitacoes_ajuste WHERE status = 'Pendente'")
    total = c.fetchone()[0]
    conn.close()
    return total

def contar_solicitacoes_operador(usuario):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM solicitacoes_ajuste WHERE solicitante = ?", (usuario,))
    total = c.fetchone()[0]
    conn.close()
    return total

init_db()

# --- GERADORES DE RELATÓRIO PDF ---
def gerar_pdf_relatorio(df_produtos):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=15, leftMargin=15, topMargin=15, bottomMargin=15)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#0f172a'))
    story.append(Paragraph("Relatório de Controle de Estoque Atual", title_style))
    story.append(Paragraph(f"Gerado em: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
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

    tabela = Table(dados, colWidths=[50, 140, 80, 40, 40, 60, 60])
    tabela.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
    ]))
    story.append(tabela)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def gerar_pdf_movimentacoes(df_mov, titulo_periodo):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=15, leftMargin=15, topMargin=15, bottomMargin=15)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#0f172a'))
    story.append(Paragraph(f"Relatório de Movimentações - {titulo_periodo}", title_style))
    story.append(Paragraph(f"Gerado em: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
    story.append(Spacer(1, 10))

    dados = [["ID", "Data", "Tipo", "SKU/Produto", "Qtd", "Usuário", "Descrição"]]
    for _, r in df_mov.iterrows():
        desc = str(r['Descrição']) if pd.notna(r['Descrição']) else ""
        if len(desc) > 25:
            desc = desc[:22] + "..."
        dados.append([
            str(r['ID']), str(r['Data']), str(r['Tipo']),
            f"{r['SKU']} - {r['Produto']}", str(r['Qtd']),
            str(r['Usuário']), desc
        ])

    tabela = Table(dados, colWidths=[30, 85, 50, 140, 35, 65, 115])
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

# --- TELA DE LOGIN / RECUPERAÇÃO ---
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
            usuario = st.text_input("Usuário").strip()
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
                        st.error("Usuário bloqueado. Contate o Administrador.")
                    else:
                        st.session_state["logado"] = True
                        st.session_state["usuario"] = usuario
                        st.session_state["perfil"] = perfil
                        st.rerun()
                else:
                    st.error("Usuário ou senha incorretos.")

        if st.button("Esqueci minha senha"):
            st.session_state["modo_login"] = "recuperar"
            st.rerun()

    elif st.session_state["modo_login"] == "recuperar":
        st.subheader("🔑 Recuperação de Senha")
        usr_rec = st.text_input("Informe seu nome de Usuário").strip()

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
                st.warning("Usuário não possui pergunta de segurança cadastrada.")
            else:
                st.error("Usuário não encontrado.")

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

# Configuração de Notificações nos Títulos das Guia
if st.session_state["perfil"] == "Admin":
    num_pendentes = contar_solicitacoes_pendentes_admin()
    label_correcoes = f"🛠️ Correções / Estornos (🔴 {num_pendentes})" if num_pendentes > 0 else "🛠️ Correções / Estornos"
    abas = st.tabs(["📊 Dashboard", "🔄 Lançar Entrada/Saída", "📈 Relatórios Avançados", label_correcoes, "📝 Produtos", "🏷️ Categorias", "👥 Usuários"])
    aba_dash, aba_mov, aba_rel, aba_ajuste, aba_prod, aba_cat, aba_usr = abas
else:
    num_solic_operador = contar_solicitacoes_operador(st.session_state["usuario"])
    label_solic_op = f"🛠️ Solicitar Correção (🔴 {num_solic_operador})" if num_solic_operador > 0 else "🛠️ Solicitar Correção"
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

        pdf_bytes = gerar_pdf_relatorio(df_produtos)
        st.download_button("📄 Exportar Estoque em PDF", data=pdf_bytes, file_name="estoque_atual.pdf", mime="application/pdf", use_container_width=True)

        fig_status = px.pie(df_produtos, names="status", color="status", color_discrete_map={"⚠️ CRÍTICO": "#FF4B4B", "✅ NORMAL": "#00CC96"}, hole=0.4)
        st.plotly_chart(fig_status, use_container_width=True)

        st.dataframe(df_produtos[['sku', 'nome', 'categoria', 'qtd_estoque', 'qtd_minima', 'status']], use_container_width=True)
    else:
        st.info("Nenhum produto cadastrado no sistema.")

# --- ABA 2: LANÇAMENTO DE ENTRADA E SAÍDA ---
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
            descricao = st.text_input("Descrição / Observação do Lançamento (ex: Nota Fiscal 1234, Uso na Obra X, Recebido de Fornecedor)")

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
        st.warning("Nenhum produto cadastrado. O Administrador precisa cadastrar produtos antes do lançamento.")

# --- ABA RELATÓRIOS (ADMIN E OPERADOR) ---
with aba_rel:
    if st.session_state["perfil"] == "Admin":
        st.subheader("📈 Relatórios Avançados e Filtros por Período")
    else:
        st.subheader(f"📈 Meus Relatórios de Lançamentos ({st.session_state['usuario']})")
    
    # Filtros Superiores
    col_f1, col_f2, col_f3 = st.columns([2, 2, 2])
    
    with col_f1:
        periodo = st.selectbox("Selecione o Período", ["Hoje (Dia)", "Última Semana (7 dias)", "Mês Atual", "Ano Atual", "Personalizado"])
    
    data_hoje = datetime.date.today()
    
    if periodo == "Hoje (Dia)":
        dt_inicio = data_hoje
        dt_fim = data_hoje
        label_periodo = f"Dia {data_hoje.strftime('%d/%m/%Y')}"
    elif periodo == "Última Semana (7 dias)":
        dt_inicio = data_hoje - datetime.timedelta(days=7)
        dt_fim = data_hoje
        label_periodo = f"Semana ({dt_inicio.strftime('%d/%m')} a {dt_fim.strftime('%d/%m/%Y')})"
    elif periodo == "Mês Atual":
        dt_inicio = datetime.date(data_hoje.year, data_hoje.month, 1)
        dt_fim = data_hoje
        label_periodo = f"Mês {data_hoje.strftime('%m/%Y')}"
    elif periodo == "Ano Atual":
        dt_inicio = datetime.date(data_hoje.year, 1, 1)
        dt_fim = data_hoje
        label_periodo = f"Ano {data_hoje.year}"
    else:
        with col_f2:
            dt_inicio = st.date_input("Data Inicial", data_hoje - datetime.timedelta(days=30))
        with col_f3:
            dt_fim = st.date_input("Data Final", data_hoje)
        label_periodo = f"Período de {dt_inicio.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')}"

    st.divider()

    if st.session_state["perfil"] == "Admin":
        tab_rel1, tab_rel2 = st.tabs(["📥 Outflows / Inflows (Entrada e Saída)", "🛠️ Histórico de Correções e Usuários"])
    else:
        tab_rel1 = st.container()

    # Conteúdo de Movimentações
    with tab_rel1:
        col_t1, col_t2 = st.columns([2, 2])
        with col_t1:
            filtro_tipo = st.multiselect("Filtrar Tipo de Operação", ["Entrada", "Saída"], default=["Entrada", "Saída"])
        
        str_inicio = f"{dt_inicio.strftime('%Y-%m-%d')} 00:00:00"
        str_fim = f"{dt_fim.strftime('%Y-%m-%d')} 23:59:59"

        conn = get_connection()
        if st.session_state["perfil"] == "Admin":
            df_m = pd.read_sql_query("""
                SELECT m.id as 'ID', m.data as 'Data', m.tipo as 'Tipo', m.sku as 'SKU', p.nome as 'Produto', 
                       m.quantidade as 'Qtd', m.usuario as 'Usuário', m.descricao as 'Descrição', m.status as 'Status'
                FROM movimentacoes m
                JOIN produtos p ON m.sku = p.sku
                WHERE m.data BETWEEN ? AND ?
                ORDER BY m.id DESC
            """, conn, params=(str_inicio, str_fim))
        else:
            df_m = pd.read_sql_query("""
                SELECT m.id as 'ID', m.data as 'Data', m.tipo as 'Tipo', m.sku as 'SKU', p.nome as 'Produto', 
                       m.quantidade as 'Qtd', m.usuario as 'Usuário', m.descricao as 'Descrição', m.status as 'Status'
                FROM movimentacoes m
                JOIN produtos p ON m.sku = p.sku
                WHERE m.usuario = ? AND m.data BETWEEN ? AND ?
                ORDER BY m.id DESC
            """, conn, params=(st.session_state["usuario"], str_inicio, str_fim))
        conn.close()

        if not df_m.empty and filtro_tipo:
            df_m_filtrado = df_m[df_m["Tipo"].isin(filtro_tipo)]
            
            c_m1, c_m2, c_m3 = st.columns(3)
            c_m1.metric("Lançamentos Encontrados", len(df_m_filtrado))
            c_m2.metric("Total Unidades Entradas", df_m_filtrado[df_m_filtrado["Tipo"]=="Entrada"]["Qtd"].sum() if "Entrada" in filtro_tipo else 0)
            c_m3.metric("Total Unidades Saídas", df_m_filtrado[df_m_filtrado["Tipo"]=="Saída"]["Qtd"].sum() if "Saída" in filtro_tipo else 0)

            st.dataframe(df_m_filtrado, use_container_width=True)

            col_e1, col_e2 = st.columns(2)
            with col_e1:
                csv_data = df_m_filtrado.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Exportar Meus Lançamentos (CSV)", data=csv_data, file_name=f"meus_lancamentos_{periodo}.csv", mime="text/csv", use_container_width=True)
            with col_e2:
                pdf_mov_bytes = gerar_pdf_movimentacoes(df_m_filtrado, label_periodo)
                st.download_button("📄 Exportar Meus Lançamentos (PDF)", data=pdf_mov_bytes, file_name=f"meus_lancamentos_{periodo}.pdf", mime="application/pdf", use_container_width=True)
        else:
            st.info("Nenhuma movimentação registrada no período selecionado.")

    if st.session_state["perfil"] == "Admin":
        with tab_rel2:
            conn = get_connection()
            # CONSULTA CORRIGIDA COM O JOIN EM PRODUTOS P:
            df_c = pd.read_sql_query("""
                SELECT s.id as 'ID_Solicitacao', s.data_solicitacao as 'Data', s.movimentacao_id as 'ID_Mov_Original', 
                       m.sku as 'SKU', p.nome as 'Produto', m.tipo as 'Tipo_Original', m.quantidade as 'Qtd_Original',
                       s.solicitante as 'Solicitante_Operador', s.motivo as 'Motivo_Correção', s.status as 'Status_Aprovação'
                FROM solicitacoes_ajuste s
                JOIN movimentacoes m ON s.movimentacao_id = m.id
                JOIN produtos p ON m.sku = p.sku
                WHERE s.data_solicitacao BETWEEN ? AND ?
                ORDER BY s.id DESC
            """, conn, params=(str_inicio, str_fim))
            conn.close()

            if not df_c.empty:
                st.dataframe(df_c, use_container_width=True)
                csv_correcoes = df_c.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Exportar Correções em CSV", data=csv_correcoes, file_name=f"correcoes_{periodo}.csv", mime="text/csv", use_container_width=True)
            else:
                st.info("Nenhuma solicitação de correção ou estorno registrada no período selecionado.")

# --- ABA CORREÇÃO E SOLICITAÇÃO ---
with aba_ajuste:
    col_aj_title, col_aj_btn = st.columns([4, 1])
    with col_aj_title:
        st.subheader("⚠️ Correção e Estorno de Lançamentos")
    with col_aj_btn:
        if st.button("🔄 Atualizar Tabela", key="btn_ref_ajuste", use_container_width=True):
            st.rerun()

    # NOTIFICAÇÕES E SEÇÃO DO OPERADOR
    if st.session_state["perfil"] == "Operador":
        st.write("### 🔔 Painel de Acompanhamento das Suas Solicitações")
        
        conn = get_connection()
        df_minhas_solicitacoes = pd.read_sql_query("""
            SELECT s.id as 'ID_Solicitação', s.movimentacao_id as 'ID_Lançamento', 
                   s.motivo as 'Seu Motivo', s.status as 'Status_Decisão', s.data_solicitacao as 'Data'
            FROM solicitacoes_ajuste s
            WHERE s.solicitante = ?
            ORDER BY s.id DESC
        """, conn, params=(st.session_state["usuario"],))
        conn.close()

        if not df_minhas_solicitacoes.empty:
            st.dataframe(df_minhas_solicitacoes, use_container_width=True)
        else:
            st.info("Você ainda não realizou nenhuma solicitação de correção/estorno.")

        st.divider()

        conn = get_connection()
        df_mov = pd.read_sql_query("""
            SELECT m.id as 'ID_Lançamento', m.sku as 'SKU', p.nome as 'Produto', m.tipo as 'Tipo', 
                   m.quantidade as 'Qtd', m.descricao as 'Descrição', m.data as 'Data', m.status as 'Status'
            FROM movimentacoes m 
            JOIN produtos p ON m.sku = p.sku
            WHERE m.usuario = ?
            ORDER BY m.id DESC LIMIT 30
        """, conn, params=(st.session_state["usuario"],))
        conn.close()

        st.write("**Histórico dos seus Lançamentos Recentes:**")
        if not df_mov.empty:
            st.dataframe(df_mov, use_container_width=True)
        else:
            st.info("Nenhum lançamento registrado por você até o momento.")

        st.subheader("Nova Solicitação de Cancelamento/Estorno")
        with st.form("form_solicita_estorno"):
            mov_id = st.number_input("ID do Lançamento com Erro (consulte a tabela acima)", min_value=1, step=1)
            motivo = st.text_area("Descreva o Motivo da Correção (ex: Quantidade lançada errada)")
            if st.form_submit_button("Enviar para Autorização do Admin", use_container_width=True):
                conn = get_connection()
                c = conn.cursor()
                c.execute("SELECT status FROM movimentacoes WHERE id = ? AND usuario = ?", (mov_id, st.session_state["usuario"]))
                res = c.fetchone()
                
                if not res:
                    st.error(f"Lançamento com ID {mov_id} não foi encontrado entre seus lançamentos.")
                elif res[0] != 'Concluido':
                    st.warning(f"Lançamento ID {mov_id} já se encontra com status: {res[0]}")
                else:
                    c.execute("""
                        INSERT INTO solicitacoes_ajuste (movimentacao_id, solicitante, motivo, data_solicitacao) 
                        VALUES (?, ?, ?, ?)
                    """, (mov_id, st.session_state["usuario"], motivo, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                    conn.commit()
                    st.success("Solicitação enviada com sucesso ao Administrador!")
                conn.close()
                st.rerun()

    # SEÇÃO DO ADMINISTRADOR
    if st.session_state["perfil"] == "Admin":
        st.subheader("🛡️ Painel de Autorizações Pendentes")
        
        conn = get_connection()
        df_solicitacoes = pd.read_sql_query("""
            SELECT s.id as 'ID_Solicitacao', s.movimentacao_id as 'ID_Mov', m.sku, p.nome as 'Produto', m.tipo, m.quantidade, m.descricao, s.solicitante, s.motivo, s.data_solicitacao 
            FROM solicitacoes_ajuste s
            JOIN movimentacoes m ON s.movimentacao_id = m.id
            JOIN produtos p ON m.sku = p.sku
            WHERE s.status = 'Pendente'
        """, conn)
        conn.close()

        if not df_solicitacoes.empty:
            st.dataframe(df_solicitacoes, use_container_width=True)
            
            with st.form("form_aprova_estorno"):
                solic_id = st.selectbox("Selecione a Solicitação para Processar", df_solicitacoes["ID_Solicitacao"].tolist())
                decisao = st.radio("Ação do Admin", ["Aprovar e Estornar Lançamento", "Rejeitar Solicitação"], horizontal=True)

                if st.form_submit_button("Processar Autorização", use_container_width=True):
                    conn = get_connection()
                    c = conn.cursor()
                    
                    c.execute("""
                        SELECT m.id, m.sku, m.tipo, m.quantidade 
                        FROM solicitacoes_ajuste s
                        JOIN movimentacoes m ON s.movimentacao_id = m.id
                        WHERE s.id = ?
                    """, (solic_id,))
                    _, sku_m, tipo_m, qtd_m = c.fetchone()

                    if "Aprovar" in decisao:
                        fator_estorno = -1 if tipo_m == "Entrada" else 1
                        c.execute("UPDATE produtos SET qtd_estoque = qtd_estoque + ? WHERE sku = ?", (qtd_m * fator_estorno, sku_m))
                        c.execute("UPDATE movimentacoes SET status = 'Estornado/Corrigido' WHERE id = (SELECT movimentacao_id FROM solicitacoes_ajuste WHERE id = ?)", (solic_id,))
                        c.execute("UPDATE solicitacoes_ajuste SET status = 'Aprovado' WHERE id = ?", (solic_id,))
                        conn.commit()
                        st.success("Estorno AUTORIZADO! Estoque corrigido e solicitante notificado.")
                    else:
                        c.execute("UPDATE solicitacoes_ajuste SET status = 'Rejeitado' WHERE id = ?", (solic_id,))
                        conn.commit()
                        st.warning("Solicitação REJEITADA e solicitante notificado.")
                    
                    conn.close()
                    st.rerun()
        else:
            st.info("Nenhuma solicitação pendente no momento.")

        st.divider()

        # BOTÃO PARA LIMPAR SOLICITAÇÕES FINALIZADAS
        st.subheader("🧹 Limpeza e Manutenção da Tabela de Solicitações")
        col_limp1, col_limp2 = st.columns([3, 1])
        with col_limp1:
            st.write("Limpe do banco de dados o histórico de solicitações que já foram **Aprovadas** ou **Rejeitadas**.")
        with col_limp2:
            if st.button("🧹 Limpar Finalizadas", use_container_width=True):
                conn = get_connection()
                c = conn.cursor()
                c.execute("DELETE FROM solicitacoes_ajuste WHERE status IN ('Aprovado', 'Rejeitado')")
                removidos = c.rowcount
                conn.commit()
                conn.close()
                st.success(f"{removidos} solicitações finalizadas foram removidas do sistema!")
                st.rerun()

# --- DEMAIS ABAS (ADMIN) ---
if st.session_state["perfil"] == "Admin":
    with aba_prod:
        st.subheader("Cadastrar Produto")
        conn = get_connection()
        cats = pd.read_sql_query("SELECT nome FROM categorias ORDER BY nome ASC", conn)["nome"].tolist()
        conn.close()

        with st.form("form_cad_prod", clear_on_submit=True):
            sku = st.text_input("SKU / Código do Item")
            nome = st.text_input("Nome do Produto")
            categoria = st.selectbox("Categoria", cats if cats else ["Padrão"])
            qtd_min = st.number_input("Estoque Mínimo (Alerta)", value=5, step=1)
            preco = st.number_input("Preço Unitário (R$)", value=0.0, step=0.5)

            if st.form_submit_button("Salvar Produto", use_container_width=True):
                if sku and nome:
                    conn = get_connection()
                    c = conn.cursor()
                    try:
                        c.execute("INSERT INTO produtos VALUES (?, ?, ?, 0, ?, ?)", (sku, nome, categoria, qtd_min, preco))
                        conn.commit()
                        st.success("Produto cadastrado com sucesso!")
                    except sqlite3.IntegrityError:
                        st.error("SKU já cadastrado. Utilize um código único.")
                    finally:
                        conn.close()
                else:
                    st.error("Preencha o SKU e o Nome do Produto.")

    with aba_cat:
        st.subheader("🏷️ Gerenciar Categorias")
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            with st.form("form_add_cat", clear_on_submit=True):
                nova_cat = st.text_input("Nova Categoria").strip()
                if st.form_submit_button("Adicionar Categoria", use_container_width=True):
                    if nova_cat:
                        conn = get_connection()
                        c = conn.cursor()
                        try:
                            c.execute("INSERT INTO categorias VALUES (?)", (nova_cat,))
                            conn.commit()
                            st.success(f"Categoria '{nova_cat}' adicionada!")
                        except sqlite3.IntegrityError:
                            st.error("Categoria já existe.")
                        finally:
                            conn.close()

        with col_c2:
            conn = get_connection()
            df_cat = pd.read_sql_query("SELECT nome as 'Categoria' FROM categorias", conn)
            conn.close()
            st.dataframe(df_cat, use_container_width=True)

    with aba_usr:
        st.subheader("➕ Novo Usuário")
        with st.form("form_cad_usr", clear_on_submit=True):
            novo_usr = st.text_input("Usuário").strip()
            nova_senha = st.text_input("Senha", type="password")
            novo_perfil = st.selectbox("Perfil de Acesso", ["Operador", "Admin"])
            pergunta = st.text_input("Pergunta de Segurança para Recuperação")
            resposta = st.text_input("Resposta da Pergunta")

            if st.form_submit_button("Cadastrar Usuário", use_container_width=True):
                if novo_usr and nova_senha:
                    conn = get_connection()
                    c = conn.cursor()
                    try:
                        c.execute("INSERT INTO usuarios VALUES (?, ?, ?, 'Ativo', ?, ?)", 
                                  (novo_usr, hash_senha(nova_senha), novo_perfil, pergunta, hash_senha(resposta.lower())))
                        conn.commit()
                        st.success(f"Usuário '{novo_usr}' cadastrado com sucesso!")
                    except sqlite3.IntegrityError:
                        st.error("Nome de usuário já existente.")
                    finally:
                        conn.close()

        st.divider()
        st.subheader("⚙️ Usuários Cadastrados")
        conn = get_connection()
        df_usr = pd.read_sql_query("SELECT username as 'Usuário', perfil as 'Perfil', status as 'Status' FROM usuarios", conn)
        conn.close()
        st.dataframe(df_usr, use_container_width=True)