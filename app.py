# app.py - VERSÃO FINAL REVISADA E COMPLETA

import streamlit as st
import pandas as pd
import importlib.util
from datetime import datetime, timedelta
import webbrowser
import os
import logging
import time

# --- Configuração da Página ---
st.set_page_config(page_title="Hub de Vendas", layout="wide")

# --- Carrega o main.py ---
try:
    spec = importlib.util.spec_from_file_location("main", "main.py")
    main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main)
except FileNotFoundError:
    st.error("ERRO CRÍTICO: O arquivo 'main.py' não foi encontrado.")
    st.stop()

# --- Funções de Compatibilidade e Estado ---
def rerun():
    try: st.rerun()
    except AttributeError: st.experimental_rerun()

if 'tokens' not in st.session_state:
    st.session_state.tokens = main.carregar_tokens()

# --- Funções da Interface ---
def handle_authentication():
    if st.session_state.tokens:
        expires_at = datetime.fromisoformat(st.session_state.tokens['expires_at'])
        if expires_at < datetime.now() + timedelta(minutes=10):
            with st.spinner("Token expirado. Renovando..."):
                novos_tokens = main.renovar_token(st.session_state.tokens.get('refresh_token'))
                if novos_tokens: st.session_state.tokens = novos_tokens
                else: st.session_state.tokens = None; rerun()
    if not st.session_state.tokens:
        st.warning("Você não está autenticado.")
        auth_url, code_verifier = main.iniciar_autenticacao(interactive=False)
        if 'code_verifier' not in st.session_state: st.session_state.code_verifier = code_verifier
        if st.button("1. Gerar Código de Autorização (Login no ML)"): webbrowser.open(auth_url)
        auth_code = st.text_input("2. Cole o código da URL aqui")
        if st.button("3. Confirmar e Autenticar"):
            if auth_code:
                with st.spinner("Autenticando..."):
                    novos_tokens = main.obter_token_com_codigo(auth_code, st.session_state.code_verifier)
                    if novos_tokens: st.session_state.tokens = novos_tokens; rerun()
                    else: st.error("Código inválido.")
            else: st.error("O campo do código não pode estar vazio.")
        return False
    return True

def carregar_dados_estoque(_tokens):
    worksheet = main.conectar_google_sheets()
    if worksheet:
        df = main.ler_estoque_online(worksheet)
        if df is not None and not df.empty:
            return df, worksheet
    return pd.DataFrame(), None

# --- LÓGICA PRINCIPAL DA INTERFACE ---
st.title("🚀 Hub de Vendas")

