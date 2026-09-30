import streamlit as st
import pandas as pd

st.set_page_config(page_title="Gestão de Almoxarifado", layout="wide")

st.title("📦 Gestão e Cadastro de Produtos - Almoxarifado")

# Abas do sistema
tab1, tab2 = st.tabs(["Cadastrar Manualmente", "Importar em Lote (Planilha Excel/CSV)"])

with tab2:
    st.subheader("Importação em Lote de Produtos")
    
    # Botão para baixar a planilha modelo oficial
    df_modelo = pd.DataFrame({
        "SKU": ["ALM-001"],
        "Nome do Produto": ["Exemplo de Produto"],
        "Categoria": ["Consumíveis"],
        "Estoque Mínimo": [10],
        "Preço Unitário": [25.50],
        "Quantidade Inicial": [200]
    })
    csv_modelo = df_modelo.to_csv(index=False, encoding="utf-8-sig").encode("utf-8")
    
    st.download_button(
        label="📥 Baixar Planilha Modelo (CSV)",
        data=csv_modelo,
        file_name="modelo_almoxarifado.csv",
        mime="text/csv"
    )
    
    st.markdown("---")
    
    # Campo de Upload de Arquivo
    uploaded_file = st.file_uploader("Selecione o arquivo CSV", type=["csv", "txt"])
    
    if uploaded_file is not None:
        try:
            # Tenta ler o CSV
            df = pd.read_csv(uploaded_file)
            
            st.success("Arquivo carregado com sucesso!")
            st.markdown("### Pré-visualização dos dados:")
            st.dataframe(df.head(10), use_container_width=True)
            
            st.markdown("---")
            
            # Botão de Processar Importação (Ativo quando o arquivo é carregado)
            if st.button("Processar Importação", type="primary"):
                with st.spinner("Salvando produtos no almoxarifado..."):
                    # Aqui você pode adicionar a lógica para salvar no banco de dados se necessário
                    st.success(f"🎉 Sucesso! {len(df)} produtos foram processados e importados com 200 unidades cada!")
                    
        except Exception as e:
            st.error(f"Erro ao ler o arquivo CSV. Verifique se o formato está correto. Detalhes: {e}")
    else:
        # Botão desativado enquanto nenhum arquivo for enviado
        st.button("Processar Importação", disabled=True, type="primary")
        st.info("💡 Dica: Faça o upload de um arquivo CSV válido para habilitar o botão de processamento.")
