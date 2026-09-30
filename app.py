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
    c.execute("CREATE TABLE IF NOT EXISTS ordens_servico (id INTEGER PRIMARY KEY AUTOINCREMENT, movimentacao_id INTEGER, data_abertura TEXT, data_limite TEXT, destino TEXT, usuario_abertura TEXT, usuario_consumidor TEXT, observacoes TEXT, status TEXT DEFAULT 'Aberta')")
    
    # Tabela para fotos georreferenciadas com suporte offline/fila de sincronização
    c.execute("CREATE TABLE IF NOT EXISTS fotos_os (id INTEGER PRIMARY KEY AUTOINCREMENT, os_id INTEGER, imagem BLOB, latitude TEXT, longitude TEXT, data_captura TEXT, status_sincronizacao TEXT DEFAULT 'Pendente')")

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

def gerar_pdf_ordem_servico(os_id, data_abertura, data_limite, destino, usuario_abertura, usuario_consumidor, observacoes, produto_nome, sku, tipo_mov, qtd):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#0f172a'), alignment=1)
    subtitle_style = ParagraphStyle('SubStyle', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#334155'), alignment=1)
    section_style = ParagraphStyle('SecStyle', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor('#0f172a'), spaceBefore=10, spaceAfter=5)
    normal_style = ParagraphStyle('NormStyle', parent=styles['Normal'], fontSize=9, leading=12, textColor=colors.HexColor('#0f172a'))
    header_table_style = ParagraphStyle('HeadTableStyle', parent=styles['Normal'], fontSize=8.5, leading=11, textColor=colors.whitesmoke, fontName='Helvetica-Bold')

    story.append(Paragraph(f"ORDEM DE SERVIÇO DE ALMOXARIFADO — Nº {os_id:04d}", title_style))
    story.append(Paragraph(f"Emitido em: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}", subtitle_style))
    story.append(Spacer(1, 15))

    data_info = [
        [Paragraph("**Data de Abertura:**", normal_style), Paragraph(str(data_abertura), normal_style), Paragraph("**Prazo Máximo (Data Limite):**", normal_style), Paragraph(str(data_limite), normal_style)],
        [Paragraph("**Quem Abriu (Operacional):**", normal_style), Paragraph(str(usuario_abertura), normal_style), Paragraph("**Utilizador / Consumidor:**", normal_style), Paragraph(str(usuario_consumidor), normal_style)],
        [Paragraph("**Destino do Material:**", normal_style), Paragraph(str(destino), normal_style), Paragraph("**Status da OS:**", normal_style), Paragraph("Aberta / Pendente", normal_style)]
    ]
    t_info = Table(data_info, colWidths=[130, 140, 150, 115])
    t_info.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc'))
    ]))
    story.append(t_info)
    story.append(Spacer(1, 15))

    story.append(Paragraph("Detalhes da Operação / Item Movimentado", section_style))
    data_prod = [
        [Paragraph("SKU", header_table_style), Paragraph("Produto / Material", header_table_style), Paragraph("Tipo de Operação", header_table_style), Paragraph("Quantidade", header_table_style)],
        [Paragraph(str(sku), normal_style), Paragraph(str(produto_nome), normal_style), Paragraph(str(tipo_mov), normal_style), Paragraph(str(qtd), normal_style)]
    ]
    t_prod = Table(data_prod, colWidths=[80, 240, 110, 105])
    t_prod.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0f172a')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_prod)
    story.append(Spacer(1, 15))

    story.append(Paragraph("Observações e Instruções Específicas", section_style))
    data_obs = [[Paragraph(str(observacoes) if observacoes else "Nenhuma observação informada.", normal_style)]]
    t_obs = Table(data_obs, colWidths=[535])
    t_obs.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#fffbeb'))
    ]))
    story.append(t_obs)
    story.append(Spacer(1, 45))

    data_ass = [
        [Paragraph("_"*40, normal_style), Paragraph("_"*40, normal_style)],
        [Paragraph("**Assinatura do Operacional (Emissor)**", normal_style), Paragraph("**Assinatura do Supervisor Imediato**", normal_style)]
    ]
    t_ass = Table(data_ass, colWidths=[265, 270])
    t_ass.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'TOP')
    ]))
    story.append(t_ass)

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

if "upload_counter" not in st.session_state:
    st.session_state["upload_counter"] = 0

if "ultima_os_gerada" not in st.session_state:
    st.session_state["ultima_os_gerada"] = None

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

        if perfil_atual in ["Admin", "Supervisor"]:
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

        if perfil_atual in ["Admin", "Supervisor"]:
            st.dataframe(df_produtos[['sku', 'nome', 'categoria', 'qtd_estoque', 'qtd_minima', 'status']], use_container_width=True)
    else:
        st.info("Nenhum produto cadastrado no sistema.")

with aba_mov:
    st.subheader("🔄 Lançamento de Entrada / Saída de Materiais e Emissão de OS")
    
    if st.session_state["ultima_os_gerada"] is not None:
        os_dados = st.session_state["ultima_os_gerada"]
        st.success("✅ Materiais adicionados/movimentados com sucesso! Ordem de Serviço gerada.")
        
        pdf_os_bytes = gerar_pdf_ordem_servico(
            os_dados['id'], os_dados['data_abertura'], os_dados['data_limite'], 
            os_dados['destino'], os_dados['usuario_abertura'], os_dados['usuario_consumidor'], 
            os_dados['observacoes'], os_dados['produto_nome'], os_dados['sku'], 
            os_dados['tipo_mov'], os_dados['qtd']
        )
        
        st.download_button(
            label=f"📄 Imprimir / Baixar Ordem de Serviço (OS #{os_dados['id']:04d})",
            data=pdf_os_bytes,
            file_name=f"ordem_servico_{os_dados['id']:04d}.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True
        )
        
        st.divider()
        st.subheader("📸 Registo Fotográfico Georreferenciado da OS (Offline-First)")
        st.info("Tire uma foto do local/aplicação. As coordenadas GPS serão obtidas. Se estiver sem conexão, a foto ficará guardada na fila local até sincronizar.")

        # Componente para captura de geolocalização via HTML/JS nativo no Streamlit
        loc_html = """
