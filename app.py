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

# Limpa o cache do Streamlit para garantir dados atualizados a cada execução
st.cache_data.clear()

# CSS para otimização mobile
st.markdown("""
    
""", unsafe_allow_html=True)

# --- BANCO DE DADOS E SEGURANÇA ---
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
            data_solicitacao TEXT
        )
    """)

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

def contar_solicitacoes_operador(usuario):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM solicitacoes_ajuste WHERE solicitante = ?", (usuario,))
    total = c.fetchone()[0]
    conn.close()
    return total

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
                    st.error("Usuário ou senha incorretos. (Admin padrão: admin / admin123)")

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
    if st.session_state["perfil"] == "Admin":
        st.subheader("📈 Relatórios Avançados e Filtros por Período")
    else:
        st.subheader(f"📈 Meus Relatórios de Lançamentos ({st.session_state['usuario']})")
    
    col_f1, col_f2, col_f3 = st.columns([2, 2, 2])
    with col_f1:
        periodo = st.selectbox("Selecione o Período", ["Hoje (Dia)", "Última Semana (7 dias)", "Mês Atual", "Ano Atual", "Personalizado"])
    
    data_hoje = datetime.date.today()
    if periodo == "Hoje (Dia)":
        dt_inicio = data_hoje
        dt_fim = data_hoje
    elif periodo == "Última Semana (7 dias)":
        dt_inicio = data_hoje - datetime.timedelta(days=7)
        dt_fim = data_hoje
    elif periodo == "Mês Atual":
        dt_inicio = datetime.date(data_hoje.year, data_hoje.month, 1)
        dt_fim = data_hoje
    elif periodo == "Ano Atual":
        dt_inicio = datetime.date(data_hoje.year, 1, 1)
        dt_fim = data_hoje
    else:
        with col_f2:
            dt_inicio = st.date_input("Data Inicial", data_hoje - datetime.timedelta(days=30))
        with col_f3:
            dt_fim = st.date_input("Data Final", data_hoje)

    st.divider()
    str_inicio = f"{dt_inicio.strftime('%Y-%m-%d')} 00:00:00"
    str_fim = f"{dt_fim.strftime('%Y-%m-%d')} 23:59:59"

    conn = get_connection()
    if st.session_state["perfil"] == "Admin":
        df_m = pd.read_sql_query("SELECT m.id as 'ID', m.data as 'Data', m.tipo as 'Tipo', m.sku as 'SKU', p.nome as 'Produto', m.quantidade as 'Qtd', m.usuario as 'Usuário', m.descricao as 'Descrição', m.status as 'Status' FROM movimentacoes m JOIN produtos p ON m.sku = p.sku WHERE m.data BETWEEN ? AND ? ORDER BY m.id DESC", conn, params=(str_inicio, str_fim))
    else:
        df_m = pd.read_sql_query("SELECT m.id as 'ID', m.data as 'Data', m.tipo as 'Tipo', m.sku as 'SKU', p.nome as 'Produto', m.quantidade as 'Qtd', m.usuario as 'Usuário', m.descricao as 'Descrição', m.status as 'Status' FROM movimentacoes m JOIN produtos p ON m.sku = p.sku WHERE m.usuario = ? AND m.data BETWEEN ? AND ? ORDER BY m.id DESC", conn, params=(st.session_state["usuario"], str_inicio, str_fim))
    conn.close()

    if not df_m.empty:
        st.dataframe(df_m, use_container_width=True)
    else:
        st.info("Nenhuma movimentação no período.")

# --- ABA CORREÇÃO ---
with aba_ajuste:
    st.subheader("⚠️ Correção e Estorno de Lançamentos")
    if st.session_state["perfil"] == "Admin":
        conn = get_connection()
        df_sol = pd.read_sql_query("SELECT s.id as 'ID_Solicitacao', s.movimentacao_id as 'ID_Mov', m.sku, p.nome as 'Produto', m.tipo, m.quantidade, s.solicitante, s.motivo FROM solicitacoes_ajuste s JOIN movimentacoes m ON s.movimentacao_id = m.id JOIN produtos p ON m.sku = p.sku WHERE s.status = 'Pendente'", conn)
        conn.close()
        if not df_sol.empty:
            st.dataframe(df_sol, use_container_width=True)
            with st.form("form_aprova"):
                sid = st.selectbox("Solicitação ID", df_sol["ID_Solicitacao"].tolist())
                acao = st.radio("Ação", ["Aprovar", "Rejeitar"], horizontal=True)
                if st.form_submit_button("Processar"):
                    conn = get_connection()
                    c = conn.cursor()
                    c.execute("SELECT m.sku, m.tipo, m.quantidade FROM solicitacoes_ajuste s JOIN movimentacoes m ON s.movimentacao_id = m.id WHERE s.id = ?", (sid,))
                    sku_m, tipo_m, qtd_m = c.fetchone()
                    if "Aprovar" in acao:
                        f = -1 if tipo_m == "Entrada" else 1
                        c.execute("UPDATE produtos SET qtd_estoque = qtd_estoque + ? WHERE sku = ?", (qtd_m * f, sku_m))
                        c.execute("UPDATE solicitacoes_ajuste SET status = 'Aprovado' WHERE id = ?", (sid,))
                    else:
                        c.execute("UPDATE solicitacoes_ajuste SET status = 'Rejeitado' WHERE id = ?", (sid,))
                    conn.commit()
                    conn.close()
                    st.success("Processado com sucesso!")
                    st.rerun()
        else:
            st.info("Nenhuma solicitação pendente.")
    else:
        st.info("Painel de operador para solicitações.")

# --- GESTÃO DE PRODUTOS (ADMIN) ---
if st.session_state["perfil"] == "Admin":
    with aba_prod:
        st.subheader("📝 Gestão e Cadastro de Produtos")
        
        tab_p1, tab_p2, tab_p3, tab_p4, tab_p5 = st.tabs([
            "Cadastrar", "✏️ Editar", "❌ Excluir", "🗑️️ Zerar Estoques", "📥 Importar Planilha"
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
            st.subheader("📥 Importação em Lote por Planilha")
            
            df_mod = pd.DataFrame([
                {"SKU": "ALM-001", "Nome do Produto": "Papel A4", "Categoria": "Consumíveis", "Estoque Mínimo": 10, "Preço Unitário": 25.0, "Quantidade Inicial": 150}
            ])
            st.download_button("Baixar Modelo CSV", data=df_mod.to_csv(index=False).encode('utf-8'), file_name="modelo.csv", mime="text/csv")

            if "up_key" not in st.session_state:
                st.session_state["up_key"] = 0

            up_file = st.file_uploader("Enviar Planilha CSV", type=["csv"], key=f"up_{st.session_state['up_key']}")

            if up_file is not None:
                df_imp = pd.read_csv(up_file)
                st.dataframe(df_imp, use_container_width=True)

                if st.button("Executar Importação e Atualizar Estoque", type="primary"):
                    conn = get_connection()
                    c = conn.cursor()
                    count = 0
                    for _, row in df_imp.iterrows():
                        s = str(row["SKU"]).strip()
                        n = str(row["Nome do Produto"]).strip()
                        cat = str(row["Categoria"]).strip()
                        qmin = int(row.get("Estoque Mínimo", 5))
                        preco = float(row.get("Preço Unitário", 0.0))
                        qtd = int(row.get("Quantidade Inicial", 0))

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

    with aba_cat:
        st.subheader("🏷️ Categorias")
        conn = get_connection()
        st.dataframe(pd.read_sql_query("SELECT nome FROM categorias", conn), use_container_width=True)
        conn.close()

    with aba_usr:
        st.subheader("👥 Usuários")
        conn = get_connection()
        st.dataframe(pd.read_sql_query("SELECT username, perfil, status FROM usuarios", conn), use_container_width=True)
        conn.close()
