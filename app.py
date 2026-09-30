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

# Configuração responsiva e moderna
st.set_page_config(
    page_title="Almoxarifado Inteligente Pro", 
    page_icon="📦", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

st.cache_data.clear()

# --- DESIGN SYSTEM MODERNO E CORPORATIVO (CSS) ---
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
            destinatario TEXT,
            motivo TEXT,
            status TEXT DEFAULT 'Pendente',
            data_solicitacao TEXT,
            resposta_admin TEXT,
            avaliador TEXT,
            lido_gestor INTEGER DEFAULT 0,
            lido_operador INTEGER DEFAULT 0
        )
    """)

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
        c.execute("""
            INSERT OR REPLACE INTO usuarios VALUES ('admin', ?, 'Admin', 'Ativo', 'Qual a cidade natal?', ?)
        """, (hash_senha("admin123"), hash_senha("admin")))

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

# --- GERADORES DE RELATÓRIO PDF COM AJUSTE DE CÉLULAS E PARÁGRAFOS ---
def gerar_pdf_relatorio(df_produtos, titulo_relatorio):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=15, textColor=colors.HexColor('#0f172a'))
    story.append(Paragraph(f"Relatório Formal - {titulo_relatorio}", title_style))
    story.append(Paragraph(f"Emitido em: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
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
            Paragraph(f"R${r['preco_unitario']:.2f}", cell_style),
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
    story.append(Paragraph(f"Relatório: {tipo_relatorio}", title_style))
    story.append(Paragraph(f"Período: {titulo_periodo} | Emitido em: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
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

# --- TELA DE LOGIN ---
if "logado" not in st.session_state:
    st.session_state["logado"] = False
    st.session_state["usuario"] = None
    st.session_state["perfil"] = None

if "modo_login" not in st.session_state:
    st.session_state["modo_login"] = "login"

def tela_login():
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("