if handle_authentication():
    estoque_df, worksheet = carregar_dados_estoque(st.session_state.tokens['access_token'])
    if worksheet is None or estoque_df.empty:
        st.error("Não foi possível carregar os dados do estoque.")
    else:
        tab_dashboard, tab_entrada, tab_financeiro, tab_sincronizacao, tab_logs = st.tabs([
            "📊 Dashboard", "📦 Entrada de Estoque", "💰 Financeiro", "⚙️ Sincronização", "📜 Histórico"
        ])

        with tab_dashboard:
            st.header("Estoque Detalhado")
            colunas_visiveis = ['SKU', 'PRODUTO', 'QUANTIDADE_LOCAL', 'PRECO_CUSTO']
            st.info("💡 Dica: 1. Clique duas vezes para editar. 2. Pressione 'Enter' para confirmar. 3. Clique no botão 'Salvar Alterações' abaixo.")
            df_editado = st.data_editor(
                estoque_df[colunas_visiveis],
                key="editor_estoque_final",
                column_config={"PRECO_CUSTO": st.column_config.NumberColumn("Preço de Custo", format="R$ %.2f")}
            )
            if st.button("✅ Salvar Alterações na Planilha", type="primary"):
                edited_rows = st.session_state["editor_estoque_final"].get("edited_rows", {})
                if edited_rows:
                    with st.spinner("Salvando alterações no Google Sheets..."):
                        updates_realizadas = 0
                        for row_index, changes in edited_rows.items():
                            sku_alterado = estoque_df.iloc[row_index]['SKU']
                            nova_qtd = df_editado.iloc[row_index]['QUANTIDADE_LOCAL']
                            novo_custo = df_editado.iloc[row_index]['PRECO_CUSTO']
                            sucesso = main.atualizar_linha_estoque(sku_alterado, nova_qtd, novo_custo)
                            if sucesso: updates_realizadas += 1
                        st.success(f"{updates_realizadas} produto(s) atualizado(s) com sucesso!")
                        rerun()
                else:
                    st.warning("Nenhuma alteração detectada para salvar.")
        
        with tab_entrada:
            st.header("Registrar Nova Compra de Produtos")
            lista_skus = estoque_df['SKU'].tolist()
            
            with st.form(key="form_nova_compra"):
                sku_selecionado = st.selectbox("1. Selecione o SKU do produto", options=lista_skus)
                qtd_comprada = st.number_input("2. Digite a quantidade comprada", min_value=1, step=1)
                custo_compra = st.number_input("3. Digite o custo unitário desta compra", min_value=0.01, format="%.2f", step=0.01)
                submit_button = st.form_submit_button(label="Registrar Compra e Recalcular Custo Médio")

            if submit_button:
                if not sku_selecionado or not qtd_comprada or not custo_compra:
                    st.error("Por favor, preencha todos os campos.")
                else:
                    with st.spinner(f"Registrando compra de {qtd_comprada} unidade(s) do SKU {sku_selecionado}..."):
                        sucesso, mensagem = main.registrar_compra_e_recalcular_custo(sku_selecionado, qtd_comprada, custo_compra)
                    
                    if sucesso:
                        st.success(mensagem)
                        st.info("O Dashboard de Estoque será atualizado com os novos valores. Recarregando...")
                        time.sleep(2)
                        rerun()
                    else:
                        st.error(mensagem)

        with tab_financeiro:
            st.header("Análise Financeira por Período")
            today = datetime.now()
            col1, col2 = st.columns(2)
            with col1: data_inicio = st.date_input("Data de Início", today - timedelta(days=7))
            with col2: data_fim = st.date_input("Data Final", today)
            if st.button("🔍 Analisar Período", type="primary", key="btn_financeiro"):
                if data_inicio > data_fim: st.error("A data de início não pode ser posterior à data final.")
                else:
                    with st.spinner("Buscando e processando dados financeiros..."):
                        df_financeiro = main.analisar_financeiro_periodo(st.session_state.tokens['access_token'], estoque_df, data_inicio, data_fim)
                    if df_financeiro is not None and not df_financeiro.empty:
                        st.success("Análise concluída!")
                        total_vendas = df_financeiro['Valor Venda'].sum()
                        total_taxas = df_financeiro['Taxa ML'].sum()
                        total_envio = df_financeiro['Custo Envio'].sum()
                        total_custo_produto = df_financeiro['Custo Produto'].sum()
                        total_lucro = df_financeiro['Lucro Bruto'].sum()
                        m1, m2, m3, m4, m5 = st.columns(5)
                        m1.metric("Receita Bruta", f"R$ {total_vendas:,.2f}")
                        m2.metric("Taxas ML", f"R$ {total_taxas:,.2f}")
                        m3.metric("Custo Envio", f"R$ {total_envio:,.2f}")
                        m4.metric("Custo Produtos", f"R$ {total_custo_produto:,.2f}")
                        m5.metric("Lucro Bruto", f"R$ {total_lucro:,.2f}", delta=f"{(total_lucro/total_vendas*100 if total_vendas > 0 else 0):.1f}% Margem")
                        st.dataframe(df_financeiro.style.format({
                            'Valor Venda': 'R$ {:,.2f}', 'Taxa ML': 'R$ {:,.2f}',
                            'Custo Envio': 'R$ {:,.2f}', 'Custo Produto': 'R$ {:,.2f}',
                            'Lucro Bruto': 'R$ {:,.2f}'
                        }))
                    else:
                        st.warning("Nenhuma venda entregue foi encontrada no período selecionado.")

        with tab_sincronizacao:
            st.header("Sincronização Completa")
            st.warning("Este processo pode levar alguns minutos. O resultado será salvo no Histórico de Logs.")
            if st.button("▶️ Iniciar Sincronização Completa", type="primary", key="btn_sinc"):
                try:
                    with st.spinner("Executando ciclo completo... Verifique o Histórico de Logs para detalhes."):
                        sucesso_baixa = main.buscar_e_processar_vendas(st.session_state.tokens['access_token'], estoque_df, worksheet)
                        if sucesso_baixa:
                            estoque_atualizado_df = main.ler_estoque_online(worksheet)
                            if estoque_atualizado_df is not None:
                                main.sincronizar_estoque_para_ml(st.session_state.tokens['access_token'], estoque_atualizado_df, worksheet)
                            else:
                                raise Exception("Falha ao reler o estoque da planilha após a baixa.")
                        else:
                            raise Exception("Falha na etapa de baixar vendas.")
                    st.success("Ciclo de sincronização finalizado com sucesso!")
                    st.info("Vá para a aba '📜 Histórico' para ver o relatório detalhado.")
                except Exception as e:
                    st.error(f"Ocorreu um erro durante a sincronização: {e}")
                    logging.error(f"Erro fatal na sincronização completa: {e}")

        with tab_logs:
            st.header("Histórico de Atividades")
            if st.button("🔄 Atualizar Logs", key="btn_logs"): rerun()
            log_file_path = 'data/hub_vendas.log'
            if os.path.exists(log_file_path):
                with open(log_file_path, 'r', encoding='utf-8') as f:
                    log_content = f.readlines()[::-1] 
                st.code('\n'.join(log_content), language='log')
            else:
                st.info("Nenhum arquivo de log encontrado.")
